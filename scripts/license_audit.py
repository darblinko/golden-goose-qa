"""License audit over the installed Python environment and the web npm lockfile.

    uv run python scripts/license_audit.py

Every installed distribution (and every npm package in apps/web) must declare a
license on the allowlist (permissive or weak-copyleft). Strong copyleft or
undeclared licenses fail the build so a dependency bump cannot quietly change
the project's licensing posture. Vulnerability scanning is pip-audit / npm
audit's job (see ci.yml); this script only judges licenses, from
importlib.metadata and the npm lockfile — no third-party dependency.

License declarations are SPDX expressions, not plain strings: `A AND B` means
both licenses bind (both must be allowed), `A OR B` means either may be chosen
(one allowed is enough). Substring matching would let an allowed token mask a
forbidden one — `LGPL AND GPL` reads as "contains LGPL" and slips through — so
every term is parsed and classified individually and combined by its operator.
"""

import importlib.metadata
import json
import sys
from pathlib import Path

ALLOWED_TOKENS = (
    "mit",
    "bsd",
    "apache",
    "isc",
    "python software foundation",
    "psf",
    "mpl",
    "mozilla public license",
    "zlib",
    "unlicense",
    "cc0",
    "public domain",
    "cc-by-4.0",
    "cc-by-3.0",
    "python-2.0",
    "lgpl",
    "lesser general public",
)

# GPL (without the L) is strong copyleft; matched after LGPL is ruled out.
FORBIDDEN_TOKENS = ("gpl",)

# Distributions whose metadata carries no usable license declaration but
# whose license is known. Keep this list short and cited.
KNOWN_EXCEPTIONS: dict[str, str] = {}

# npm packages whose lockfile entry lacks a usable license but whose license is
# known. Keep short and cited; never use to admit a forbidden license.
NPM_KNOWN_EXCEPTIONS: dict[str, str] = {}

# First-party workspace packages: not third-party dependencies, so the policy
# does not apply. Matched exactly — a prefix match would exempt any dependency
# that happened to start with "gg-".
FIRST_PARTY_NAMES = frozenset(
    {
        "gg-common",
        "gg-ingestion",
        "gg-retrieval",
        "gg-agents",
        "gg-evals",
        "gg-synthdata",
        "goldengoose-api",
    }
)

_SPDX_OPERATORS = frozenset({"AND", "OR", "WITH"})


def _classifier_licenses(dist: importlib.metadata.Distribution) -> list[str]:
    classifiers = dist.metadata.get_all("Classifier") or []
    return [
        str(value).split("::")[-1].strip()
        for value in classifiers
        if str(value).startswith("License ::")
    ]


def declared_license(dist: importlib.metadata.Distribution) -> str:
    """Best available declaration, for display: PEP 639 expression, then
    classifiers (joined by OR — multiple classifiers are alternative
    offerings), then the free-text License field."""
    expression = dist.metadata.get("License-Expression")
    if expression:
        return expression.strip()
    classifiers = _classifier_licenses(dist)
    if classifiers:
        return " OR ".join(classifiers)
    return (dist.metadata.get("License") or "").strip()


def is_allowed(license_text: str) -> bool:
    """Whether a single atomic license names a permissive/weak-copyleft term."""
    lowered = license_text.lower()
    if not lowered:
        return False
    return any(token in lowered for token in ALLOWED_TOKENS)


def is_forbidden(license_text: str) -> bool:
    """Whether a single atomic license names strong copyleft (GPL, not LGPL)."""
    lowered = license_text.lower()
    if "lgpl" in lowered or "lesser general public" in lowered:
        return False
    return "gpl" in lowered or "general public license" in lowered


def _atom_acceptable(atom: str) -> bool:
    """A single license term is acceptable only when it is on the allowlist and
    is not strong copyleft. Unknown terms fail closed."""
    return is_allowed(atom) and not is_forbidden(atom)


def _tokenize(expression: str) -> list[str]:
    return expression.replace("(", " ( ").replace(")", " ) ").split()


class _ParseError(RuntimeError):
    pass


def _parse_or(tokens: list[str], pos: int) -> tuple[bool, int]:
    value, pos = _parse_and(tokens, pos)
    while pos < len(tokens) and tokens[pos] == "OR":
        right, pos = _parse_and(tokens, pos + 1)
        value = value or right
    return value, pos


def _parse_and(tokens: list[str], pos: int) -> tuple[bool, int]:
    value, pos = _parse_primary(tokens, pos)
    while pos < len(tokens) and tokens[pos] == "AND":
        right, pos = _parse_primary(tokens, pos + 1)
        value = value and right
    return value, pos


def _parse_primary(tokens: list[str], pos: int) -> tuple[bool, int]:
    if pos >= len(tokens):
        raise _ParseError("unexpected end of expression")
    if tokens[pos] == "(":
        value, pos = _parse_or(tokens, pos + 1)
        if pos >= len(tokens) or tokens[pos] != ")":
            raise _ParseError("unbalanced parenthesis")
        return value, pos + 1
    if tokens[pos] in {")", "AND", "OR", "WITH"}:
        raise _ParseError(f"unexpected operator {tokens[pos]!r}")
    # A license id is one or more words up to the next operator or paren; free
    # text ("GNU General Public License v2") counts as a single term. A WITH
    # exception attaches to the license and does not relax the classification.
    words: list[str] = []
    while (
        pos < len(tokens) and tokens[pos] not in _SPDX_OPERATORS and tokens[pos] not in {"(", ")"}
    ):
        words.append(tokens[pos])
        pos += 1
    value = _atom_acceptable(" ".join(words))
    if pos < len(tokens) and tokens[pos] == "WITH":
        pos += 1  # consume the exception id/phrase; acceptability is the license's
        while (
            pos < len(tokens)
            and tokens[pos] not in _SPDX_OPERATORS
            and tokens[pos] not in {"(", ")"}
        ):
            pos += 1
    return value, pos


