from __future__ import annotations

from test_encounter_plan_commitments_a10 import (
    a10_app,
    _commitment,
    _context,
    _sign,
)


def test_plan_completion_route_records_real_evidence_and_is_idempotent(a10_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.encounter_plan_commitment_repo import (
        EncounterPlanCommitmentRepository,
    )
    from src.services.followup_contact_service import FollowupContactService
    from src.services.followup_orchestration.backfill import (
        FollowupEpisodeBackfillService,
    )
    from src.services.followup_orchestration.projection_service import (
        FollowupProjectionService,
    )

    app = a10_app
    app.config.update(
        FOLLOWUP_UNIFIED_WORKLIST_READONLY=True,
        FOLLOWUP_UNIFIED_WORKLIST_ACTIONS=True,
        FOLLOWUP_AUTO_ROUTING=True,
        FOLLOWUP_STRUCTURED_CONTACT=True,
    )
    ctx = _context(invoice_id=7991)
    _sign(
        ctx,
        commitments=[_commitment(ctx, key="work-center-plan-client-0001")],
        key="work-center-plan-sign-0001",
    )
    db = get_db()
    current = EncounterPlanCommitmentRepository(db).list_current()[0]
    contact = FollowupContactService().record(
        task_id=int(current["id"]),
        channel="PHONE",
        outcome="REACHED",
        actor_username="admin",
        actor_user_id=ctx["actor_user_id"],
        idempotency_key="work-center-plan-contact-0001",
        note="اقدام با بیمار تأیید شد",
    )
    FollowupEpisodeBackfillService(db).run(apply=True)
    FollowupProjectionService(db).run(
        as_of_at=ctx["now"].strftime("%Y-%m-%d %H:%M:%S"),
        apply=True,
    )
    episode = db.execute(
        """SELECT episode_id FROM followup_episode_links
           WHERE source_type='ENCOUNTER_COMMITMENT'
             AND source_id=? ORDER BY id LIMIT 1""",
        (str(current["commitment_id"]),),
    ).fetchone()
    assert episode
    episode_id = str(episode["episode_id"])

    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = int(ctx["actor_user_id"])
    payload = {
        "current_url": f"/followups/unified/{episode_id}?view=all",
        "return_url": "/followups/unified/?view=all",
        "next_url": "",
        "idempotency_key": "work-center-plan-complete-0001",
        "evidence_type": "CONTACT_EVENT",
        "evidence_ref": str(contact["id"]),
        "outcome_code": "COMPLETED_AS_PLANNED",
        "note": "اقدام برنامه درمان تکمیل شد",
    }
    first = client.post(
        f"/followups/work-center-outcomes/{episode_id}/plan-complete",
        data=payload,
        follow_redirects=False,
    )
    second = client.post(
        f"/followups/work-center-outcomes/{episode_id}/plan-complete",
        data=payload,
        follow_redirects=False,
    )

    assert first.status_code in {302, 303}
    assert second.status_code in {302, 303}
    head = EncounterPlanCommitmentRepository(db).current_for_task(int(current["id"]))
    assert head["current_status"] == "COMPLETED"
    assert head["current_evidence_type"] == "CONTACT_EVENT"
    assert head["current_evidence_ref"] == str(contact["id"])
    assert db.execute(
        """SELECT COUNT(*) FROM care_plan_commitment_events
           WHERE commitment_id=? AND event_type='COMPLETED'""",
        (str(current["commitment_id"]),),
    ).fetchone()[0] == 1
    projection = db.execute(
        """SELECT state_class FROM followup_work_item_projection
           WHERE episode_id=?""",
        (episode_id,),
    ).fetchone()
    assert projection["state_class"] == "TERMINAL"
