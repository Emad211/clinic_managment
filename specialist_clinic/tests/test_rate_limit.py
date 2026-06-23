"""Unit tests for src.common.rate_limit (SECU-13).

Deterministic: every call injects `now` so no real clock is used.
Thread-safety: a small concurrent smoke-test confirms no crash and no
over-admission.

Run:
    .venv/Scripts/python.exe -m pytest tests/test_rate_limit.py -v
"""
import sys
import os
import threading

sys.stdout.reconfigure(encoding="utf-8")

# Make sure the specialist_clinic package is importable regardless of cwd.
_SPECIALIST_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
if _SPECIALIST_ROOT not in sys.path:
    sys.path.insert(0, _SPECIALIST_ROOT)

import pytest
from src.common.rate_limit import allow, reset


# ---------------------------------------------------------------------------
# Auto-reset: each test starts from a clean slate.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean():
    reset()
    yield
    reset()


# ---------------------------------------------------------------------------
# 1. Within-limit: first `limit` calls True; call limit+1 in same window → False
# ---------------------------------------------------------------------------

class TestWithinAndExceedLimit:

    def test_exact_limit_all_true(self):
        """Calls 1..limit at the same `now` must all be True."""
        limit = 5
        for i in range(limit):
            result = allow("k1", limit=limit, per_seconds=60.0, now=100.0)
            assert result is True, f"Expected True on call {i+1}, got False"

    def test_limit_plus_one_is_false(self):
        """Call limit+1 at the same `now` must return False without recording."""
        limit = 5
        for _ in range(limit):
            allow("k1", limit=limit, per_seconds=60.0, now=100.0)
        result = allow("k1", limit=limit, per_seconds=60.0, now=100.0)
        assert result is False, "Expected False on call limit+1, got True"

    def test_limit_one_second_call_then_false(self):
        """limit=1: first call True, second call at same time → False."""
        assert allow("k_one", limit=1, per_seconds=60.0, now=0.0) is True
        assert allow("k_one", limit=1, per_seconds=60.0, now=0.0) is False

    def test_limit_zero_always_false(self):
        """limit=0 means no calls are permitted at all."""
        assert allow("k_zero", limit=0, per_seconds=60.0, now=0.0) is False

    def test_false_does_not_record(self):
        """After a rejected call, the window count must not increase.

        If the rejected call were recorded, the next legitimate call (after
        the window expires) would be off-by-one.
        """
        limit = 2
        allow("k_nr", limit=limit, per_seconds=10.0, now=0.0)
        allow("k_nr", limit=limit, per_seconds=10.0, now=1.0)
        # window full — reject
        assert allow("k_nr", limit=limit, per_seconds=10.0, now=1.0) is False
        # 11 seconds later: both original hits expired → fresh window
        assert allow("k_nr", limit=limit, per_seconds=10.0, now=11.0) is True


# ---------------------------------------------------------------------------
# 2. Sliding-window expiry
# ---------------------------------------------------------------------------

class TestSlidingWindow:

    def test_three_hits_then_expire_and_admit(self):
        """Classic sliding window: 3 hits at t=0,1,2; t=3 full (per=60);
        at t=61 the t=0 hit expires → window has room again.
        """
        limit = 3
        per = 60.0

        assert allow("sw", limit=limit, per_seconds=per, now=0.0)  is True   # 1
        assert allow("sw", limit=limit, per_seconds=per, now=1.0)  is True   # 2
        assert allow("sw", limit=limit, per_seconds=per, now=2.0)  is True   # 3  (window full)
        assert allow("sw", limit=limit, per_seconds=per, now=3.0)  is False  # still full (oldest=0, cutoff=3-60=-57 → 0≥-57 kept)
        # At now=61 cutoff=1.0 → hit at t=0.0 < 1.0 → evicted; queue=[1.0,2.0] len=2 < 3
        assert allow("sw", limit=limit, per_seconds=per, now=61.0) is True   # window slid

    def test_exact_boundary_not_yet_expired(self):
        """A hit at t=0 with per=10: at t=10 the cutoff is 0.0.
        The hit is at 0.0 which is NOT < 0.0, so it's still counted.
        """
        assert allow("bnd", limit=1, per_seconds=10.0, now=0.0) is True
        # cutoff = 10 - 10 = 0.0; q[0]=0.0 is NOT < 0.0 → stays → window full
        assert allow("bnd", limit=1, per_seconds=10.0, now=10.0) is False

    def test_just_past_boundary_expires(self):
        """A hit at t=0 with per=10: at t=10.001 the cutoff is 0.001.
        0.0 < 0.001 → evicted → room for new hit.
        """
        assert allow("bnd2", limit=1, per_seconds=10.0, now=0.0) is True
        assert allow("bnd2", limit=1, per_seconds=10.0, now=10.001) is True

    def test_partial_expiry(self):
        """5 hits spread in time; partial window slide evicts only the oldest."""
        limit = 3
        per = 30.0
        # hits at t=0, 5, 10 (window full at t=10)
        allow("par", limit=limit, per_seconds=per, now=0.0)
        allow("par", limit=limit, per_seconds=per, now=5.0)
        allow("par", limit=limit, per_seconds=per, now=10.0)
        assert allow("par", limit=limit, per_seconds=per, now=10.0) is False  # full

        # At t=31 cutoff=1.0; t=0 evicted; queue=[5,10], len=2 < 3 → admit
        assert allow("par", limit=limit, per_seconds=per, now=31.0) is True

        # At t=36 cutoff=6.0; t=5 evicted; queue=[10,31], len=2 < 3 → admit
        assert allow("par", limit=limit, per_seconds=per, now=36.0) is True

    def test_per_second_window_sub_second_granularity(self):
        """per_seconds=1: three sub-second hits → window full; 1s later → clear."""
        limit = 3
        per = 1.0
        allow("sub", limit=limit, per_seconds=per, now=0.0)
        allow("sub", limit=limit, per_seconds=per, now=0.3)
        allow("sub", limit=limit, per_seconds=per, now=0.6)
        assert allow("sub", limit=limit, per_seconds=per, now=0.9) is False
        # now=1.01 → cutoff=0.01; hits at 0.0 < 0.01 evicted; [0.3, 0.6] → room
        assert allow("sub", limit=limit, per_seconds=per, now=1.01) is True


