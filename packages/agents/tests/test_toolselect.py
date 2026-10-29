"""Deterministic router overrides and tool plans, pinned against the golden
QA phrasings they must catch — and the phrasings they must leave alone."""

from datetime import date

from gg_agents.toolselect import (
    external_plan,
    extract_as_of,
    extract_scope,
    graph_plan,
    is_rate_comparison,
    route_override,
    warehouse_plan,
)
from gg_retrieval.tools.sqlguard import validate_select
from gg_retrieval.tools.warehouse import ALLOWED_RELATIONS


class TestExtractAsOf:
    def test_iso_date(self):
        question = "What did the CAPA procedure require as of 2024-03-15?"
        assert extract_as_of(question) == date(2024, 3, 15)

    def test_corpus_date_format(self):
        question = "Which revision of SOP-011 was in effect on 15-Mar-2024?"
        assert extract_as_of(question) == date(2024, 3, 15)

    def test_month_name_with_day(self):
        question = "Show the labeling procedure effective on March 15, 2024."
        assert extract_as_of(question) == date(2024, 3, 15)

    def test_month_only_means_first_of_month(self):
        question = "What was the sterilization SOP as of March 2024?"
        assert extract_as_of(question) == date(2024, 3, 1)

    def test_no_as_of_phrase_returns_none(self):
        assert extract_as_of("What is the current revision of SOP-004?") is None

    def test_non_date_text_after_phrase_returns_none(self):
        assert extract_as_of("Were we compliant as of fiscal 2024?") is None


class TestExtractScope:
    def test_single_doc_key_becomes_scope(self):
        scope = extract_scope("What does SOP-004 require for effectiveness verification?")
        assert (scope.doc_key, scope.revision) == ("SOP-004", None)

    def test_compound_doc_key(self):
        scope = extract_scope("What does WI-MFG-014 say about torque?")
        assert (scope.doc_key, scope.revision) == ("WI-MFG-014", None)

    def test_doc_key_with_revision(self):
        scope = extract_scope("What did Rev A of SOP-004 require?")
        assert (scope.doc_key, scope.revision) == ("SOP-004", "A")

    def test_revision_word_variants(self):
        for phrasing in ("Revision B of QM-001", "QM-001 rev. B", "QM-001 revision B"):
            scope = extract_scope(phrasing)
            assert (scope.doc_key, scope.revision) == ("QM-001", "B"), phrasing

    def test_current_revision_phrasing_pins_nothing(self):
        # "current revision" and "revision history" are not exact-revision pins;
        # the token after the word is not a revision identifier.
        assert extract_scope("What is the current revision of SOP-004?").revision is None
        assert extract_scope("Walk me through the revision history of SOP-004.").revision is None

    def test_two_distinct_doc_keys_are_ambiguous(self):
        # A comparison names two documents; scoping to one would answer the wrong
        # question, so no hard doc_key scope is applied and retrieval stays broad.
        scope = extract_scope("How does SOP-004 differ from SOP-006?")
        assert (scope.doc_key, scope.revision) == (None, None)

    def test_repeated_same_doc_key_is_still_single_scope(self):
        scope = extract_scope("In SOP-004, what does SOP-004 require for verification?")
        assert scope.doc_key == "SOP-004"

    def test_no_doc_key_yields_no_scope(self):
        scope = extract_scope("What is the corrective action process?")
        assert (scope.doc_key, scope.revision) == (None, None)

    def test_revision_without_a_single_doc_key_is_dropped(self):
        # A bare revision cannot be pinned to a document; without exactly one
        # doc key there is nothing to scope it to.
        assert extract_scope("What changed in Rev B?").revision is None

    def test_review_is_not_a_revision(self):
        scope = extract_scope("Review SOP-004 for completeness.")
        assert (scope.doc_key, scope.revision) == ("SOP-004", None)


