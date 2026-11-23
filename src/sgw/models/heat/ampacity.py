"""Steady-state conductor ampacity, IEEE 738 heat balance (R02 1.2; equations as cited in the MIT-licensed
`statnett/linerate` implementation): `I = sqrt((q_c + q_r - q_s) / R(T_c))`, all heat terms in W/m.

- forced convection: q_c1 = K_angle (1.01 + 1.35 Re^0.52) k_f dT, q_c2 = K_angle 0.754 Re^0.6 k_f dT,
  Re = D rho_f V / mu_f; natural convection q_cn = 3.645 rho_f^0.5 D^0.75 dT^1.25; q_c = max of the three;
- radiation q_r = 17.8 D eps (((T_c + 273)/100)^4 - ((T_a + 273)/100)^4);
- solar q_s = alpha Q_se D (sun normal to the conductor, worst case);
- air properties at T_film = (T_c + T_a)/2, elevation H in m; D in m; R(T_c) linear between 25 and 75 deg C.

Domain: steady state, wind 0-10 m/s, ambient -10..45 deg C. Conductor data in `params.yaml` are typical values
[A]; the IEEE 738 Drake example (100 deg C, 40 deg C, 0.61 m/s) is the verification case.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Conductor:
    name: str
    diameter_m: float
    r25_ohm_per_m: float
    r75_ohm_per_m: float
    emissivity: float = 0.5
    absorptivity: float = 0.5
    max_temp_c: float = 75.0

    def resistance(self, t_c: float) -> float:
        slope = (self.r75_ohm_per_m - self.r25_ohm_per_m) / 50.0
        return self.r25_ohm_per_m + slope * (t_c - 25.0)


@dataclass(frozen=True)
class HeatTerms:
    q_convection: float
    q_radiation: float
    q_solar: float
    ampacity_a: float


def _air(t_film: float, elevation_m: float) -> tuple[float, float, float]:
    mu = 1.458e-6 * (t_film + 273.0) ** 1.5 / (t_film + 383.4)
    rho = (1.293 - 1.525e-4 * elevation_m + 6.379e-9 * elevation_m**2) / (1.0 + 0.00367 * t_film)
    k = 2.424e-2 + 7.477e-5 * t_film - 4.407e-9 * t_film**2
    return mu, rho, k


def k_angle(phi_deg: float) -> float:
    phi = math.radians(phi_deg)
    return 1.194 - math.cos(phi) + 0.194 * math.cos(2 * phi) + 0.368 * math.sin(2 * phi)


def heat_terms(
    c: Conductor,
    t_ambient_c: float,
    wind_ms: float,
    solar_w_m2: float,
    t_conductor_c: float | None = None,
    wind_angle_deg: float = 90.0,
    elevation_m: float = 100.0,
) -> HeatTerms:
    tc = c.max_temp_c if t_conductor_c is None else t_conductor_c
    if tc <= t_ambient_c:
        raise ValueError("conductor temperature must exceed ambient")
    d = c.diameter_m
    dt = tc - t_ambient_c
    mu, rho, k = _air((tc + t_ambient_c) / 2.0, elevation_m)
    re = d * rho * max(wind_ms, 0.0) / mu
    ka = k_angle(wind_angle_deg)
    qc1 = ka * (1.01 + 1.35 * re**0.52) * k * dt
    qc2 = ka * 0.754 * re**0.6 * k * dt
    qcn = 3.645 * rho**0.5 * d**0.75 * dt**1.25
    qc = max(qc1, qc2, qcn)
    qr = 17.8 * d * c.emissivity * (((tc + 273.0) / 100.0) ** 4 - ((t_ambient_c + 273.0) / 100.0) ** 4)
    qs = c.absorptivity * solar_w_m2 * d
    net = qc + qr - qs
    amp = math.sqrt(net / c.resistance(tc)) if net > 0 else 0.0
    return HeatTerms(qc, qr, qs, amp)


def ampacity(c: Conductor, t_ambient_c: float, wind_ms: float, solar_w_m2: float, **kw: float) -> float:
    return heat_terms(c, t_ambient_c, wind_ms, solar_w_m2, **kw).ampacity_a
