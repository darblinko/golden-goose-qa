"""The crosswalk must add counterpart vocabulary for dialect phrases and
clause citations, and must leave unrelated queries byte-identical."""

from gg_retrieval.synonyms import expand_query


class TestPhraseCrosswalk:
    def test_iso_phrase_appends_qsr_terms(self):
        expanded = expand_query("How are advisory notices initiated?")
        assert expanded.startswith("How are advisory notices initiated?\n")
        assert "field action" in expanded
        assert "recall" in expanded

    def test_match_is_case_insensitive(self):
        expanded = expand_query("VIGILANCE reporting requirements")
        assert "medical device reporting" in expanded
        assert "adverse event" in expanded

    def test_qsr_phrase_appends_iso_terms(self):
        expanded = expand_query("Where is the device master record kept?")
        assert "medical device file" in expanded

    def test_medical_device_file_maps_to_dmr_not_dhf(self):
        # The ISO medical device file is the QSR Device Master Record, not the
        # Design History File; the crosswalk must not pull in design records.
        expanded = expand_query("Where is the medical device file for MP-100?")
        assert "device master record" in expanded
        assert "design history file" not in expanded

    def test_original_query_is_preserved_verbatim(self):
        query = "Who is Top Management here?"
        expanded = expand_query(query)
        assert expanded.startswith(query)


class TestClauseCrosswalk:
    def test_iso_clause_number_maps_to_topic(self):
        expanded = expand_query("Which procedure implements Clause 8.5.2?")
        assert "CAPA" in expanded
        assert "corrective" in expanded

    def test_cfr_section_maps_to_topic(self):
        expanded = expand_query("Show compliance with 21 CFR 820.90")
        assert "nonconforming product" in expanded

    def test_cfr_part_without_subsection(self):
        expanded = expand_query("our Part 803 reporting obligations")
        assert "medical device reporting" in expanded

    def test_part_830_udi(self):
        expanded = expand_query("does Part 830 apply to this label?")
        assert "unique device identification" in expanded

    def test_three_level_iso_clause(self):
        expanded = expand_query("evidence for clause 7.5.11 compliance")
        assert "packaging" in expanded

    def test_unknown_clause_number_adds_nothing(self):
        query = "See section 9.9.9 of the contract"
        assert expand_query(query) == query


class TestWordBoundary:
    def test_embedded_substring_does_not_expand(self):
        # "competence" is a substring of "incompetence" but not a standalone
        # word there; a curated crosswalk must not fire on the embedded match.
        query = "findings of incompetence during the walkthrough"
        assert expand_query(query) == query

    def test_simple_plural_of_phrase_still_matches(self):
        # The crosswalk exists for recall; a trailing English plural on the last
        # word must not defeat it ("advisory notices", "complaint files").
        expanded = expand_query("advisory notices and complaint files")
        assert "field action" in expanded  # advisory notice(s)
        assert "complaint handling" in expanded  # complaint file(s)


class TestExpansionCap:
    def test_expansions_are_capped(self):
        # Seven distinct clause topics cited at once; the cap keeps the first
        # six in order, so the seventh (8.5.2 -> CAPA) contributes nothing while
        # the sixth (8.2.4 -> internal audit) still does.
        expanded = expand_query("clauses 4.2.4, 5.6, 6.2, 7.3, 7.4, 8.2.4, and 8.5.2 all apply")
        added = expanded.splitlines()[1]
        assert "internal" in added  # sixth source survives
        assert "CAPA" not in added  # seventh source dropped by the cap


class TestExpansionHygiene:
    def test_no_match_returns_query_unchanged(self):
        query = "What is the lot size for L250028?"
        assert expand_query(query) == query

    def test_added_terms_are_deduplicated(self):
        # Both phrases map to CAPA vocabulary; each token appears once.
        expanded = expand_query("corrective action and preventive action records")
        added = expanded.splitlines()[1].split()
        assert len(added) == len(set(added))

    def test_multiple_sources_all_contribute(self):
        expanded = expand_query("Does clause 8.2.2 cover customer feedback?")
        added = expanded.splitlines()[1]
        assert "complaint" in added