class TestRouteOverride:
    def test_req_id_routes_to_trace(self):
        question = "Which verification report(s) provide objective evidence for REQ-001?"
        assert route_override(question) == "trace"

    def test_unverified_requirements_routes_to_trace(self):
        question = (
            "Do all design input requirements have verification evidence in the "
            "traceability matrix? If not, which requirements lack it?"
        )
        assert route_override(question) == "trace"

    def test_training_with_doc_key_routes_to_trace(self):
        question = "Is Sarah Lindqvist trained to the current revision of SOP-001?"
        assert route_override(question) == "trace"

    def test_training_with_compound_doc_key_routes_to_trace(self):
        # The whole compound key must be seen, not just its MFG-014 tail.
        question = "Is the operator trained to the current revision of WI-MFG-014?"
        assert route_override(question) == "trace"

    def test_count_question_routes_to_aggregate(self):
        assert route_override("How many complaints were received in 2024?") == "aggregate"

    def test_are_any_overdue_routes_to_aggregate(self):
        question = "As of 2026-07-01, are any CAPA effectiveness checks overdue?"
        assert route_override(question) == "aggregate"

    def test_were_all_complaints_routes_to_aggregate(self):
        question = (
            "Were all complaints evaluated against the risk management file as "
            "SOP-006 requires? Identify any exception."
        )
        assert route_override(question) == "aggregate"

    def test_supplier_question_routes_to_aggregate(self):
        question = "Which supplier provides the Titanium Enclosure (HSG-100)?"
        assert route_override(question) == "aggregate"

    def test_record_id_routes_to_record(self):
        question = "What triggered CAPA-2024-001 and is its effectiveness check complete?"
        assert route_override(question) == "record"

    def test_capa_thread_walk_routes_to_trace(self):
        # A record id plus walk/thread phrasing is a graph thread walk.
        assert route_override("Walk me through CAPA-2025-014 end to end.") == "trace"

    def test_complaint_thread_walk_routes_to_trace(self):
        assert route_override("Trace the thread from complaint C-2025-0142.") == "trace"

    def test_complaint_id_routes_to_record(self):
        assert route_override("What was the investigation outcome for C-2025-0142?") == "record"

    def test_mdr_id_routes_to_record(self):
        question = "Which complaint led to MDR-0001, and when was the MDR submitted to FDA?"
        assert route_override(question) == "record"

    def test_maude_question_routes_to_external(self):
        question = "Compare our infusion pump complaints against MAUDE adverse events"
        assert route_override(question) == "external"

    def test_maude_count_phrasing_still_routes_external(self):
        assert (
            route_override("How many MAUDE reports mention infusion pump catheters?") == "external"
        )

    def test_rate_comparison_routes_to_compare(self):
        question = "How does our complaint rate for this device class compare to MAUDE?"
        assert route_override(question) == "compare"

    def test_raw_count_comparison_stays_external_not_compare(self):
        # No rate word — a count comparison, not a rate comparison — so the plain
        # external path (which still runs internal retrieval) is used.
        question = "Compare our infusion pump complaints against MAUDE adverse events"
        assert route_override(question) == "external"

    def test_cfr_citation_routes_to_external(self):
        assert route_override("What does 21 CFR 820.100 require for CAPA?") == "external"

    def test_plain_procedure_question_is_left_to_the_llm(self):
        assert route_override("What does SOP-004 require for effectiveness verification?") is None

    def test_revision_question_is_left_to_the_llm(self):
        question = "What is the current revision of QM-001 (Quality Manual)?"
        assert route_override(question) is None


class TestIsRateComparison:
    def test_needs_source_verb_and_rate_word_together(self):
        assert is_rate_comparison("How does our complaint rate compare to MAUDE?")
        assert is_rate_comparison("Benchmark our MDR frequency versus openFDA")

    def test_missing_any_signal_is_not_a_rate_comparison(self):
        assert not is_rate_comparison("Compare our complaints to MAUDE")  # no rate word
        assert not is_rate_comparison("What is our complaint rate this year?")  # no source
        assert not is_rate_comparison("Show MAUDE reports for infusion pumps")  # no comparison


