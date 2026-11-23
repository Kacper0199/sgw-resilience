"""Pipeline asset registry. An asset is a function `(ctx, conn) -> AssetResult` with upstream dependencies and
an optional freshness rule; the runner executes them in dependency order and records `pipeline_run` and
`dq_check` rows. Modules register assets with `@asset(...)` at import time."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import psycopg

if TYPE_CHECKING:
    from sgw.pipeline.context import RunContext

Severity = Literal["warn", "error"]


@dataclass(frozen=True)
class CheckResult:
    name: str
    severity: Severity
    passed: bool
    observed: str
    freshness_limit_s: int | None = None


@dataclass
class AssetResult:
    rows_in: int = 0
    rows_out: int = 0
    rows_quarantined: int = 0
    watermarks: dict[str, Any] = field(default_factory=dict)
    checks: list[CheckResult] = field(default_factory=list)
    extra_events: list[Any] = field(default_factory=list)


AssetFn = Callable[["RunContext", psycopg.Connection], AssetResult]


@dataclass(frozen=True)
class AssetSpec:
    name: str
    fn: AssetFn
    deps: tuple[str, ...]
    freshness_limit_s: int | None
    description: str
    runs_after_failure: bool = False


REGISTRY: dict[str, AssetSpec] = {}


class RegistryError(ValueError):
    pass


def asset(
    name: str,
    *,
    deps: tuple[str, ...] = (),
    freshness_limit_s: int | None = None,
    runs_after_failure: bool = False,
) -> Callable[[AssetFn], AssetFn]:
    def register(fn: AssetFn) -> AssetFn:
        if name in REGISTRY and REGISTRY[name].fn is not fn:
            raise RegistryError(f"asset {name!r} registered twice")
        REGISTRY[name] = AssetSpec(
            name, fn, deps, freshness_limit_s, (fn.__doc__ or "").strip(), runs_after_failure
        )
        return fn

    return register


def topo_order(
    names: list[str] | None = None, registry: dict[str, AssetSpec] | None = None
) -> list[AssetSpec]:
    reg = registry if registry is not None else REGISTRY
    wanted = set(names or reg)
    missing = wanted - set(reg)
    if missing:
        raise RegistryError(f"unknown assets: {sorted(missing)}")
    order: list[AssetSpec] = []
    state: dict[str, int] = {}

    def visit(name: str, path: tuple[str, ...]) -> None:
        if state.get(name) == 2:
            return
        if state.get(name) == 1:
            raise RegistryError(f"dependency cycle: {' -> '.join((*path, name))}")
        if name not in reg:
            raise RegistryError(f"{path[-1] if path else name} depends on unknown asset {name!r}")
        state[name] = 1
        for dep in reg[name].deps:
            visit(dep, (*path, name))
        state[name] = 2
        order.append(reg[name])

    for name in sorted(wanted):
        visit(name, ())
    return order


def lineage(registry: dict[str, AssetSpec] | None = None) -> list[tuple[str, str]]:
    reg = registry if registry is not None else REGISTRY
    return sorted((dep, spec.name) for spec in reg.values() for dep in spec.deps)
