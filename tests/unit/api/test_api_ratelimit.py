from __future__ import annotations

import pytest

from sgw.api.deps import CLOCK_FUNCTIONS, clock_operator
from sgw.api.errors import Forbidden
from sgw.api.ratelimit import LoginLimiter, TokenBuckets
from sgw.api.sessions import AuthUser
from sgw.contracts.vocab import ApprovalFunction

from .api_testkit import FakeMonotonic


def test_bucket_allows_burst_then_refills() -> None:
    mono = FakeMonotonic()
    b = TokenBuckets(capacity=3, refill_per_s=1.0, clock=mono)
    assert [b.take("k") for _ in range(3)] == [0.0, 0.0, 0.0]
    assert b.take("k") == pytest.approx(1.0)
    mono.t += 1.0
    assert b.take("k") == 0.0
    assert b.take("other") == 0.0


def test_login_limiter_charges_ip_and_user() -> None:
    mono = FakeMonotonic()
    lim = LoginLimiter(TokenBuckets(100, 1, clock=mono), TokenBuckets(2, 1 / 60, clock=mono))
    assert lim.check("1.2.3.4", "ic_01") == 0 and lim.check("5.6.7.8", "ic_01") == 0
    assert lim.check("9.9.9.9", "ic_01") > 0, "rotating IPs does not escape the per-user bucket"
    lim2 = LoginLimiter(TokenBuckets(2, 1 / 60, clock=mono), TokenBuckets(100, 1, clock=mono))
    assert lim2.check("1.2.3.4", "a") == 0 and lim2.check("1.2.3.4", "b") == 0
    assert lim2.check("1.2.3.4", "c") > 0, "rotating user ids does not escape the per-IP bucket"


def _user(function: ApprovalFunction, roles: tuple[str, ...]) -> AuthUser:
    return AuthUser("u_01", "U", function, roles, (), (), None, "0" * 64, False)


def test_clock_operator_is_command_operations_or_presenter() -> None:
    for fn in CLOCK_FUNCTIONS:
        assert clock_operator(_user(fn, ("x",))).function is fn
    assert clock_operator(_user(ApprovalFunction.EXECUTIVE, ("presenter",)))
    for fn in (ApprovalFunction.AUDIT, ApprovalFunction.WATER_OPERATIONS, ApprovalFunction.LOGISTICS):
        with pytest.raises(Forbidden):
            clock_operator(_user(fn, ("x",)))
