"""
Threshold-sync guard — Step 40 (cluster I).

CLAUDE.md threshold-sync rule: clinical_indicators is the LIVE source of truth
for thresholds; rule_engine._FALLBACK_THRESHOLDS is only a last-resort fallback
used when a clinical_indicators row is missing for a key. The two MUST stay
consistent — if the seed changes but the fallback doesn't (or vice versa), a
patient could be evaluated against a stale threshold via the fallback path.

This test locks that consistency: every key in _FALLBACK_THRESHOLDS must match
its clinical_indicators seed row (warn / danger / direction). It is a pure
code-consistency guard — it does NOT assert any particular clinical value, so it
never needs a physician sign-off; it only prevents silent drift between the two.

(Guideline-currency of the seed values themselves — audited against ADA 2026 /
KDIGO 2024 / ACC-AHA in docs/threshold_audit.md — is owner-gated and tracked
separately; this guard is orthogonal to it.)
"""
import pytest

from clinical.rule_engine import _FALLBACK_THRESHOLDS
from clinical.models import ClinicalIndicator


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_fallback_thresholds_match_clinical_indicators_seed():
    """
    For every key in _FALLBACK_THRESHOLDS, the warn / danger / direction must
    match the live clinical_indicators row (tenant 1). Guards threshold-sync.
    """
    assert _FALLBACK_THRESHOLDS, "_FALLBACK_THRESHOLDS must not be empty"

    for key, fb in _FALLBACK_THRESHOLDS.items():
        ind = ClinicalIndicator.objects.filter(tenant_id=1, key=key).first()
        assert ind is not None, (
            f"_FALLBACK_THRESHOLDS references key '{key}' but clinical_indicators "
            f"has no such row — the fallback points at a non-existent indicator."
        )
        assert ind.warn is not None and float(ind.warn) == float(fb["warn"]), (
            f"threshold-sync drift on '{key}'.warn: "
            f"fallback={fb['warn']} vs clinical_indicators seed={ind.warn}. "
            f"Update both (and docs) together — see CLAUDE.md threshold-sync rule."
        )
        assert ind.danger is not None and float(ind.danger) == float(fb["danger"]), (
            f"threshold-sync drift on '{key}'.danger: "
            f"fallback={fb['danger']} vs clinical_indicators seed={ind.danger}. "
            f"Update both (and docs) together — see CLAUDE.md threshold-sync rule."
        )
        seed_direction = (ind.direction or "high")
        assert seed_direction == fb["direction"], (
            f"threshold-sync drift on '{key}'.direction: "
            f"fallback={fb['direction']} vs clinical_indicators seed={seed_direction}."
        )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_fallback_keys_are_a_subset_of_seeded_indicators():
    """
    Every fallback key must exist as a seeded indicator (no orphan fallbacks).
    This catches a fallback added for a key that was never seeded.
    """
    seeded_keys = set(
        ClinicalIndicator.objects.filter(tenant_id=1).values_list("key", flat=True)
    )
    fallback_keys = set(_FALLBACK_THRESHOLDS.keys())
    orphans = fallback_keys - seeded_keys
    assert not orphans, (
        f"_FALLBACK_THRESHOLDS has keys with no clinical_indicators seed row: {orphans}"
    )
