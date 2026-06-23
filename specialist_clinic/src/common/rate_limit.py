"""Tiny in-process rate limiter (SECU-13). Thread-safe, dependency-free.

A sliding-window counter kept in this process's memory. It blunts brute-force /
scraping on the public, token-addressed surfaces (the patient card `/card/<token>` and
the extension bridge `/api/ext/*`) while the app runs as a single process.

SCOPE NOTE (roadmap): this is **per-process** — counters are NOT shared across multiple
instances. The distributed (Redis/DB-backed) version belongs to the cloud platform; until
then the app is one process so an in-memory limiter is sufficient and correct.

Usage:
    from src.common.rate_limit import allow
    if not allow(f"card:{ip}", limit=30, per_seconds=60):
        abort(429)
"""
import threading
import time

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}
_calls = 0


def allow(key: str, limit: int, per_seconds: float = 60.0, now: float | None = None) -> bool:
    """Sliding window: permit at most `limit` events per `per_seconds` for `key`.

    Records and permits the event when within the limit (returns True); otherwise returns
    False without recording. `now` (monotonic seconds) is injectable for deterministic tests.
    """
    global _calls
    t = time.monotonic() if now is None else now
    cutoff = t - per_seconds
    with _lock:
        # Opportunistic sweep so stale keys can't grow memory without bound.
        _calls += 1
        if _calls % 5000 == 0:
            for k in [k for k, v in _hits.items() if not v or v[-1] < cutoff]:
                _hits.pop(k, None)

        q = _hits.setdefault(key, [])
        while q and q[0] < cutoff:
            q.pop(0)
        if len(q) >= limit:
            return False
        q.append(t)
        return True


def reset() -> None:
    """Clear all counters (used by tests to isolate cases)."""
    global _calls
    with _lock:
        _hits.clear()
        _calls = 0
