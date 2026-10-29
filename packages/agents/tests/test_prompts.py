"""Prompt formatting: the matched child passage must always reach the generator.

A parent section is clipped to a character budget before it is shown. When the
child chunk that actually matched sits in the clipped-off tail, the generator
would answer from a section that no longer contains the sentence retrieval
found. format_sources must guarantee the matched passage is present verbatim.
"""

from gg_agents.prompts import _CONTEXT_CHAR_LIMIT, format_marked_sources, format_sources

_CHILD = "The sterilizer D-value shall be verified quarterly against a biological indicator."


def _parent_with_child_in_tail() -> dict[str, object]:
    # The matched child sits past the clip window, so a plain clip would drop it.
    head = "filler sentence. " * 400
    assert len(head) > _CONTEXT_CHAR_LIMIT
    return {
        "citation": "SOP-050 Rev B, 3. Procedure, p. 4",
        "text": head + _CHILD,
        "matched_child_text": _CHILD,
    }


def test_format_sources_includes_matched_child_when_clipped():
    out = format_sources([_parent_with_child_in_tail()])
    assert _CHILD in out


def test_format_marked_sources_includes_matched_child_when_clipped():
    out = format_marked_sources([(3, _parent_with_child_in_tail())])
    assert out.startswith("[3] ")
    assert _CHILD in out


def test_format_sources_unchanged_when_child_within_window():
    # A short parent whose matched child is already in view renders as a plain
    # clip — no restructuring, so existing prompts are unaffected.
    text = "Short parent section that already contains the matched passage."
    parent = {"citation": "SOP-001 Rev A, 1", "text": text, "matched_child_text": "matched passage"}
    assert format_sources([parent]) == f"[1] SOP-001 Rev A, 1\n{text}"


def test_format_sources_without_matched_child_falls_back_to_clip():
    # Synthetic parents (tool/external results) carry no matched_child_text; they
    # must still render as a plain clip rather than error.
    text = "Structured tool result table rendered as-is."
    parent = {"citation": "Complaint count — registers", "text": text}
    assert format_sources([parent]) == f"[1] Complaint count — registers\n{text}"
