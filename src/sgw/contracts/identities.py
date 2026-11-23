"""K18 seeded identities (`data/seed/users.yaml`, X-01). Display names are role titles; the demo password
is read from `DEMO_PASSWORD` by name only."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import Field, model_validator

from sgw.contracts.base import Contract
from sgw.contracts.vocab import ApprovalFunction, Domain

PASSWORD_ENV = "DEMO_PASSWORD"  # noqa: S105
PUBLIC_DEMO_PASSWORD = "123"  # noqa: S105  the local-demo value the sign-in page may print


def password_env_for(user_id: str) -> str:
    """Per-persona password variable DEMO_PASSWORD_<USER_ID>, written by `sgw bootstrap` to var/demo.env."""
    return f"{PASSWORD_ENV}_{''.join(c if c.isalnum() else '_' for c in user_id).upper()}"


def demo_password_for(user_id: str, env: Mapping[str, str]) -> str | None:
    """The persona's own password, else the legacy shared DEMO_PASSWORD; read by name, never logged."""
    return env.get(password_env_for(user_id)) or env.get(PASSWORD_ENV) or None


class SeedUser(Contract):
    user_id: str = Field(pattern=r"^[a-z][a-z_]*_\d{2}$")
    display_name: str
    persona: str
    function: ApprovalFunction
    roles: list[str]
    regions: list[str]
    domains: list[Domain]
    can_approve: bool
    break_glass_eligible: bool = False
    kill_trigger: bool = False


class SeedUsers(Contract):
    version: int
    password_env: str
    users: list[SeedUser]

    @model_validator(mode="after")
    def _checks(self) -> SeedUsers:
        ids = [u.user_id for u in self.users]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate user ids")
        if self.password_env != PASSWORD_ENV:
            raise ValueError("password is read from DEMO_PASSWORD by name only")
        return self

    def by_function(self, fn: ApprovalFunction) -> list[SeedUser]:
        return [u for u in self.users if u.function is fn and u.can_approve]


def load_users(path: Path) -> SeedUsers:
    return SeedUsers.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
