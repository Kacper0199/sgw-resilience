"""K10 policy parameters (`kind=policy` in `data/numbers/numbers.yaml`) for K3 `/api/policies`: the target
of the UI policy chips ("Assumed SGW policy")."""

from __future__ import annotations

from functools import cache

from sgw.common import numbers as numbers_mod
from sgw.contracts.api_models import PolicyParam
from sgw.contracts.vocab import NumberKind


@cache
def policies() -> tuple[PolicyParam, ...]:
    return tuple(
        PolicyParam(
            key=key, value=e.value, unit=e.unit, label=e.label, kind=NumberKind.POLICY, source=e.source
        )
        for key, e in sorted(numbers_mod.numbers().items())
        if e.kind is NumberKind.POLICY
    )
