"""Transformer top-oil and hot-spot temperature, IEC 60076-7 differential-equation method.

    d(theta_o)/dt = (dTheta_or ((1 + K^2 R)/(1 + R))^x - (theta_o - theta_a)) / (k11 tau_o)
    d(h1)/dt      = (k21 dTheta_hr K^y - h1) / (k22 tau_w)
    d(h2)/dt      = ((k21 - 1) dTheta_hr K^y - h2) / (tau_o / k22)
    theta_h       = theta_o + h1 - h2

t in minutes, temperatures in deg C, K = load / rated (pu). Integrated with explicit Euler at `dt_min`, which
IEC requires to be below half the smallest time constant (k22 tau_w / 2 = 4 min for distribution ONAN; we use
1 min and verify convergence by halving). Ageing: relative ageing rate
F_AA = exp(15000/383 - 15000/(theta_h + 273)) (thermally upgraded paper, 110 deg C reference) and loss of
life in equivalent hours. Table 5 constants are [F]; rated rises dTheta_or = 55 K, dTheta_hr = 23 K and
R = 6 are not in the free preview and are [A].
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Cooling:
    name: str
    x: float
    y: float
    k11: float
    k21: float
    k22: float
    tau_o_min: float
    tau_w_min: float
    d_theta_or: float = 55.0
    d_theta_hr: float = 23.0
    r: float = 6.0


DISTRIBUTION_ONAN = Cooling("distribution ONAN", 0.8, 1.6, 1.0, 1.0, 2.0, 180.0, 4.0)
ONAF = Cooling("ONAF", 0.8, 1.3, 0.5, 2.0, 2.0, 150.0, 7.0)
COOLING = {"distribution_onan": DISTRIBUTION_ONAN, "onaf": ONAF}


@dataclass(frozen=True)
class ThermalTrace:
    t_min: list[float]
    theta_a: list[float]
    k: list[float]
    theta_o: list[float]
    theta_h: list[float]
    faa: list[float]
    loss_of_life_h: float


def faa(theta_h: float) -> float:
    return math.exp(15000.0 / 383.0 - 15000.0 / (theta_h + 273.0))


def steady_state(c: Cooling, k: float, theta_a: float) -> tuple[float, float]:
    """(top oil, hot spot) at constant load and ambient."""
    oil = theta_a + c.d_theta_or * ((1.0 + k * k * c.r) / (1.0 + c.r)) ** c.x
    return oil, oil + c.d_theta_hr * k**c.y


def simulate(
    c: Cooling,
    k: Sequence[float],
    theta_a: Sequence[float],
    dt_min: float = 1.0,
    initial: tuple[float, float, float] | None = None,
) -> ThermalTrace:
    """`k` and `theta_a` are per-step inputs (length n); starts in steady state at the first inputs unless
    `initial` = (theta_o, h1, h2) is given."""
    if len(k) != len(theta_a) or not k:
        raise ValueError("k and theta_a need the same non-zero length")
    if dt_min <= 0 or dt_min > min(c.k22 * c.tau_w_min, c.tau_o_min / c.k22, c.k11 * c.tau_o_min) / 2.0:
        raise ValueError("time step must be positive and below half the smallest time constant (IEC 60076-7)")
    if initial is None:
        oil0, _ = steady_state(c, k[0], theta_a[0])
        h1 = c.k21 * c.d_theta_hr * k[0] ** c.y
        h2 = (c.k21 - 1.0) * c.d_theta_hr * k[0] ** c.y
        state = (oil0, h1, h2)
    else:
        state = initial
    oil, h1, h2 = state
    out_o: list[float] = []
    out_h: list[float] = []
    out_f: list[float] = []
    lol = 0.0
    for kk, ta in zip(k, theta_a, strict=True):
        hs = oil + h1 - h2
        out_o.append(oil)
        out_h.append(hs)
        f = faa(hs)
        out_f.append(f)
        lol += f * dt_min / 60.0
        ky = kk**c.y
        d_oil = (c.d_theta_or * ((1.0 + kk * kk * c.r) / (1.0 + c.r)) ** c.x - (oil - ta)) / (
            c.k11 * c.tau_o_min
        )
        d_h1 = (c.k21 * c.d_theta_hr * ky - h1) / (c.k22 * c.tau_w_min)
        d_h2 = ((c.k21 - 1.0) * c.d_theta_hr * ky - h2) / (c.tau_o_min / c.k22)
        oil += dt_min * d_oil
        h1 += dt_min * d_h1
        h2 += dt_min * d_h2
    return ThermalTrace([i * dt_min for i in range(len(k))], list(theta_a), list(k), out_o, out_h, out_f, lol)
