"""ACL vocabulary tests. Every tool path derives its restriction decisions
from these functions, so the fail-closed defaults (unknown role, unknown
level) are asserted explicitly."""

from gg_common import acl


class TestAccessLevelFor:
    def test_restricted_families(self):
        for doc_type in ("complaint", "mdr", "emdr"):
            assert acl.access_level_for(doc_type) == acl.ACCESS_RESTRICTED

    def test_known_general_families(self):
        for doc_type in ("sop", "wi", "dfmea", "capa", "ncr", "trace_matrix"):
            assert acl.access_level_for(doc_type) == acl.ACCESS_GENERAL

    def test_unknown_or_missing_type_fails_closed(self):
        for doc_type in ("field_report", "", None):
            assert acl.access_level_for(doc_type) == acl.ACCESS_RESTRICTED

    def test_vocabularies_are_disjoint(self):
        assert not acl.KNOWN_GENERAL_DOC_TYPES & acl.RESTRICTED_DOC_TYPES


class TestCanReadRestricted:
    def test_privileged_roles(self):
        assert acl.can_read_restricted("admin")
        assert acl.can_read_restricted("qa_user")

    def test_auditor_cannot(self):
        assert not acl.can_read_restricted("auditor_readonly")

    def test_unknown_role_fails_closed(self):
        assert not acl.can_read_restricted("superuser")
        assert not acl.can_read_restricted("")


class TestAllowedAccessLevels:
    def test_privileged_roles_see_all_levels(self):
        assert acl.allowed_access_levels("admin") == acl.ACCESS_LEVELS
        assert acl.allowed_access_levels("qa_user") == acl.ACCESS_LEVELS

    def test_auditor_sees_general_only(self):
        assert acl.allowed_access_levels("auditor_readonly") == (acl.ACCESS_GENERAL,)

    def test_unknown_role_fails_closed(self):
        assert acl.allowed_access_levels("intruder") == (acl.ACCESS_GENERAL,)


class TestIsRestrictedKey:
    def test_restricted_prefixes(self):
        assert acl.is_restricted_key("C-2025-0142")
        assert acl.is_restricted_key("MDR-2025-0031")
        assert acl.is_restricted_key("EMDR-2025-0002")

    def test_case_insensitive(self):
        assert acl.is_restricted_key("c-2025-0142")
        assert acl.is_restricted_key("mdr-2025-0031")

    def test_general_keys(self):
        assert not acl.is_restricted_key("SOP-004")
        assert not acl.is_restricted_key("CAPA-2025-007")
        assert not acl.is_restricted_key("REQ-017")
        assert not acl.is_restricted_key("")


class TestCitationAccessLevel:
    def test_restricted_family_doc_type(self):
        assert acl.citation_access_level({"doc_key": "X", "doc_type": "complaint"}) == (
            acl.ACCESS_RESTRICTED
        )

    def test_general_family_doc_type(self):
        assert acl.citation_access_level({"doc_key": "SOP-004", "doc_type": "sop"}) == (
            acl.ACCESS_GENERAL
        )

    def test_restricted_doc_key_overrides_type(self):
        # Even a doc_type the vocabulary would call general is restricted when the
        # record key names a complaint/MDR/eMDR.
        assert acl.citation_access_level({"doc_key": "MDR-2025-0031", "doc_type": "sop"}) == (
            acl.ACCESS_RESTRICTED
        )

    def test_restricted_source_doc_key_behind_tool_result(self):
        # A graph/SQL answer read from a complaint record names it in
        # source_doc_keys; the synthetic doc_type must not launder it to general.
        citation = {
            "doc_key": "graph traversal",
            "doc_type": "tool_result",
            "source_doc_keys": ["SOP-004", "C-2025-0142"],
        }
        assert acl.citation_access_level(citation) == acl.ACCESS_RESTRICTED

    def test_tool_result_without_restricted_keys_is_general(self):
        # An aggregate count with no restricted record key is general — counts
        # are not secret, only record text is.
        citation = {
            "doc_key": "record warehouse",
            "doc_type": "tool_result",
            "source_doc_keys": [],
        }
        assert acl.citation_access_level(citation) == acl.ACCESS_GENERAL

    def test_external_result_is_general(self):
        citation = {"doc_key": "FDA MAUDE", "doc_type": "external_result"}
        assert acl.citation_access_level(citation) == acl.ACCESS_GENERAL

    def test_unknown_corpus_doc_type_fails_closed(self):
        assert acl.citation_access_level({"doc_key": "X-1", "doc_type": "field_note"}) == (
            acl.ACCESS_RESTRICTED
        )

    def test_missing_doc_type_fails_closed(self):
        assert acl.citation_access_level({"doc_key": "X-1"}) == acl.ACCESS_RESTRICTED


class TestMessageAccessLevel:
    def test_no_citations_is_general(self):
        # A user turn or an out-of-scope reply carries no citations.
        assert acl.message_access_level([]) == acl.ACCESS_GENERAL

    def test_all_general_citations(self):
        citations = [
            {"doc_key": "SOP-004", "doc_type": "sop"},
            {"doc_key": "FDA MAUDE", "doc_type": "external_result"},
        ]
        assert acl.message_access_level(citations) == acl.ACCESS_GENERAL

    def test_any_restricted_citation_restricts_the_message(self):
        citations = [
            {"doc_key": "SOP-004", "doc_type": "sop"},
            {"doc_key": "C-2025-0142", "doc_type": "complaint"},
        ]
        assert acl.message_access_level(citations) == acl.ACCESS_RESTRICTED


class TestRoleCanReadAccessLevel:
    def test_privileged_roles_read_restricted(self):
        assert acl.role_can_read_access_level("qa_user", acl.ACCESS_RESTRICTED)
        assert acl.role_can_read_access_level("admin", acl.ACCESS_RESTRICTED)

    def test_auditor_reads_general_only(self):
        assert acl.role_can_read_access_level("auditor_readonly", acl.ACCESS_GENERAL)
        assert not acl.role_can_read_access_level("auditor_readonly", acl.ACCESS_RESTRICTED)

    def test_unknown_role_fails_closed(self):
        assert not acl.role_can_read_access_level("intruder", acl.ACCESS_RESTRICTED)
