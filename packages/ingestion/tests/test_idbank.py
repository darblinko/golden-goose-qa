from gg_ingestion.extract.idbank import (
    find_ids,
    find_ids_with_correction,
    normalize_id,
    split_ids,
)


def test_normalize_folds_unicode_dashes_and_case():
    assert normalize_id("sop–001") == "SOP-001"  # noqa: RUF001 — en dash on purpose
    assert normalize_id(" CAPA—2024—03 ") == "CAPA-2024-03"


def test_find_ids_orders_and_dedupes():
    text = "Per SOP-002 and RA-100; see SOP-002 again, then C-2025-0104 and DHR-L24-0012."
    assert find_ids(text) == ["SOP-002", "RA-100", "C-2025-0104", "DHR-L24-0012"]


def test_find_ids_ignores_non_family_tokens():
    assert find_ids("Part FT-210 rev B, ISO 13485:2016, none here") == []


def test_split_ids_drops_non_id_parts():
    assert split_ids("DO-001, DO-002") == ["DO-001", "DO-002"]
    assert split_ids("VTR-001; VTR-002") == ["VTR-001", "VTR-002"]
    assert split_ids("pass, fail") == []
    assert split_ids("") == []


def test_correction_recovers_unique_ocr_misreads():
    # The finding's own evidence: SOP-1O5 (O for 0) and WI-S01 (S for 5) each
    # resolve to exactly one registered id and are recovered.
    known = frozenset({"SOP-105", "WI-501"})
    assert find_ids_with_correction("cf. SOP-1O5 and WI-S01", known) == ["SOP-105", "WI-501"]


def test_correction_keeps_exact_matches_and_appends():
    known = frozenset({"SOP-105", "RA-100"})
    # Exact hits come first, deterministically; the recovered id follows.
    assert find_ids_with_correction("RA-100 governs, see SOP-1O5", known) == ["RA-100", "SOP-105"]


def test_correction_recovers_dropped_leading_zero_by_padding():
    # The reference dropped its canonical leading zero and a digit was misread as
    # a letter; padding the folded body to the registry width uniquely recovers it.
    assert find_ids_with_correction("see WI-5I", frozenset({"WI-051"})) == ["WI-051"]


def test_correction_rejects_ambiguous_match():
    # Two known ids are equally plausible corrections of the misread token, so no
    # edge is guessed — a missed reference is recoverable, a wrong edge is not.
    known = frozenset({"SOP-005", "SOP-0005"})
    assert find_ids_with_correction("ref SOP-O05", known) == []


def test_correction_leaves_unknown_loose_tokens_alone():
    # SOP-9O9 folds to SOP-909, which is not registered — no invention.
    assert find_ids_with_correction("SOP-9O9 dangles", frozenset({"SOP-105"})) == []


def test_correction_does_not_rewrite_a_clean_reference():
    # A clean, exact-shaped id is surfaced verbatim by find_ids; the correction
    # pass skips all-digit bodies, so a real id is never silently renumbered into
    # a different registered id (real-ID collision safety).
    known = frozenset({"SOP-105", "SOP-005"})
    assert find_ids_with_correction("SOP-105 only", known) == ["SOP-105"]
    assert find_ids_with_correction("SOP-05 here", known) == ["SOP-05"]


def test_correction_does_not_duplicate_an_existing_exact_match():
    known = frozenset({"SOP-105"})
    assert find_ids_with_correction("SOP-105 and its misread SOP-1O5", known) == ["SOP-105"]
