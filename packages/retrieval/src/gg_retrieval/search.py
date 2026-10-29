"""Hybrid dense + BM25-sparse search via the Qdrant Query API.

Both branches prefetch under the same payload filter; server-side RRF fuses
them. Filters are exact keyword matches on indexed payload fields — an audit
question scoped to one document or type must never leak neighbors in.
"""

from datetime import UTC, date, datetime

from gg_common.settings import QdrantSettings, RetrievalSettings
from gg_common.sparse import SparseVector
from gg_common.vectors import DENSE_VECTOR, SPARSE_VECTOR
from qdrant_client import AsyncQdrantClient, models

# Sentinel: skip the status condition entirely (e.g. audits of obsoleted docs).
ANY_STATUS = "any"

# Point-in-time record and event families carry no controlled effective
# interval: a complaint, NCR, CAPA, MDR, device history record, audit, review,
# or verification report is a fact of the date it happened, not a versioned
# controlled document. These types may match an as-of query without a bounded
# [from, to) window — but a record that carries a real date must still not be
# returned for an as-of moment that predates it (see _as_of_conditions). Every
# other type — a versioned controlled document (SOP, WI, quality manual,
# training_matrix, ...) or any unrecognized type — must present a real
# effective_from to be returned as the revision in effect on a date. An undated
# (null effective_from) controlled revision is obsolete or malformed and must
# never surface as the current evidence for an as-of question.
#
# training_matrix is deliberately NOT here: it carries revision and effective
# metadata like any controlled document, so an as-of training query must select
# the revision in effect on the date, not every matrix revision ever indexed.
AS_OF_TIMELESS_DOC_TYPES = frozenset(
    {
        "complaint",
        "mdr",
        "emdr",
        "ncr",
        "capa",
        "dhr",
        "dhr_scanned",
        "verification_report",
        "supplier_audit",
        "internal_audit",
        "management_review",
    }
)


def build_filter(
    *,
    doc_type: str | None = None,
    doc_key: str | None = None,
    revision: str | None = None,
    status: str | None = None,
    as_of: date | None = None,
    now: date | None = None,
    allowed_levels: tuple[str, ...] | None = None,
) -> models.Filter | None:
    must: list[models.Condition] = []
    if doc_type:
        must.append(models.FieldCondition(key="doc_type", match=models.MatchValue(value=doc_type)))
    if doc_key:
        must.append(models.FieldCondition(key="doc_key", match=models.MatchValue(value=doc_key)))
    if revision:
        # Exact match on the indexed 'revision' payload field: a query scoped to
        # one revision must never return a neighboring revision of the same
        # document. Combined with doc_key this is the hard one-document/
        # one-revision non-leakage boundary the question's lexical hints imply.
        must.append(models.FieldCondition(key="revision", match=models.MatchValue(value=revision)))
    if status and status != ANY_STATUS:
        must.append(models.FieldCondition(key="status", match=models.MatchValue(value=status)))
    if as_of:
        must.extend(_as_of_conditions(as_of))
    elif now:
        # Default (non-as-of) retrieval still binds to the revision in effect
        # *now*, not merely whatever carries the 'effective' status label. The
        # same [from, to) window as an as-of query — with today's date — is
        # defense in depth against a registry status that lags reconciliation
        # (a superseded or not-yet-effective revision left labeled effective).
        must.extend(_as_of_conditions(now))
    if allowed_levels is not None:
        # Exact match against the labeled level: points indexed before labeling
        # existed have no access_level and match nothing. Fail closed — an
        # unlabeled chunk is invisible to a restricted caller, never leaked.
        must.append(
            models.FieldCondition(
                key="access_level", match=models.MatchAny(any=list(allowed_levels))
            )
        )
    return models.Filter(must=must) if must else None


def _as_of_conditions(as_of: date) -> list[models.Condition]:
    """Match the controlled revision effective on the given date:
    effective_from <= date < effective_to, with [from, to) semantics so a
    revision's effective date excludes its predecessor. A null effective_to
    means still in effect. Point-in-time records (complaints, NCRs, forms) carry
    no effective interval, but a record that records its own date must not be
    returned for an as-of moment before it happened — so records match only when
    undated (permissive: absence of a date cannot be proven to post-date the
    question) or dated on/before the moment. A controlled document with a null
    effective_from is obsolete or malformed and never matches — it must not be
    returned as the revision in effect on an as-of date."""
    moment = datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC)
    controlled_in_effect = models.Filter(
        must=[
            # A real start date on or before the moment — a null effective_from
            # is not accepted here, so an undated controlled revision is excluded.
            models.FieldCondition(key="effective_from", range=models.DatetimeRange(lte=moment)),
            models.Filter(
                should=[
                    models.IsEmptyCondition(is_empty=models.PayloadField(key="effective_to")),
                    models.FieldCondition(
                        key="effective_to", range=models.DatetimeRange(gt=moment)
                    ),
                ]
            ),
        ]
    )
    timeless_record_in_scope = models.Filter(
        must=[
            models.FieldCondition(
                key="doc_type",
                match=models.MatchAny(any=sorted(AS_OF_TIMELESS_DOC_TYPES)),
            ),
            # Event-timestamp gate: a record dated after the moment is out of
            # scope; an undated record stays permissive. effective_from is the
            # record's own event date on record points (no supersession runs
            # for single-version records, so it never carries a controlled
            # [from, to) window).
            models.Filter(
                should=[
                    models.IsEmptyCondition(is_empty=models.PayloadField(key="effective_from")),
                    models.FieldCondition(
                        key="effective_from", range=models.DatetimeRange(lte=moment)
                    ),
                ]
            ),
        ]
    )
    return [
        models.Filter(
            should=[
                # Timeless record types: dated on/before the moment, or undated.
                timeless_record_in_scope,
                # Controlled documents: a real bounded effective interval only.
                controlled_in_effect,
            ]
        )
    ]


async def hybrid_search(
    client: AsyncQdrantClient,
    qdrant: QdrantSettings,
    retrieval: RetrievalSettings,
    *,
    dense_vector: list[float],
    sparse_vector: SparseVector,
    query_filter: models.Filter | None,
    limit: int,
) -> list[models.ScoredPoint]:
    prefetch = [
        models.Prefetch(
            query=dense_vector,
            using=DENSE_VECTOR,
            filter=query_filter,
            limit=retrieval.prefetch_dense,
        ),
        models.Prefetch(
            query=models.SparseVector(
                indices=list(sparse_vector.indices), values=list(sparse_vector.values)
            ),
            using=SPARSE_VECTOR,
            filter=query_filter,
            limit=retrieval.prefetch_sparse,
        ),
    ]
    response = await client.query_points(
        collection_name=qdrant.collection,
        prefetch=prefetch,
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit,
        with_payload=True,
    )
    return list(response.points)
