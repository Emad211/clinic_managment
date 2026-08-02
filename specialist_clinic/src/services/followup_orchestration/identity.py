"""Deterministic, versioned identity for operational follow-up episodes."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

IDENTITY_VERSION = "1.0"
EPISODE_ID_PREFIX = "fuep_"
_ALLOWED_EPISODE_TYPES = frozenset(
    {"ADMIN_FOLLOWUP", "CLINICAL_TASK", "ENCOUNTER_COMMITMENT", "ENGAGEMENT"}
)


def canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _clean(value: object, *, field: str, minimum: int = 1, maximum: int = 300) -> str:
    text = str(value or "").strip()
    if not minimum <= len(text) <= maximum:
        raise ValueError(f"invalid {field}")
    return text


@dataclass(frozen=True, slots=True)
class EpisodeIdentity:
    patient_link_id: int
    episode_type: str
    semantic_key: str
    period_key: str
    identity_version: str
    identity_hash: str
    episode_id: str

    @classmethod
    def build(
        cls,
        *,
        patient_link_id: int,
        episode_type: str,
        semantic_key: str,
        period_key: str,
        identity_version: str = IDENTITY_VERSION,
    ) -> "EpisodeIdentity":
        patient = int(patient_link_id)
        if patient <= 0:
            raise ValueError("invalid patient_link_id")
        kind = _clean(episode_type, field="episode_type", maximum=60).upper()
        if kind not in _ALLOWED_EPISODE_TYPES:
            raise ValueError("invalid episode_type")
        semantic = _clean(semantic_key, field="semantic_key").lower()
        period = _clean(period_key, field="period_key", maximum=200).lower()
        version = _clean(identity_version, field="identity_version", maximum=20)
        payload = {
            "episode_type": kind,
            "identity_version": version,
            "patient_link_id": patient,
            "period_key": period,
            "semantic_key": semantic,
        }
        digest = canonical_hash(payload)
        return cls(
            patient_link_id=patient,
            episode_type=kind,
            semantic_key=semantic,
            period_key=period,
            identity_version=version,
            identity_hash=digest,
            episode_id=EPISODE_ID_PREFIX + digest,
        )

    def as_dict(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "patient_link_id": self.patient_link_id,
            "episode_type": self.episode_type,
            "semantic_key": self.semantic_key,
            "period_key": self.period_key,
            "identity_version": self.identity_version,
            "identity_hash": self.identity_hash,
        }


__all__ = [
    "EPISODE_ID_PREFIX",
    "IDENTITY_VERSION",
    "EpisodeIdentity",
    "canonical_hash",
    "canonical_json",
]
