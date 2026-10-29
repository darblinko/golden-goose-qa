"""License policy logic of the audit script (the environment scan runs in CI)."""

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "license_audit.py"
_spec = importlib.util.spec_from_file_location("license_audit", _SCRIPT)
assert _spec is not None and _spec.loader is not None
license_audit = importlib.util.module_from_spec(_spec)
sys.modules["license_audit"] = license_audit
_spec.loader.exec_module(license_audit)


def test_permissive_licenses_are_allowed():
    for text in ("MIT", "BSD-3-Clause", "Apache-2.0", "ISC License", "MIT License; BSD License"):
        assert license_audit.is_allowed(text), text
        assert not license_audit.is_forbidden(text), text
        assert license_audit.is_acceptable(text), text


def test_weak_copyleft_is_allowed():
    for text in ("MPL-2.0", "LGPL-3.0-or-later", "GNU Lesser General Public License v2"):
        assert license_audit.is_allowed(text), text
        assert not license_audit.is_forbidden(text), text
        assert license_audit.is_acceptable(text), text


def test_strong_copyleft_is_forbidden():
    for text in ("GPL-3.0-only", "GNU General Public License v2 (GPLv2)", "AGPL-3.0"):
        assert license_audit.is_forbidden(text) or not license_audit.is_allowed(text), text
        assert not license_audit.is_acceptable(text), text


def test_missing_metadata_is_not_allowed():
    assert not license_audit.is_allowed("")
    assert not license_audit.is_acceptable("")


def test_and_expression_requires_every_term_allowed():
    # The core substring bug: an allowed token must not mask a forbidden one.
    assert not license_audit.is_acceptable("LGPL-3.0-only AND GPL-3.0-only")
    assert not license_audit.is_acceptable("MIT AND Proprietary")
    assert not license_audit.is_acceptable("MIT AND GPL-3.0-only")
    # Every AND term allowed -> acceptable.
    assert license_audit.is_acceptable("Apache-2.0 AND LGPL-3.0-or-later AND MIT")


def test_or_expression_needs_one_allowed_term():
    # OR is a choice: an allowed branch carries the expression.
    assert license_audit.is_acceptable("MIT OR GPL-3.0-only")
    assert license_audit.is_acceptable("GPL-3.0-only OR MIT")
    # No acceptable branch -> forbidden.
    assert not license_audit.is_acceptable("GPL-3.0-only OR Proprietary")


def test_parentheses_and_unknown_terms_fail_closed():
    assert license_audit.is_acceptable("(MIT OR GPL-3.0-only) AND Apache-2.0")
    assert not license_audit.is_acceptable("(GPL-3.0-only OR AGPL-3.0) AND MIT")
    assert not license_audit.is_acceptable("Frobnicate-1.0")  # unknown -> fail closed
    assert not license_audit.is_acceptable("MIT AND (")  # malformed -> fail closed


def test_cc_by_permissive_data_license_allowed():
    assert license_audit.is_acceptable("CC-BY-4.0")
    assert not license_audit.is_acceptable("CC-BY-SA-4.0")  # share-alike is not on the list


def test_npm_license_field_shapes():
    assert license_audit._npm_license({"license": "MIT"}) == "MIT"
    assert license_audit._npm_license({"license": {"type": "MIT"}}) == "MIT"
    assert license_audit._npm_license({"licenses": [{"type": "MIT"}, {"type": "Apache-2.0"}]}) == (
        "MIT OR Apache-2.0"
    )
    assert license_audit._npm_license({}) == ""


def test_audit_npm_flags_forbidden_and_missing(tmp_path):
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(
        """
        {"packages": {
            "": {"name": "root"},
            "node_modules/good": {"license": "MIT"},
            "node_modules/copyleft": {"license": "GPL-3.0-only"},
            "node_modules/masked": {"license": "MIT AND GPL-3.0-only"},
            "node_modules/nometa": {"version": "1.0.0"}
        }}
        """
    )
    violations = dict(license_audit.audit_npm(lockfile))
    assert "good" not in violations
    assert violations["copyleft"] == "GPL-3.0-only"
    assert violations["masked"] == "MIT AND GPL-3.0-only"
    assert violations["nometa"] == "no license metadata"


def test_environment_audit_passes_here():
    # The project's own environment must satisfy its own policy; a dependency
    # bump that breaks this belongs in review, not in a nightly surprise.
    assert license_audit.audit_environment() == []


def test_real_npm_lockfile_passes():
    # The shipped web lockfile must satisfy the policy under real SPDX parsing.
    assert license_audit.audit_npm(_ROOT / "apps" / "web" / "package-lock.json") == []