class TestExternalPlan:
    def test_maude_comparison_distills_the_device_term(self):
        plan = external_plan("Compare our infusion pump complaints against MAUDE adverse events")
        assert plan.method == "maude"
        assert plan.term == "infusion pump"

    def test_quoted_phrase_wins_as_search_term(self):
        plan = external_plan('Search MAUDE for "catheter kink" events')
        assert plan.method == "maude"
        assert plan.term == "catheter kink"

    def test_recall_question_targets_the_recall_database(self):
        plan = external_plan("Are there any recent FDA recalls affecting infusion pumps?")
        assert plan.method == "recalls"
        assert plan.term == "infusion pumps"

    def test_cfr_citation_is_passed_verbatim_to_ecfr(self):
        plan = external_plan("What does 21 CFR 820.100 require for CAPA?")
        assert plan.method == "ecfr"
        assert plan.term == "21 CFR 820.100"

    def test_guidance_question(self):
        plan = external_plan("Is there FDA guidance on cybersecurity?")
        assert plan.method == "guidance"
        assert plan.term == "cybersecurity"

    def test_warning_letter_question_targets_compliance_actions(self):
        plan = external_plan("Have any warning letters been issued to Synthetic Devices Inc?")
        assert plan.method == "compliance"
        assert plan.term == "Synthetic Devices Inc"

    def test_literature_question_targets_pubmed(self):
        plan = external_plan("What does the published literature say about catheter occlusion?")
        assert plan.method == "pubmed"
        assert plan.term == "catheter occlusion"

    def test_clinical_trials_question(self):
        plan = external_plan("Are there clinical trials studying implantable infusion pumps?")
        assert plan.method == "clinicaltrials"
        assert "implantable infusion pumps" in plan.term

    def test_unmatched_source_falls_back_to_web_with_full_question(self):
        question = "Search the web for ISO 13485 transition timelines"
        plan = external_plan(question)
        assert plan.method == "web"
        assert plan.term == question


