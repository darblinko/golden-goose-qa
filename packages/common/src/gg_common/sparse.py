"""BM25 sparse vectors for Qdrant, computed locally and deterministically.

Qdrant's sparse-vector IDF modifier computes the corpus IDF server-side; the
client supplies term-frequency-weighted tokens hashed to uint32 indices. Doing
the tokenization here (instead of pulling a model-download dependency) keeps
ingestion fully offline and reproducible.

Document IDs (SOP-004, CAPA-2025-007) are emitted both as compound tokens and
as parts, so an exact-ID audit query gets a very strong sparse match — the
whole reason the sparse branch exists.
"""

import re
import zlib
from dataclasses import dataclass

_K1 = 1.2
_B = 0.75
# BM25 average document length, in sparse.tokenize tokens. Corpus-derived, not a
# magic number: the mean child-chunk length over the seeded reference corpus is
# ~42 at the shipped child_chunk_tokens=350 default (a chunk yields far fewer
# BM25 tokens than whitespace tokens — stopwords drop out, only content words
# and id parts remain). A provenance test regenerates the corpus, recomputes the
# mean, and fails if this constant drifts (see ADR-0012). IDF is not held here —
# Qdrant's server-side IDF modifier supplies it.
_AVG_DOC_LEN = 42.0

_WORD_RE = re.compile(r"[a-z0-9]+")
_ID_RE = re.compile(r"\b[a-z]{1,6}-[0-9]{2,4}(?:-[0-9]{2,4})?\b")

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "if",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "which",
        "will",
        "with",
    ]
)


@dataclass(frozen=True)
class SparseVector:
    indices: tuple[int, ...]
    values: tuple[float, ...]


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    tokens = [t for t in _WORD_RE.findall(lowered) if t not in _STOPWORDS]
    tokens.extend(_ID_RE.findall(lowered))
    return tokens


def token_index(token: str) -> int:
    return zlib.crc32(token.encode("utf-8"))


def document_sparse_vector(text: str) -> SparseVector:
    """BM25 term-frequency component; Qdrant multiplies in IDF at query time."""
    tokens = tokenize(text)
    if not tokens:
        return SparseVector(indices=(), values=())
    doc_len = float(len(tokens))
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    norm = _K1 * (1.0 - _B + _B * doc_len / _AVG_DOC_LEN)
    weighted = {
        token_index(token): (tf * (_K1 + 1.0)) / (tf + norm) for token, tf in counts.items()
    }
    indices = tuple(sorted(weighted))
    return SparseVector(indices=indices, values=tuple(weighted[i] for i in indices))


def query_sparse_vector(text: str) -> SparseVector:
    """Unique query tokens with unit weight; the IDF modifier does the rest."""
    indices = tuple(sorted({token_index(t) for t in tokenize(text)}))
    return SparseVector(indices=indices, values=tuple(1.0 for _ in indices))