# ---------------------------------------------------------------------------
# 3. Key independence
# ---------------------------------------------------------------------------

class TestKeyIndependence:

    def test_different_keys_are_independent(self):
        """Exhausting key 'a' must not affect key 'b'."""
        limit = 3
        for _ in range(limit):
            allow("a", limit=limit, per_seconds=60.0, now=0.0)
        # 'a' is now full
        assert allow("a", limit=limit, per_seconds=60.0, now=0.0) is False
        # 'b' is untouched → still admits
        assert allow("b", limit=limit, per_seconds=60.0, now=0.0) is True

    def test_many_keys_do_not_cross_contaminate(self):
        """100 distinct keys, each with limit=1; exhausting each must not
        spill into others."""
        limit = 1
        keys = [f"ip_{i}" for i in range(100)]
        # Fill each key
        for k in keys:
            assert allow(k, limit=limit, per_seconds=60.0, now=0.0) is True
        # Each should now be full
        for k in keys:
            assert allow(k, limit=limit, per_seconds=60.0, now=0.0) is False

    def test_key_with_different_limit_settings(self):
        """The same key called with different limits should respect each call's
        limit argument independently (limit is per-call, not per-key)."""
        # With limit=5: first 5 True
        for _ in range(5):
            assert allow("mixed", limit=5, per_seconds=60.0, now=0.0) is True
        # 6th with limit=5 → False
        assert allow("mixed", limit=5, per_seconds=60.0, now=0.0) is False
        # But with limit=10 (same key, same window, 5 hits recorded) → True
        assert allow("mixed", limit=10, per_seconds=60.0, now=0.0) is True


# ---------------------------------------------------------------------------
# 4. reset() clears all state
# ---------------------------------------------------------------------------

class TestReset:

    def test_reset_clears_full_window(self):
        """After filling a window, reset() must make allow() return True again."""
        limit = 2
        allow("r", limit=limit, per_seconds=60.0, now=0.0)
        allow("r", limit=limit, per_seconds=60.0, now=0.0)
        assert allow("r", limit=limit, per_seconds=60.0, now=0.0) is False  # full

        reset()

        assert allow("r", limit=limit, per_seconds=60.0, now=0.0) is True  # clean slate

    def test_reset_clears_all_keys(self):
        """reset() must clear every key, not just one."""
        keys = ["x", "y", "z"]
        limit = 1
        for k in keys:
            allow(k, limit=limit, per_seconds=60.0, now=0.0)
            assert allow(k, limit=limit, per_seconds=60.0, now=0.0) is False

        reset()

        for k in keys:
            assert allow(k, limit=limit, per_seconds=60.0, now=0.0) is True, (
                f"Key '{k}' not cleared by reset()"
            )

    def test_double_reset_is_safe(self):
        """Calling reset() twice must not raise."""
        reset()
        reset()  # no exception expected

    def test_reset_on_empty_state_is_safe(self):
        """reset() on a fresh (or already-reset) state must not raise."""
        reset()  # state already clean from autouse fixture
        # If no exception, the test passes.


# ---------------------------------------------------------------------------
# 5. Thread-safety smoke test
# ---------------------------------------------------------------------------

class TestThreadSafety:

    def test_concurrent_calls_no_crash(self):
        """Multiple threads calling allow() concurrently must not raise.
        Uses real time.monotonic() (now=None) to stress the lock path.
        """
        limit = 50
        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(20):
                    allow("thread_key", limit=limit, per_seconds=60.0)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread(s) raised exceptions: {errors}"

    def test_concurrent_calls_no_over_admission(self):
        """With limit=10 and many concurrent threads, the number of admitted
        (True) results must not exceed the limit within the same time window.

        Strategy: inject a fixed `now` for all threads so every call falls
        in the same window; count True results; assert ≤ limit.
        """
        reset()
        limit = 10
        admitted: list[bool] = []
        lock = threading.Lock()

        def worker():
            result = allow("oa_key", limit=limit, per_seconds=60.0, now=500.0)
            with lock:
                admitted.append(result)

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        true_count = sum(admitted)
        assert true_count <= limit, (
            f"Over-admitted: {true_count} True results for limit={limit}"
        )
        assert true_count == limit, (
            f"Under-admitted: only {true_count} True results; expected exactly {limit}"
        )
