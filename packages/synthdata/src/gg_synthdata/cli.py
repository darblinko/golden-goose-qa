"""synthdata CLI: generate the Halvern corpus and verify its integrity.

`generate` writes the full corpus, golden QA sets, and a manifest with a
sha256 for every file. `verify` re-parses every emitted file, validates the
QA sets against their schema, and regenerates the corpus from the manifest
seed to prove byte-determinism.
"""

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from openpyxl import load_workbook

from gg_synthdata.qa import QaSet, SmokeQaSet, build_qa_set, build_smoke_set
from gg_synthdata.render.clinical_docs import render_clinical_corpus
from gg_synthdata.render.excel_docs import render_excel_corpus
from gg_synthdata.render.governance_docs import render_governance_corpus
from gg_synthdata.render.pdf_docs import render_pdf_corpus
from gg_synthdata.render.scanned import render_scanned_corpus
from gg_synthdata.render.word_docs import render_word_corpus
from gg_synthdata.render.xml_docs import render_xml_corpus
from gg_synthdata.world import build_world

MANIFEST_NAME = "manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_corpus(out_dir: Path, seed: int) -> dict:
    world = build_world(seed)
    corpus_dir = out_dir / "corpus"
    paths: list[Path] = []
    paths.extend(render_word_corpus(world, corpus_dir))
    paths.extend(render_excel_corpus(world, corpus_dir))
    paths.extend(render_pdf_corpus(world, corpus_dir))
    paths.extend(render_scanned_corpus(world, corpus_dir))
    paths.extend(render_xml_corpus(world, corpus_dir))
    paths.extend(render_governance_corpus(world, corpus_dir))
    paths.extend(render_clinical_corpus(world, corpus_dir))

    qa_dir = out_dir / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    qa_set = build_qa_set(world)
    golden_path = qa_dir / "golden_qa.json"
    golden_path.write_text(qa_set.model_dump_json(indent=2) + "\n")
    smoke = build_smoke_set(qa_set)
    smoke_path = qa_dir / "smoke_qa.json"
    smoke_path.write_text(smoke.model_dump_json(indent=2) + "\n")
    paths.extend([golden_path, smoke_path])

    files = sorted(
        (
            {
                "path": str(p.relative_to(out_dir)),
                "sha256": _sha256(p),
                "bytes": p.stat().st_size,
            }
            for p in paths
        ),
        key=lambda f: str(f["path"]),
    )
    return {
        "seed": seed,
        "world_today": qa_set.world_today,
        "company": world.company,
        "counts": {
            "files": len(files),
            "qa_items": len(qa_set.items),
            "qa_smoke_items": sum(1 for i in qa_set.items if i.smoke),
            "seeded_defects": len(world.defects),
        },
        "files": files,
    }


