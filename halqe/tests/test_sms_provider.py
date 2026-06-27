"""
tests/test_sms_provider.py — SMS provider safety-gate tests (step 53).

Focus: the TWO-GATE live policy in clinical.sms.provider.get_provider().
A configured KAVENEGAR_API_KEY is NOT sufficient to send real SMS — the
explicit SMS_LIVE_ENABLED gate must ALSO be True, and only after owner KYC.

These tests are DB-FREE on purpose:
  - No @pytest.mark.django_db, no `db` fixture in any signature → the autouse
    set_default_tenant_guc fixture (gated on `db`) never runs, so no DB is
    touched and Postgres is not required.
  - They use @override_settings to flip SMS_* settings deterministically.
  - NO real HTTP / network is ever made:
      * the NullProvider branch returns SIMULATED without any socket use;
      * the KavenegarProvider branch is asserted with isinstance ONLY —
        .send() is NEVER called against the network;
      * the 430 mapping is a pure dict assertion.

NEVER put a real API key here. The 'kavenegar' tests use an obviously-fake
placeholder key and never call .send().
"""
from django.test import override_settings

from clinical.sms.provider import (
    KavenegarProvider,
    NullProvider,
    SendResult,
    _KAVENEGAR_CODES,
    get_provider,
)

# An obviously-fake, non-functional placeholder. NEVER a real key. We only ever
# construct a provider object with it and assert isinstance — never .send().
_FAKE_KEY = "FAKE-TEST-KEY-NOT-REAL-DO-NOT-SEND"


# ---------------------------------------------------------------------------
# 1 — default (no key, no flag) → NullProvider
# ---------------------------------------------------------------------------
@override_settings(SMS_PROVIDER="kavenegar", KAVENEGAR_API_KEY="", SMS_LIVE_ENABLED=False)
def test_default_no_key_no_flag_is_null_provider():
    """Default config (no key, flag off) → NullProvider (default-safe)."""
    provider = get_provider()
    assert isinstance(provider, NullProvider)


# ---------------------------------------------------------------------------
# 2 — THE new safety gate: key present BUT SMS_LIVE_ENABLED=False → NullProvider
# ---------------------------------------------------------------------------
@override_settings(
    SMS_PROVIDER="kavenegar",
    KAVENEGAR_API_KEY=_FAKE_KEY,
    SMS_LIVE_ENABLED=False,
)
def test_key_present_but_live_disabled_is_null_provider():
    """
    THE KEY SAFETY GATE: a configured key is NOT sufficient.

    With a key present but SMS_LIVE_ENABLED=False the system MUST stay on
    NullProvider — merely setting KAVENEGAR_API_KEY must never flip live sends.
    """
    provider = get_provider()
    assert isinstance(provider, NullProvider), (
        "A configured key with SMS_LIVE_ENABLED=False MUST yield NullProvider "
        "(the owner KYC gate)."
    )


# ---------------------------------------------------------------------------
# 3 — SMS_PROVIDER='null' → NullProvider regardless of key / flag
# ---------------------------------------------------------------------------
@override_settings(
    SMS_PROVIDER="null",
    KAVENEGAR_API_KEY=_FAKE_KEY,
    SMS_LIVE_ENABLED=True,
)
def test_provider_null_overrides_everything():
    """SMS_PROVIDER='null' forces NullProvider even with key + flag on."""
    provider = get_provider()
    assert isinstance(provider, NullProvider)


# ---------------------------------------------------------------------------
# 4 — kavenegar + key + SMS_LIVE_ENABLED=True → KavenegarProvider (isinstance ONLY)
# ---------------------------------------------------------------------------
@override_settings(
    SMS_PROVIDER="kavenegar",
    KAVENEGAR_API_KEY=_FAKE_KEY,
    KAVENEGAR_SENDER="",
    KAVENEGAR_TIMEOUT=45,
    SMS_LIVE_ENABLED=True,
)
def test_all_gates_open_returns_kavenegar_provider():
    """
    All three gates open → a real KavenegarProvider instance.

    We assert isinstance ONLY. We NEVER call .send() — that would attempt a
    real network call. This proves wiring, not connectivity.
    """
    provider = get_provider()
    assert isinstance(provider, KavenegarProvider)
    # The provider carries the (fake) key but is never exercised over the wire.
    assert provider.api_key == _FAKE_KEY


@override_settings(
    SMS_PROVIDER="kavenegar",
    KAVENEGAR_API_KEY=_FAKE_KEY,
    SMS_LIVE_ENABLED=True,
)
def test_live_gate_truthy_flag_required_exact():
    """
    Sanity: with the flag genuinely True (not just key present) we get the
    live provider — the positive counterpart to the gate test above.
    """
    assert isinstance(get_provider(), KavenegarProvider)


# ---------------------------------------------------------------------------
# 5 — NullProvider().send(...) returns SIMULATED, deterministic, no HTTP
# ---------------------------------------------------------------------------
def test_null_provider_send_is_simulated_and_deterministic():
    """
    NullProvider.send() returns SendResult(ok=True, provider_msgid='SIMULATED')
    and makes NO network call. Deterministic across inputs/calls.
    """
    provider = NullProvider()
    r1 = provider.send("09120000000", "سلام، این یک پیام آزمایشی است")
    assert isinstance(r1, SendResult)
    assert r1.ok is True
    assert r1.provider_msgid == "SIMULATED"
    assert r1.pending is False
    assert r1.error is None

    # Deterministic: a different recipient/body yields the same shape.
    r2 = provider.send("09350000001", "متن دیگر")
    assert r2.ok is True
    assert r2.provider_msgid == "SIMULATED"
    assert r1 == r2  # dataclass equality — fully deterministic


def test_get_provider_default_send_path_is_simulated():
    """
    End-to-end of the safe default: get_provider() with no live config returns
    NullProvider whose send() simulates — no real SMS, no network.
    """
    with override_settings(
        SMS_PROVIDER="kavenegar", KAVENEGAR_API_KEY="", SMS_LIVE_ENABLED=False
    ):
        provider = get_provider()
    assert isinstance(provider, NullProvider)
    result = provider.send("09120000000", "تست")
    assert result.ok is True
    assert result.provider_msgid == "SIMULATED"


# ---------------------------------------------------------------------------
# 6 — 430 KYC code mapped to a Persian KYC message (pure dict, no network)
# ---------------------------------------------------------------------------
def test_code_430_maps_to_persian_kyc_message():
    """
    The 430 status (the KNOWN account gate) maps to a Persian message that
    mentions KYC / احراز هویت. Pure dict assertion — no network.
    """
    assert 430 in _KAVENEGAR_CODES
    msg = _KAVENEGAR_CODES[430]
    assert "احراز هویت" in msg
    assert "KYC" in msg


def test_code_200_maps_to_confirmation():
    """Sanity: 200 is the success/confirmation mapping."""
    assert _KAVENEGAR_CODES.get(200) == "تأیید شد"
