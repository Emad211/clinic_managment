"""FO-4 append-only ownership, routing and claim orchestration.

This service never mutates an operational follow-up source or clinical state.  The
current owner is derived from the Episode event stream and can therefore be rebuilt
independently from the disposable FO-2 projection cache.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import sqlite3
from typing import Iterable

from src.adapters.sqlite.followup_episode_repo import FollowupEpisodeRepository
from src.security.permissions import Permission, resolved_permissions
from src.services.followup_orchestration.identity import canonical_json


OWNERSHIP_EVENT_TYPES = ("ROUTED", "CLAIMED", "ASSIGNED")
ROLE_LABELS = {
    "RECEPTION": "پذیرش",
    "NURSING": "پرستاری",
    "PHYSICIAN": "پزشک",
    "MANAGER": "مدیر عملیات",
}
ROLE_PERMISSIONS = {
    "RECEPTION": Permission.FOLLOWUP_ADMIN_MANAGE,
    "NURSING": Permission.FOLLOWUP_CONTACT_RECORD,
    "PHYSICIAN": Permission.CLINICAL_TASK_TRANSITION,
    "MANAGER": Permission.SECURITY_GRANT_MANAGE,
}


class FollowupOwnershipError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class OwnershipState:
    episode_id: str
    owner_role: str | None
    owner_user_id: int | None
    owner_name: str | None
    ownership_event_id: int | None
    ownership_event_type: str | None

    @property
    def expected_event_id(self) -> int:
        return int(self.ownership_event_id or 0)

    @property
    def assigned(self) -> bool:
        return self.owner_user_id is not None

    def as_dict(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "owner_role": self.owner_role,
            "owner_role_label": ROLE_LABELS.get(
                str(self.owner_role or ""), "صف مشخص نشده"
            ),
            "owner_user_id": self.owner_user_id,
            "owner_name": self.owner_name,
            "ownership_event_id": self.ownership_event_id,
            "expected_event_id": self.expected_event_id,
            "ownership_event_type": self.ownership_event_type,
            "assigned": self.assigned,
        }


def _payload(row: sqlite3.Row | dict) -> dict:
    try:
        value = json.loads(str(row["payload_json"] or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _normalize_role(value: object) -> str:
    role = str(value or "").strip().upper()
    if role not in ROLE_LABELS:
        raise FollowupOwnershipError(
            "INVALID_OWNER_ROLE", "صف مسئول انتخاب‌شده معتبر نیست."
        )
    return role


def _normalize_expected(value: object) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise FollowupOwnershipError(
            "INVALID_EXPECTED_EVENT", "نسخهٔ فرم معتبر نیست؛ صفحه را تازه کنید."
        ) from exc
    return max(parsed, 0)


class FollowupOwnershipService:
    """Serialize FO-4 ownership mutations through the Episode event stream."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.row_factory = sqlite3.Row

    def _projection(self, episode_id: str) -> sqlite3.Row:
        row = self.db.execute(
            """SELECT episode_id, state_class, owner_role_proposal
               FROM followup_work_item_projection WHERE episode_id=?""",
            (str(episode_id),),
        ).fetchone()
        if not row:
            raise FollowupOwnershipError(
                "OWNERSHIP_PROJECTION_UNAVAILABLE",
                "این مسیر در نمای جاری موجود نیست؛ ابتدا نمای یکپارچه را بازسازی کنید.",
            )
        return row

    def _user(self, user_id: int) -> sqlite3.Row:
        row = self.db.execute(
            """SELECT id, username, full_name, role, is_active
               FROM users WHERE id=?""",
            (int(user_id),),
        ).fetchone()
        if not row or int(row["is_active"] or 0) != 1:
            raise FollowupOwnershipError(
                "OWNER_USER_UNAVAILABLE", "کاربر انتخاب‌شده فعال یا در دسترس نیست."
            )
        return row

    @staticmethod
    def _user_label(user: sqlite3.Row | dict | None) -> str | None:
        if not user:
            return None
        return str(user["full_name"] or user["username"] or "").strip() or None

    def state(self, episode_id: str) -> OwnershipState:
        states = self.states([str(episode_id)])
        try:
            return states[str(episode_id)]
        except KeyError as exc:
            raise FollowupOwnershipError(
                "OWNERSHIP_PROJECTION_UNAVAILABLE",
                "این مسیر در نمای جاری موجود نیست؛ ابتدا نمای یکپارچه را بازسازی کنید.",
            ) from exc

    def states(self, episode_ids: Iterable[str]) -> dict[str, OwnershipState]:
        ids = list(dict.fromkeys(str(value) for value in episode_ids if str(value)))
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        projections = self.db.execute(
            f"""SELECT episode_id, owner_role_proposal
                FROM followup_work_item_projection
                WHERE episode_id IN ({placeholders})""",
            ids,
        ).fetchall()
        role_by_episode = {
            str(row["episode_id"]): (
                str(row["owner_role_proposal"] or "").strip() or None
            )
            for row in projections
        }
        missing = [episode_id for episode_id in ids if episode_id not in role_by_episode]
        if missing:
            raise FollowupOwnershipError(
                "OWNERSHIP_PROJECTION_UNAVAILABLE",
                "یکی از مسیرها در نمای جاری موجود نیست؛ ابتدا نمای یکپارچه را بازسازی کنید.",
            )

        working = {
            episode_id: {
                "owner_role": role_by_episode[episode_id],
                "owner_user_id": None,
                "event_id": None,
                "event_type": None,
            }
            for episode_id in ids
        }
        events = self.db.execute(
            f"""SELECT episode_id, id, event_type, payload_json
                FROM followup_episode_events
                WHERE episode_id IN ({placeholders})
                  AND event_type IN ('ROUTED','CLAIMED','ASSIGNED')
                ORDER BY episode_id, id""",
            ids,
        ).fetchall()
        for row in events:
            episode_id = str(row["episode_id"])
            current = working[episode_id]
            data = _payload(row)
            kind = str(row["event_type"])
            if data.get("owner_role") in ROLE_LABELS:
                current["owner_role"] = str(data["owner_role"])
            if kind == "ROUTED":
                current["owner_user_id"] = None
            elif kind in {"CLAIMED", "ASSIGNED"}:
                action = str(data.get("action") or "").upper()
                raw_user = data.get("owner_user_id")
                current["owner_user_id"] = (
                    int(raw_user)
                    if raw_user not in (None, "") and action != "RELEASE"
                    else None
                )
            current["event_id"] = int(row["id"])
            current["event_type"] = kind

        user_ids = sorted(
            {
                int(current["owner_user_id"])
                for current in working.values()
                if current["owner_user_id"] is not None
            }
        )
        users = {}
        if user_ids:
            user_placeholders = ",".join("?" for _ in user_ids)
            users = {
                int(row["id"]): row
                for row in self.db.execute(
                    f"""SELECT id, username, full_name, role, is_active
                        FROM users WHERE id IN ({user_placeholders})""",
                    user_ids,
                ).fetchall()
            }

        result: dict[str, OwnershipState] = {}
        for episode_id, current in working.items():
            owner_user_id = current["owner_user_id"]
            user = users.get(int(owner_user_id)) if owner_user_id is not None else None
            owner_name = self._user_label(user)
            if owner_user_id is not None and not owner_name:
                owner_name = "کاربر غیرفعال یا ناموجود"
            result[episode_id] = OwnershipState(
                episode_id=episode_id,
                owner_role=current["owner_role"],
                owner_user_id=owner_user_id,
                owner_name=owner_name,
                ownership_event_id=current["event_id"],
                ownership_event_type=current["event_type"],
            )
        return result

    def decorate_items(self, items: list[dict]) -> list[dict]:
        states = self.states([str(item["episode_id"]) for item in items])
        for item in items:
            item["ownership"] = states[str(item["episode_id"])].as_dict()
        return items

    @staticmethod
    def _permissions(user: sqlite3.Row | dict) -> frozenset[Permission]:
        return resolved_permissions(user)

    def _require_role_compatible(
        self, user: sqlite3.Row | dict, owner_role: str
    ) -> None:
        required = ROLE_PERMISSIONS[owner_role]
        if required not in self._permissions(user):
            raise FollowupOwnershipError(
                "OWNER_ROLE_PERMISSION_MISMATCH",
                "این کاربر مجوز لازم برای صف انتخاب‌شده را ندارد.",
            )

    def _require_admin(self, actor: sqlite3.Row | dict) -> None:
        if Permission.FOLLOWUP_ADMIN_MANAGE not in self._permissions(actor):
            raise FollowupOwnershipError(
                "OWNERSHIP_ADMIN_REQUIRED",
                "مجوز مدیریت واگذاری برای این اقدام ثبت نشده است.",
            )

    def capabilities(
        self, *, episode_id: str, actor: sqlite3.Row | dict
    ) -> dict:
        state = self.state(episode_id)
        permissions = self._permissions(actor)
        role = state.owner_role
        return {
            "can_claim": bool(
                role
                and state.owner_user_id is None
                and ROLE_PERMISSIONS[role] in permissions
            ),
            "can_release": bool(
                state.owner_user_id == int(actor["id"])
                or Permission.FOLLOWUP_ADMIN_MANAGE in permissions
            ),
            "can_assign": Permission.FOLLOWUP_ADMIN_MANAGE in permissions,
            "can_route": Permission.FOLLOWUP_ADMIN_MANAGE in permissions,
        }

    def assignable_users(self, owner_role: str | None = None) -> list[dict]:
        role = _normalize_role(owner_role) if owner_role else None
        rows = self.db.execute(
            """SELECT id, username, full_name, role, is_active
               FROM users WHERE is_active=1 ORDER BY full_name, username, id"""
        ).fetchall()
        result: list[dict] = []
        for row in rows:
            compatible_roles = [
                candidate
                for candidate, permission in ROLE_PERMISSIONS.items()
                if permission in self._permissions(row)
            ]
            if role and role not in compatible_roles:
                continue
            result.append(
                {
                    "id": int(row["id"]),
                    "label": self._user_label(row),
                    "compatible_roles": compatible_roles,
                }
            )
        return result

    def _existing_replay(
        self,
        *,
        episode_id: str,
        event_type: str,
        idempotency_key: str,
        payload: dict | None = None,
        request_fields: dict | None = None,
    ) -> OwnershipState | None:
        row = self.db.execute(
            """SELECT episode_id, event_type, payload_json
               FROM followup_episode_events WHERE idempotency_key=?""",
            (str(idempotency_key),),
        ).fetchone()
        if not row:
            return None
        existing = _payload(row)
        mismatch = (
            str(row["episode_id"]) != str(episode_id)
            or str(row["event_type"]) != str(event_type)
        )
        if payload is not None:
            mismatch = mismatch or canonical_json(existing) != canonical_json(payload)
        if request_fields is not None:
            mismatch = mismatch or any(
                existing.get(key) != value for key, value in request_fields.items()
            )
        if mismatch:
            raise FollowupOwnershipError(
                "OWNERSHIP_IDEMPOTENCY_CONFLICT",
                "شناسهٔ تکرار قبلاً برای اقدام دیگری استفاده شده است.",
            )
        return self.state(episode_id)

    def _append(
        self,
        *,
        episode_id: str,
        event_type: str,
        actor: sqlite3.Row | dict,
        expected_event_id: object,
        idempotency_key: str,
        payload: dict,
    ) -> OwnershipState:
        key = str(idempotency_key or "").strip()
        if len(key) < 16:
            raise FollowupOwnershipError(
                "OWNERSHIP_IDEMPOTENCY_REQUIRED",
                "شناسهٔ امن اقدام ثبت نشده است؛ صفحه را تازه کنید.",
            )
        replay = self._existing_replay(
            episode_id=episode_id,
            event_type=event_type,
            idempotency_key=key,
            payload=payload,
        )
        if replay:
            return replay

        expected = _normalize_expected(expected_event_id)
        repository = FollowupEpisodeRepository(self.db)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            projection = self._projection(episode_id)
            if str(projection["state_class"]) == "TERMINAL":
                raise FollowupOwnershipError(
                    "TERMINAL_OWNERSHIP_MUTATION",
                    "مسیر پایان‌یافته قابل دریافت یا واگذاری نیست.",
                )
            current = self.state(episode_id)
            if current.expected_event_id != expected:
                raise FollowupOwnershipError(
                    "STALE_OWNERSHIP_FORM",
                    "مسئول این مورد تغییر کرده است؛ صفحه را تازه کنید و دوباره بررسی کنید.",
                )
            repository.append_event_once(
                episode_id=str(episode_id),
                event_type=event_type,
                actor_username=str(actor["username"]),
                actor_user_id=int(actor["id"]),
                idempotency_key=key,
                payload=payload,
                effective_at=datetime.now().replace(microsecond=0),
                recorded_at=datetime.now().replace(microsecond=0),
                commit=False,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.state(episode_id)

    def claim(
        self,
        *,
        episode_id: str,
        actor: sqlite3.Row | dict,
        expected_event_id: object,
        idempotency_key: str,
    ) -> OwnershipState:
        current = self.state(episode_id)
        key = str(idempotency_key or "").strip()
        replay = self._existing_replay(
            episode_id=episode_id,
            event_type="CLAIMED",
            idempotency_key=key,
            request_fields={"action": "CLAIM", "owner_user_id": int(actor["id"])},
        )
        if replay:
            return replay
        if not current.owner_role:
            raise FollowupOwnershipError(
                "OWNER_ROLE_MISSING", "این مسیر هنوز صف مسئول مشخصی ندارد."
            )
        if current.owner_user_id is not None:
            raise FollowupOwnershipError(
                "ALREADY_CLAIMED", "این مورد قبلاً توسط فرد دیگری دریافت شده است."
            )
        self._require_role_compatible(actor, current.owner_role)
        payload = {
            "action": "CLAIM",
            "owner_role": current.owner_role,
            "owner_user_id": int(actor["id"]),
            "reason_code": "SELF_CLAIM",
        }
        return self._append(
            episode_id=episode_id,
            event_type="CLAIMED",
            actor=actor,
            expected_event_id=expected_event_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )

    def release(
        self,
        *,
        episode_id: str,
        actor: sqlite3.Row | dict,
        expected_event_id: object,
        idempotency_key: str,
        reason_code: str = "OWNER_RELEASE",
    ) -> OwnershipState:
        current = self.state(episode_id)
        key = str(idempotency_key or "").strip()
        replay = self._existing_replay(
            episode_id=episode_id,
            event_type="ASSIGNED",
            idempotency_key=key,
            request_fields={"action": "RELEASE"},
        )
        if replay:
            return replay
        if current.owner_user_id is None:
            raise FollowupOwnershipError(
                "NOT_ASSIGNED", "این مورد در حال حاضر مسئول مشخصی ندارد."
            )
        actor_id = int(actor["id"])
        if (
            current.owner_user_id != actor_id
            and Permission.FOLLOWUP_ADMIN_MANAGE not in self._permissions(actor)
        ):
            raise FollowupOwnershipError(
                "NON_OWNER_RELEASE", "فقط مسئول فعلی یا مدیر می‌تواند این مورد را آزاد کند."
            )
        payload = {
            "action": "RELEASE",
            "owner_role": current.owner_role,
            "owner_user_id": None,
            "previous_owner_user_id": current.owner_user_id,
            "reason_code": str(reason_code or "OWNER_RELEASE"),
        }
        return self._append(
            episode_id=episode_id,
            event_type="ASSIGNED",
            actor=actor,
            expected_event_id=expected_event_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )

    def route(
        self,
        *,
        episode_id: str,
        owner_role: str,
        actor: sqlite3.Row | dict,
        expected_event_id: object,
        idempotency_key: str,
        reason_code: str,
    ) -> OwnershipState:
        self._require_admin(actor)
        role = _normalize_role(owner_role)
        key = str(idempotency_key or "").strip()
        replay = self._existing_replay(
            episode_id=episode_id,
            event_type="ROUTED",
            idempotency_key=key,
            request_fields={"action": "ROUTE", "owner_role": role},
        )
        if replay:
            return replay
        current = self.state(episode_id)
        payload = {
            "action": "ROUTE",
            "owner_role": role,
            "owner_user_id": None,
            "previous_owner_role": current.owner_role,
            "previous_owner_user_id": current.owner_user_id,
            "reason_code": str(reason_code or "MANAGER_ROUTE"),
        }
        return self._append(
            episode_id=episode_id,
            event_type="ROUTED",
            actor=actor,
            expected_event_id=expected_event_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )

    def assign(
        self,
        *,
        episode_id: str,
        owner_user_id: int,
        actor: sqlite3.Row | dict,
        expected_event_id: object,
        idempotency_key: str,
        reason_code: str,
    ) -> OwnershipState:
        self._require_admin(actor)
        target_id = int(owner_user_id)
        key = str(idempotency_key or "").strip()
        replay = self._existing_replay(
            episode_id=episode_id,
            event_type="ASSIGNED",
            idempotency_key=key,
            request_fields={"owner_user_id": target_id},
        )
        if replay:
            return replay
        current = self.state(episode_id)
        if not current.owner_role:
            raise FollowupOwnershipError(
                "OWNER_ROLE_MISSING", "ابتدا صف مسئول این مسیر را مشخص کنید."
            )
        target = self._user(target_id)
        self._require_role_compatible(target, current.owner_role)
        action = "REASSIGN" if current.owner_user_id else "ASSIGN"
        payload = {
            "action": action,
            "owner_role": current.owner_role,
            "owner_user_id": int(target["id"]),
            "previous_owner_user_id": current.owner_user_id,
            "reason_code": str(reason_code or "MANAGER_ASSIGN"),
        }
        return self._append(
            episode_id=episode_id,
            event_type="ASSIGNED",
            actor=actor,
            expected_event_id=expected_event_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )


__all__ = [
    "FollowupOwnershipError",
    "FollowupOwnershipService",
    "OWNERSHIP_EVENT_TYPES",
    "OwnershipState",
    "ROLE_LABELS",
    "ROLE_PERMISSIONS",
]
