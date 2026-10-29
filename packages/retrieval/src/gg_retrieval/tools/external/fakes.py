"""Synthetic offline payloads for the external tools.

Used when GG_EXTERNAL_OFFLINE is set (CI, air-gapped dev). Every record is
plainly synthetic — SYNTH- prefixes throughout — so offline answers can
never be mistaken for real regulatory data.
"""

from typing import Any

from gg_retrieval.tools.external.fetch import FakeFetcher

_MAUDE: dict[str, Any] = {
    # meta.results.total is the full match count behind the query; the results
    # array is one capped page (two synthetic rows here). The comparison path
    # reads the total, never len(results).
    "meta": {"results": {"skip": 0, "limit": 2, "total": 128}},
    "results": [
        {
            "report_number": "SYNTH-MAUDE-0001",
            "date_received": "20250315",
            "event_type": "Malfunction",
            "device": [{"brand_name": "SYNTH Infusion Pump 20", "generic_name": "infusion pump"}],
            "mdr_text": [
                {"text": "Synthetic offline record: telemetry dropout reported at follow-up."}
            ],
        },
        {
            "report_number": "SYNTH-MAUDE-0002",
            "date_received": "20250602",
            "event_type": "Injury",
            "device": [{"brand_name": "SYNTH Infusion Pump 40", "generic_name": "infusion pump"}],
            "mdr_text": [{"text": "Synthetic offline record: pocket revision after migration."}],
        },
    ],
}

_ENFORCEMENT: dict[str, Any] = {
    "results": [
        {
            "recall_number": "SYNTH-Z-0001-2025",
            "classification": "Class II",
            "status": "Ongoing",
            "recall_initiation_date": "20250120",
            "recalling_firm": "Synthetic Devices Inc",
            "reason_for_recall": "Synthetic offline record: firmware update mislabeled.",
        }
    ]
}

_510K: dict[str, Any] = {
    "results": [
        {
            "k_number": "SYNTH-K250001",
            "device_name": "Synthetic Implantable Infusion Pump",
            "applicant": "Synthetic Devices Inc",
            "decision_date": "2025-02-14",
            "decision_description": "Substantially Equivalent",
        }
    ]
}

_PMA: dict[str, Any] = {
    "results": [
        {
            "pma_number": "SYNTH-P250001",
            "supplement_number": "S001",
            "trade_name": "Synthetic Infusion Pump System",
            "applicant": "Synthetic Devices Inc",
            "decision_date": "2025-03-30",
        }
    ]
}

_UDI: dict[str, Any] = {
    "results": [
        {
            "identifiers": [{"id": "SYNTH-00810000000001"}],
            "brand_name": "Synthetic Infusion Pump",
            "version_or_model_number": "SYN-100",
            "company_name": "Synthetic Devices Inc",
            "device_description": "Synthetic offline record: 20 mL implantable infusion pump.",
        }
    ]
}

_COMPLIANCE: dict[str, Any] = {
    "result": [
        {
            "LegalName": "Synthetic Devices Inc",
            "ActionType": "Warning Letter",
            "ActionTakenDate": "2024-11-05",
            "State": "MN",
            "CaseInjunctionID": "SYNTH-WL-0001",
        }
    ]
}

_ECFR: dict[str, Any] = {
    "results": [
        {
            "hierarchy": {"title": "21", "part": "820", "section": "820.100"},
            "headings": {
                "part": "Quality System Regulation",
                "section": "Corrective and preventive action.",
            },
            "full_text_excerpt": (
                "Synthetic offline record: each manufacturer shall establish "
                "procedures for implementing corrective and preventive action."
            ),
            "starts_on": "2025-01-01",
        }
    ]
}

_GUIDANCE: dict[str, Any] = {
    "data": [
        {
            "title": '<a href="/synthetic">SYNTH Guidance: Cybersecurity in Medical Devices</a>',
            "field_issue_datetime": "2025-04-01",
            "field_center": "Center for Devices and Radiological Health",
            "field_docket_number": "SYNTH-D-0001",
        },
        {
            "title": "SYNTH Guidance: Design Considerations for Pivotal Clinical Studies",
            "field_issue_datetime": "2024-08-15",
            "field_center": "Center for Devices and Radiological Health",
            "field_docket_number": "SYNTH-D-0002",
        },
    ]
}

_CLINICALTRIALS: dict[str, Any] = {
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "SYNTH-NCT90000001",
                    "briefTitle": "Synthetic Study of Implantable Infusion Pump Longevity",
                },
                "statusModule": {"overallStatus": "COMPLETED"},
                "designModule": {"studyType": "INTERVENTIONAL"},
                "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Synthetic Devices Inc"}},
            }
        }
    ]
}

_ESEARCH: dict[str, Any] = {"esearchresult": {"idlist": ["90000001", "90000002"]}}

_ESUMMARY: dict[str, Any] = {
    "result": {
        "uids": ["90000001", "90000002"],
        "90000001": {
            "title": "Synthetic offline record: long-term outcomes of intrathecal infusion.",
            "source": "Synth J Infus Ther",
            "pubdate": "2025 Mar",
            "authors": [{"name": "Synthson A"}],
        },
        "90000002": {
            "title": "Synthetic offline record: catheter occlusion surveillance methods.",
            "source": "Synth Med Device Rev",
            "pubdate": "2024 Nov",
            "authors": [{"name": "Fakerton B"}],
        },
    }
}

_TAVILY: dict[str, Any] = {
    "results": [
        {
            "title": "Synthetic offline web result",
            "url": "https://example.invalid/synthetic-web-result",
            "content": "Synthetic offline record: canned web search payload.",
        }
    ]
}


def offline_fetcher() -> FakeFetcher:
    return FakeFetcher(
        (
            ("/device/event.json", _MAUDE),
            ("/device/enforcement.json", _ENFORCEMENT),
            ("/device/510k.json", _510K),
            ("/device/pma.json", _PMA),
            ("/device/udi.json", _UDI),
            ("compliance_actions", _COMPLIANCE),
            ("ecfr.gov/api/search", _ECFR),
            ("search-for-guidance.json", _GUIDANCE),
            ("clinicaltrials.gov/api/v2/studies", _CLINICALTRIALS),
            ("esearch.fcgi", _ESEARCH),
            ("esummary.fcgi", _ESUMMARY),
            ("api.tavily.com", _TAVILY),
        )
    )