def _prune_stale(out_dir: Path, manifest: dict) -> list[str]:
    """Remove files a previous generation left behind that this run did not
    produce, so --out is an authoritative snapshot. Without this a renamed or
    dropped document lingers on disk and gets re-ingested, polluting the eval
    corpus. Returns the pruned relative paths (logged, never silently dropped)."""
    kept = {(out_dir / entry["path"]).resolve() for entry in manifest["files"]}
    kept.add((out_dir / MANIFEST_NAME).resolve())
    pruned: list[str] = []
    for path in sorted(out_dir.rglob("*")):
        if path.is_file() and path.resolve() not in kept:
            pruned.append(str(path.relative_to(out_dir)))
            path.unlink()
    for directory in sorted(out_dir.rglob("*"), reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    return pruned


def cmd_generate(out_dir: Path, seed: int) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = _write_corpus(out_dir, seed)
    (out_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n")
    pruned = _prune_stale(out_dir, manifest)
    counts = manifest["counts"]
    print(
        f"generated {counts['files']} files, {counts['qa_items']} QA items "
        f"({counts['qa_smoke_items']} smoke) at {out_dir} (seed {seed})"
    )
    if pruned:
        print(f"pruned {len(pruned)} stale file(s) from a prior run: {pruned[:5]}")
    return 0


def _check_pdf(path: Path) -> str | None:
    """A PDF must open, have at least one page, and carry real content: a digital
    record must yield extractable text; a scanned record (image-only traveler)
    must embed at least one image. A gutted file that only starts with %PDF and
    ends with %%EOF but has no pages or content fails here, not silently passes.
    """
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if len(reader.pages) < 1:
        return "PDF has no pages"
    if path.name.endswith("_scanned.pdf"):
        if not any(page.images for page in reader.pages):
            return "scanned PDF embeds no image"
    else:
        text = "".join(page.extract_text() or "" for page in reader.pages).strip()
        if not text:
            return "digital PDF has no extractable text"
    return None


def _check_parseable(path: Path) -> str | None:
    try:
        if path.suffix == ".docx":
            from docx import Document

            Document(str(path))
        elif path.suffix == ".xlsx":
            load_workbook(str(path), read_only=True).close()
        elif path.suffix == ".pdf":
            return _check_pdf(path)
        elif path.suffix == ".json":
            json.loads(path.read_text())
        elif path.suffix == ".xml":
            import xml.etree.ElementTree as ET

            ET.fromstring(path.read_text())
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def cmd_verify(out_dir: Path) -> int:
    manifest_path = out_dir / MANIFEST_NAME
    if not manifest_path.exists():
        print(f"error: {manifest_path} not found; run generate first", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text())
    problems: list[str] = []

    for entry in manifest["files"]:
        path = out_dir / entry["path"]
        if not path.exists():
            problems.append(f"missing: {entry['path']}")
            continue
        if _sha256(path) != entry["sha256"]:
            problems.append(f"hash mismatch (modified on disk): {entry['path']}")
        error = _check_parseable(path)
        if error:
            problems.append(f"unparseable: {entry['path']} ({error})")

    golden: QaSet | None = None
    try:
        golden = QaSet.model_validate_json((out_dir / "qa" / "golden_qa.json").read_text())
    except Exception as exc:
        problems.append(f"golden_qa.json schema validation failed: {exc}")

    smoke: SmokeQaSet | None = None
    try:
        smoke = SmokeQaSet.model_validate_json((out_dir / "qa" / "smoke_qa.json").read_text())
    except Exception as exc:
        problems.append(f"smoke_qa.json schema validation failed: {exc}")

    if golden is not None and smoke is not None:
        golden_by_id = {item.id: item for item in golden.items}
        divergent = next(
            (item.id for item in smoke.items if golden_by_id.get(item.id) != item), None
        )
        if divergent is not None:
            problems.append(
                f"smoke_qa.json is not an exact subset of golden_qa.json (item {divergent})"
            )

    with tempfile.TemporaryDirectory(prefix="synthdata-verify-") as tmp:
        regen = _write_corpus(Path(tmp), manifest["seed"])
        expected = {f["path"]: f["sha256"] for f in manifest["files"]}
        actual = {f["path"]: f["sha256"] for f in regen["files"]}
        if expected != actual:
            diffs = [p for p in expected if expected.get(p) != actual.get(p)]
            diffs.extend(p for p in actual if p not in expected)
            problems.append(f"determinism failure: {len(diffs)} paths differ: {diffs[:5]}")

    if problems:
        for problem in problems:
            print(f"FAIL {problem}", file=sys.stderr)
        return 1
    print(
        f"verified {len(manifest['files'])} files: hashes match, all parseable, "
        "QA schema valid, regeneration is byte-identical"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="synthdata",
        description="Generate and verify the synthetic Halvern Medical QMS corpus.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="generate the corpus, QA sets, and manifest")
    gen.add_argument("--out", default="data/synthetic", help="output directory")
    gen.add_argument("--seed", type=int, default=42, help="world seed")
    ver = sub.add_parser("verify", help="verify manifest hashes, parseability, determinism")
    ver.add_argument("--out", default="data/synthetic", help="directory to verify")
    args = parser.parse_args()
    if args.command == "generate":
        return cmd_generate(Path(args.out), args.seed)
    return cmd_verify(Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
