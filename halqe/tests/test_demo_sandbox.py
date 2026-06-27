"""
tests/test_demo_sandbox.py — Step 57 (cluster N): Demo Sandbox orchestration guard.

WHAT THIS TESTS
───────────────
demo_sandbox is an ORCHESTRATOR: it must chain the five existing, already-tested
seed/generate commands in the correct order, with the correct tenant_id, and it
must set the tenant GUC around the GUC-less seed_clinical_rules INSERT (RLS,
slice5 — without the GUC every INSERT is rejected by tenant_isolation WITH CHECK).

We assert the ORCHESTRATION contract here (mocking call_command) rather than
re-running the full end-to-end seed against the shared halqe_app_test DB — a full
run would inject 4 demo patients + 76 rules into the shared test DB and pollute
sibling tests' counts. The real end-to-end run is proven separately on a
THROWAWAY DB (see the step-57 deliverable: patients=4, followups=41, pending
approvals=9, idempotent across two runs).

Guards:
  D1. All five sub-commands are called, in the right order, each with tenant_id.
  D2. seed_clinical_rules runs while the tenant GUC is set (RLS-safe).
  D3. --tenant-id and --admin-password are threaded through to the sub-commands.
  D4. The command does NOT send SMS (it never calls send_approved_sms / a provider).
"""
from __future__ import annotations

import io
import unittest.mock as mock

import pytest

from django.core.management import call_command


# Order of sub-commands demo_sandbox must invoke.
_EXPECTED_ORDER = [
    "seed_clinical_rules",
    "seed_engagement_events",
    "seed_demo",
    "generate_followups",
    "run_engagement",
]


def _run_with_mocked_subcommands(**extra_opts):
    """
    Run demo_sandbox with call_command (the dispatcher) patched so NO real
    sub-command executes. Returns the ordered list of (command_name, kwargs)
    captured, plus a record of whether the tenant GUC was set during
    seed_clinical_rules.

    We patch call_command INSIDE the demo_sandbox module namespace so only the
    orchestrator's calls are intercepted — the outer call_command that launches
    demo_sandbox itself is the real one.
    """
    calls: list[tuple[str, dict]] = []
    guc_state_at_rules: dict[str, object] = {}

    real_set = None
    real_clear = None

    from platform_core import tenant_context

    def _fake_call_command(name, *args, **kwargs):
        # When seed_clinical_rules is dispatched, capture the live GUC value so we
        # can prove demo_sandbox set it (RLS guard) before the GUC-less seed runs.
        if name == "seed_clinical_rules":
            from django.db import connection
            with connection.cursor() as cur:
                cur.execute("SELECT current_setting('app.current_tenant', true)")
                guc_state_at_rules["value"] = cur.fetchone()[0]
        calls.append((name, kwargs))
        # Return nothing — the orchestrator ignores sub-command return values.
        return None

    out = io.StringIO()
    with mock.patch(
        "clinical.management.commands.demo_sandbox.call_command",
        side_effect=_fake_call_command,
    ):
        call_command("demo_sandbox", stdout=out, **extra_opts)

    return calls, guc_state_at_rules, out.getvalue()


@pytest.mark.django_db(transaction=True)
def test_demo_sandbox_chains_all_subcommands_in_order():
    """D1: all five sub-commands fire, in the documented order."""
    calls, _guc, _out = _run_with_mocked_subcommands()
    names = [c[0] for c in calls]
    assert names == _EXPECTED_ORDER, (
        f"demo_sandbox must chain {_EXPECTED_ORDER} in order; got {names}"
    )


@pytest.mark.django_db(transaction=True)
def test_demo_sandbox_sets_tenant_guc_for_rule_seed():
    """
    D2: seed_clinical_rules is GUC-less and runs against FORCE-RLS tables.
    demo_sandbox MUST set app.current_tenant before dispatching it, else every
    INSERT is rejected by the tenant_isolation WITH CHECK policy.
    """
    calls, guc, _out = _run_with_mocked_subcommands(tenant_id=1)
    assert guc.get("value") == "1", (
        "Tenant GUC must be set to '1' while seed_clinical_rules runs "
        f"(RLS guard); observed: {guc.get('value')!r}"
    )


@pytest.mark.django_db(transaction=True)
def test_demo_sandbox_threads_tenant_and_password():
    """D3: --tenant-id and --admin-password reach the relevant sub-commands."""
    calls, _guc, _out = _run_with_mocked_subcommands(
        tenant_id=1, admin_password="demo_pw"
    )
    by_name = {name: kwargs for name, kwargs in calls}

    # tenant_id threaded to every sub-command
    for name in _EXPECTED_ORDER:
        assert by_name[name].get("tenant_id") == 1, (
            f"{name} must receive tenant_id=1; got {by_name[name].get('tenant_id')!r}"
        )

    # admin_password threaded specifically to seed_demo
    assert by_name["seed_demo"].get("admin_password") == "demo_pw", (
        "admin_password must be forwarded to seed_demo"
    )


@pytest.mark.django_db(transaction=True)
def test_demo_sandbox_sends_no_sms():
    """
    D4: demo_sandbox must NEVER send a real SMS. It only ENQUEUES approvals via
    run_engagement (which itself only enqueues). Prove the orchestrator does not
    import/call the send path.
    """
    with mock.patch(
        "clinical.engagement_service.send_approved_sms"
    ) as send_spy:
        calls, _guc, _out = _run_with_mocked_subcommands()
        assert send_spy.call_count == 0, (
            "demo_sandbox must not send SMS; send_approved_sms was called "
            f"{send_spy.call_count} time(s)"
        )
    # And the summary advertises the no-SMS guarantee.
    _calls2, _guc2, out = _run_with_mocked_subcommands()
    assert "No real SMS" in out or "no SMS" in out.lower()