class TestWarehousePlan:
    def test_year_count_builds_bounded_sql(self):
        plan = warehouse_plan("How many complaints were received in 2024?")
        assert plan.saved is None
        assert plan.sql == (
            "SELECT count(*) AS total FROM registers.v_complaint_register"
            " WHERE received >= '2024-01-01' AND received < '2025-01-01'"
        )
        assert plan.title == "Count of complaints in 2024"
        # The generated SQL must itself pass the guard the tool applies.
        assert validate_select(plan.sql, allowed_relations=ALLOWED_RELATIONS)

    def test_ncr_count_uses_opened_column(self):
        plan = warehouse_plan("How many nonconformance reports were opened in 2025?")
        assert plan.sql is not None
        assert "registers.v_ncr_register" in plan.sql
        assert "opened >= '2025-01-01'" in plan.sql

    def test_count_without_year_is_unbounded(self):
        plan = warehouse_plan("How many CAPAs are there?")
        assert plan.sql == "SELECT count(*) AS total FROM registers.v_capa_register"

    def test_overdue_effectiveness_uses_saved_query(self):
        plan = warehouse_plan("As of 2026-07-01, are any CAPA effectiveness checks overdue?")
        assert plan.saved == "overdue_capa_effectiveness"

    def test_complaints_without_risk_evaluation(self):
        plan = warehouse_plan("Were all complaints evaluated against the risk management file?")
        assert plan.saved == "complaints_without_risk_evaluation"

    def test_supplier_question_uses_supplier_register(self):
        plan = warehouse_plan("Which supplier provides the Titanium Enclosure (HSG-100)?")
        assert plan.saved == "supplier_audit_aging"

    def test_training_for_document_carries_doc_key_param(self):
        plan = warehouse_plan("Show the training records for SOP-013.")
        assert plan.saved == "training_for_document"
        assert plan.params == {"doc_key": "SOP-013"}

    def test_unmatched_falls_back_to_register_counts(self):
        assert warehouse_plan("List everything you have.").saved == "register_counts"

    def test_open_qualifier_filters_the_count(self):
        plan = warehouse_plan("How many NCRs are currently open?")
        assert plan.sql == "SELECT count(*) AS total FROM registers.v_ncr_register WHERE is_open"
        assert plan.title == "Count of open NCRs"
        assert validate_select(plan.sql, allowed_relations=ALLOWED_RELATIONS)

    def test_open_and_age_qualifiers_both_applied(self):
        plan = warehouse_plan("How many NCRs have been open for more than 90 days?")
        assert plan.sql == (
            "SELECT count(*) AS total FROM registers.v_ncr_register WHERE is_open AND age_days > 90"
        )
        assert plan.title == "Count of open NCRs older than 90 days"
        assert validate_select(plan.sql, allowed_relations=ALLOWED_RELATIONS)

    def test_open_qualifier_combines_with_year(self):
        plan = warehouse_plan("How many complaints opened in 2024 are still open?")
        assert plan.sql == (
            "SELECT count(*) AS total FROM registers.v_complaint_register"
            " WHERE is_open AND received >= '2024-01-01' AND received < '2025-01-01'"
        )

    def test_closed_qualifier_negates_open(self):
        plan = warehouse_plan("How many CAPAs are closed?")
        assert (
            plan.sql == "SELECT count(*) AS total FROM registers.v_capa_register WHERE NOT is_open"
        )

    def test_status_qualifier_on_mdr_refuses(self):
        # The MDR register has no is_open/age_days column; a filtered count is
        # not expressible, so the plan refuses rather than answer a bare total.
        plan = warehouse_plan("How many MDRs are still open?")
        assert plan.sql is None
        assert plan.saved is None

    def test_age_qualifier_on_mdr_refuses(self):
        plan = warehouse_plan("How many MDRs are older than 90 days?")
        assert plan.sql is None
        assert plan.saved is None


class TestGraphPlan:
    def test_req_id_traces_the_requirement(self):
        plan = graph_plan("Which verification report(s) cover REQ-017?")
        assert plan.method == "requirement_trace"
        assert plan.argument == "REQ-017"

    def test_training_targets_the_document(self):
        plan = graph_plan("Is Elena Vasquez trained to the current revision of SOP-001?")
        assert plan.method == "training_status"
        assert plan.argument == "SOP-001"

    def test_training_targets_a_compound_document_key(self):
        plan = graph_plan("Is the operator trained to the current revision of WI-MFG-014?")
        assert plan.method == "training_status"
        assert plan.argument == "WI-MFG-014"

    def test_unverified_requirements(self):
        plan = graph_plan("Do all requirements have verification evidence? Which lack it?")
        assert plan.method == "unverified_requirements"
        assert plan.argument is None

    def test_doc_key_falls_back_to_document_profile(self):
        plan = graph_plan("Walk me through everything connected to DFMEA-100.")
        assert plan.method == "document_profile"
        assert plan.argument == "DFMEA-100"

    def test_no_anchor_falls_back_to_unverified(self):
        assert graph_plan("Trace the design requirements.").method == "unverified_requirements"

    def test_record_thread_parses_full_capa_id(self):
        # The whole CAPA-2025-014 id anchors the walk, not a 3-digit tail.
        plan = graph_plan("Walk me through CAPA-2025-014 end to end.")
        assert plan.method == "record_thread"
        assert plan.argument == "CAPA-2025-014"

    def test_record_thread_parses_full_complaint_id(self):
        plan = graph_plan("Trace the thread from complaint C-2025-0142.")
        assert plan.method == "record_thread"
        assert plan.argument == "C-2025-0142"
