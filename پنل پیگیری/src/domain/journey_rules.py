"""Journey state machine (docs/05 §2, §3). Pure: takes a snapshot, returns changes.

The engine service loads a journey and its steps, asks these functions what
must change for a given ``today``, and writes the changes in one transaction.
Re-running with the same input yields no further changes (idempotent).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

OPEN = frozenset({"awaiting_identity", "active", "needs_review"})
RECALL_PURPOSES = frozenset({"missed", "no_show"})
AWAITING_IDENTITY_DAYS = 30          # G10
OVERDUE_FAIL_DAYS = 30               # G6


@dataclass
class Step:
    id: int
    seq: int
    kind: str                         # call | expect
    due_date: date
    window_end: date | None
    category: str | None
    purpose: str
    status: str                       # pending | done | skipped | missed | cancelled
    attempts: int = 0
    accept_early: bool = False
    recall_on_miss: bool = False
    completes: bool = False


@dataclass
class Journey:
    id: int
    status: str
    start_date: date
    created_on: date


@dataclass
class NewCall:
    purpose: str
    due_date: date
    category: str | None = None       # what was missed (for the call text)


@dataclass
class Changes:
    step_status: dict[int, str] = field(default_factory=dict)
    new_calls: list[NewCall] = field(default_factory=list)
    journey_status: str | None = None
    close_reason: str | None = None

    @property
    def empty(self) -> bool:
        return not (self.step_status or self.new_calls or self.journey_status)


def _effective(steps: list[Step], ch: Changes) -> list[Step]:
    return [Step(**{**s.__dict__, "status": ch.step_status.get(s.id, s.status)}) for s in steps]


def close(steps: list[Step], ch: Changes, status: str, reason: str | None) -> Changes:
    """Close the journey; every still-pending step becomes cancelled (or skipped on success)."""
    pending_to = "skipped" if status in ("succeeded", "partial") else "cancelled"
    for s in _effective(steps, ch):
        if s.status == "pending":
            ch.step_status[s.id] = pending_to
    ch.new_calls.clear()
    ch.journey_status, ch.close_reason = status, reason
    return ch


def evaluate_completion(steps: list[Step], ch: Changes | None = None) -> Changes:
    """G8 + wound care: decide whether an active journey is finished."""
    ch = ch or Changes()
    eff = _effective(steps, ch)
    expects = [s for s in eff if s.kind == "expect"]
    if any(s.completes and s.status == "done" for s in expects):
        return close(steps, ch, "partial" if any(s.status == "missed" for s in expects) else "succeeded", None)
    if any(s.status == "pending" for s in expects):
        return ch
    if any(s.kind == "call" and s.status == "pending" and s.purpose in RECALL_PURPOSES for s in eff) \
            or any(c.purpose in RECALL_PURPOSES for c in ch.new_calls):
        return ch                     # a recall can still bring the patient back
    done = [s for s in expects if s.status == "done"]
    missed = [s for s in expects if s.status == "missed"]
    last = max(expects, key=lambda s: (s.due_date, s.seq))
    if last.status == "done":
        return close(steps, ch, "partial" if missed else "succeeded", None)
    if done:
        return close(steps, ch, "partial", None)
    return close(steps, ch, "failed", "expired")


def tick(j: Journey, steps: list[Step], today: date) -> Changes:
    """Time-driven transitions for one journey (G6, G7, G10, G8)."""
    ch = Changes()
    if j.status == "awaiting_identity":
        if today - j.created_on >= timedelta(days=AWAITING_IDENTITY_DAYS):
            close(steps, ch, "cancelled", "expired")
        return ch
    if j.status != "active":
        return ch

    for s in steps:                                                    # G7
        if s.kind == "expect" and s.status == "pending" and s.window_end is not None and s.window_end < today:
            ch.step_status[s.id] = "missed"
            if s.recall_on_miss:
                ch.new_calls.append(NewCall("missed", s.window_end + timedelta(days=1), s.category))

    oldest_call = min((s.due_date for s in steps if s.kind == "call" and s.status == "pending"), default=None)
    if oldest_call is not None and (today - oldest_call).days > OVERDUE_FAIL_DAYS:     # G6
        return close(steps, ch, "failed", "expired")
    return evaluate_completion(steps, ch)


def calls_to_skip_after_return(steps: list[Step]) -> list[int]:
    """M6: once a return is recorded, earlier pending calls of the journey are pointless."""
    return [s.id for s in steps if s.kind == "call" and s.status == "pending"]