def is_acceptable(declaration: str) -> bool:
    """Parse an SPDX license expression and decide it against policy. Any parse
    failure, empty declaration, or unknown term fails closed. Assumes real SPDX
    grammar — parentheses are treated as grouping, so do not hand this prose
    (see acceptable_declaration for the mixed case)."""
    tokens = _tokenize(declaration)
    if not tokens:
        return False
    try:
        value, pos = _parse_or(tokens, 0)
    except _ParseError:
        return False
    if pos != len(tokens):
        return False
    return value


def _has_spdx_operator(text: str) -> bool:
    return any(token in _SPDX_OPERATORS for token in text.split())


def acceptable_declaration(text: str) -> bool:
    """Decide one license declaration that may be a real SPDX expression or free
    text. Only strings carrying SPDX operators get the grouping parser; prose
    like "Mozilla Public License 2.0 (MPL 2.0)" is classified atomically so its
    annotation parentheses are not mistaken for SPDX grouping."""
    if _has_spdx_operator(text):
        return is_acceptable(text)
    return _atom_acceptable(text)


def dist_acceptable(dist: importlib.metadata.Distribution) -> bool:
    """Policy decision for one distribution. A real License-Expression is parsed
    as SPDX; multiple classifiers are alternative offerings (any acceptable one
    carries the package); a free-text License field is judged in the mixed
    SPDX-or-prose path."""
    expression = dist.metadata.get("License-Expression")
    if expression:
        return is_acceptable(expression.strip())
    classifiers = _classifier_licenses(dist)
    if classifiers:
        return any(_atom_acceptable(entry) for entry in classifiers)
    return acceptable_declaration((dist.metadata.get("License") or "").strip())


def audit_environment() -> list[tuple[str, str]]:
    """Returns (name, license) for every distribution that fails the policy."""
    violations = []
    for dist in importlib.metadata.distributions():
        name = (dist.metadata.get("Name") or "unknown").lower()
        if name in KNOWN_EXCEPTIONS or name in FIRST_PARTY_NAMES:
            continue
        if not dist_acceptable(dist):
            violations.append((name, declared_license(dist) or "no license metadata"))
    return sorted(set(violations))


def _npm_license(entry: dict) -> str:
    """The license declaration for one lockfile package. Handles the SPDX string
    form, the legacy {"type": ...} object, and the legacy licenses[] list."""
    license_field = entry.get("license")
    if isinstance(license_field, str):
        return license_field.strip()
    if isinstance(license_field, dict):
        return str(license_field.get("type", "")).strip()
    legacy = entry.get("licenses")
    if isinstance(legacy, list):
        types = [str(item.get("type", "")).strip() for item in legacy if isinstance(item, dict)]
        return " OR ".join(t for t in types if t)
    return ""


def audit_npm(lockfile: Path) -> list[tuple[str, str]]:
    """Returns (name, license) for every npm package that fails the policy. The
    lockfile (v2/v3) embeds each package's license, so no install is needed."""
    data = json.loads(lockfile.read_text())
    violations = []
    for key, entry in data.get("packages", {}).items():
        if not key:  # the root project entry, not a dependency
            continue
        name = key.split("node_modules/")[-1]
        if name in NPM_KNOWN_EXCEPTIONS:
            continue
        license_text = _npm_license(entry)
        if not license_text or not acceptable_declaration(license_text):
            violations.append((name, license_text or "no license metadata"))
    return sorted(set(violations))


def _report(kind: str, violations: list[tuple[str, str]], total: int) -> None:
    print(f"{kind} license audit FAILED: {len(violations)} of {total}", file=sys.stderr)
    for name, license_text in violations:
        print(f"  {name}: {license_text}", file=sys.stderr)


def main() -> int:
    py_violations = audit_environment()
    py_total = sum(1 for _ in importlib.metadata.distributions())

    lockfile = Path(__file__).resolve().parents[1] / "apps" / "web" / "package-lock.json"
    npm_violations: list[tuple[str, str]] = []
    npm_total = 0
    if lockfile.exists():
        data = json.loads(lockfile.read_text())
        npm_total = sum(1 for key in data.get("packages", {}) if key)
        npm_violations = audit_npm(lockfile)
    else:
        print(f"license audit FAILED: npm lockfile not found at {lockfile}", file=sys.stderr)
        return 1

    if py_violations or npm_violations:
        if py_violations:
            _report("python", py_violations, py_total)
        if npm_violations:
            _report("npm", npm_violations, npm_total)
        print(
            "allowed: permissive or weak-copyleft (MIT/BSD/Apache/ISC/PSF/MPL/LGPL/...)."
            " Add a cited entry to KNOWN_EXCEPTIONS / NPM_KNOWN_EXCEPTIONS only for"
            " missing metadata, never to admit a forbidden license.",
            file=sys.stderr,
        )
        return 1
    print(
        f"license audit passed: {py_total} python distributions and "
        f"{npm_total} npm packages, all on the allowlist"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
