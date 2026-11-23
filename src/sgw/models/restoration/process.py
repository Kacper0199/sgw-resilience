"""Restoration process (the truth the ETR model is scored against): job-level crew dispatch with shifts.

What it adds to the WP-06 generator, whose county t90 was 60.8 h against 106-108 h observed for Helene:
- secondary jobs (transformers, service drops) behind each failed section: few customers each, so priority
  dispatch leaves them to the end; they become visible only once their section is back (the long tail);
- crews work 16 h on / 8 h off (`DutyClock`); a group of `headcount / 4` line crews splits section work and
  runs secondary jobs in parallel;
- storm-level effects on productivity and on the number of secondary jobs (family-A truth draws only).

Units: times are epoch seconds UTC; work is line-crew on-duty hours; regions are crew-yard operating areas.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np

from sgw.generator.config import load_family, rng
from sgw.generator.wind import distance_km
from sgw.models.restoration.params import DutyClock, Params, default_params
from sgw.models.restoration.world import World

SECTION = 0
SECONDARY = 1
CRITICAL_BONUS = 1e12


@dataclass(frozen=True)
class StormEffects:
    productivity_log: float = 0.0
    secondary_log: float = 0.0
    mutual_aid_delay_h: np.ndarray | None = None

    @classmethod
    def draw(cls, world: World, prm: Params, seed: int) -> StormEffects:
        r = rng(seed, "wp17", "storm_effects")
        prod = float(r.normal(0.0, prm.f("process", "productivity_sigma")))
        sec = float(r.normal(0.0, prm.f("process", "secondary_rate_sigma")))
        return cls(prod, sec, None)


@dataclass
class Jobs:
    kind: np.ndarray
    section: np.ndarray
    region: np.ndarray
    customers: np.ndarray
    work: np.ndarray
    lat: np.ndarray
    lon: np.ndarray

    def __len__(self) -> int:
        return len(self.kind)


@dataclass
class ProcessRun:
    world: World
    jobs: Jobs
    release: np.ndarray
    assigned: np.ndarray
    arrive: np.ndarray
    start: np.ndarray
    end: np.ndarray
    crew: np.ndarray
    lines: np.ndarray
    own_restore: np.ndarray
    section_out: tuple[np.ndarray, np.ndarray]
    secondary_out_end: np.ndarray
    effects: StormEffects


def county_effects(world: World, prm: Params, seed: int) -> np.ndarray:
    """Log work multiplier per section from its county's rebuild severity (transmission and pole damage,
    flooding, closed roads): one normal draw per county and seed, shared by every job in the county."""
    sigma = prm.f("process", "county_sigma")
    clip = prm.f("process", "county_z_max")
    draws = {
        f: sigma * float(np.clip(rng(seed, "wp17", "county", f).standard_normal(), -clip, clip))
        for f in sorted(set(world.fips.tolist()))
    }
    return np.array([draws[f] for f in world.fips.tolist()])


def section_work(world: World, prm: Params, effects: StormEffects, county_log: np.ndarray) -> np.ndarray:
    """Line-crew hours per failed section: Hazus hours x scale on a reference group of 6 line crews."""
    lines = prm.f("process", "reference_group_lines")
    scale = prm.f("process", "section_scale")
    w = np.maximum(world.min_repair_h, world.hazus_h * scale) * lines
    return np.where(world.failed, w * np.exp(effects.productivity_log + county_log), 0.0)


def secondary_jobs(
    world: World, prm: Params, effects: StormEffects, seed: int, county_log: np.ndarray
) -> Jobs:
    """Transformer and service-drop jobs behind each failed section (count, customers, work)."""
    rate = prm.f("process", "secondary_per_100") * np.exp(effects.secondary_log)
    sev = prm.arr("process", "secondary_severity")
    c_med = prm.f("process", "secondary_customers_median")
    c_sig = prm.f("process", "secondary_customers_sigma")
    share = prm.f("process", "secondary_max_share")
    w_med = prm.f("process", "secondary_work_median_h")
    w_sig = prm.f("process", "secondary_work_sigma")
    sec, cust, work = [], [], []
    for i in np.flatnonzero(world.failed):
        r = rng(seed, "wp17", "secondary", world.section_id[i])
        mean = rate * world.customers[i] / 100.0 * sev[max(int(world.ds[i]), 1) - 1]
        n = int(r.poisson(mean))
        if n == 0:
            continue
        k = np.maximum(1.0, np.round(r.lognormal(np.log(c_med), c_sig, n)))
        keep = np.cumsum(k) <= share * world.customers[i]
        k = k[keep]
        if len(k) == 0:
            continue
        w = r.lognormal(np.log(w_med), w_sig, len(k)) * np.exp(effects.productivity_log + county_log[i])
        sec += [i] * len(k)
        cust += k.tolist()
        work += w.tolist()
    s = np.asarray(sec, dtype=int)
    return Jobs(
        kind=np.full(len(s), SECONDARY, dtype=int),
        section=s,
        region=world.region[s],
        customers=np.asarray(cust, dtype=float),
        work=np.asarray(work, dtype=float),
        lat=world.lat[s],
        lon=world.lon[s],
    )


def all_jobs(world: World, prm: Params, effects: StormEffects, seed: int) -> Jobs:
    county_log = county_effects(world, prm, seed)
    failed = np.flatnonzero(world.failed)
    w = section_work(world, prm, effects, county_log)
    sec = secondary_jobs(world, prm, effects, seed, county_log)
    return Jobs(
        kind=np.concatenate([np.full(len(failed), SECTION, dtype=int), sec.kind]),
        section=np.concatenate([failed, sec.section]),
        region=np.concatenate([world.region[failed], sec.region]),
        customers=np.concatenate([world.weight[failed], sec.customers]),
        work=np.concatenate([w[failed], sec.work]),
        lat=np.concatenate([world.lat[failed], sec.lat]),
        lon=np.concatenate([world.lon[failed], sec.lon]),
    )


def crew_availability(world: World, effects: StormEffects, seed: int) -> np.ndarray:
    """Internal crews from their listed time; mutual-aid groups after a lognormal delay from the request."""
    avail = world.crew_available.copy()
    for k in np.flatnonzero(world.crew_mutual_aid):
        if effects.mutual_aid_delay_h is not None:
            delay = float(effects.mutual_aid_delay_h[k])
        else:
            r = rng(seed, "wp17", "mutual_aid", world.crew_id[k])
            delay = float(r.lognormal(np.log(world.mutual_aid_median_h), world.mutual_aid_sigma))
        avail[k] = world.request_t + delay * 3600.0
    return avail


def expected_section_work(prm: Params) -> np.ndarray:
    """Dispatcher's expectation of section work by damage state (Hazus means; slight..complete)."""
    fam = load_family("A")
    days = fam.arr("restoration.hazus_days_mean")
    return days * 24.0 * prm.f("process", "section_scale") * prm.f("process", "reference_group_lines")


def simulate(
    world: World,
    prm: Params | None = None,
    effects: StormEffects | None = None,
    seed: int | None = None,
) -> ProcessRun:
    prm = prm or default_params()
    seed = world.seed if seed is None else seed
    effects = effects or StormEffects()
    clock = DutyClock.from_params(prm)
    jobs = all_jobs(world, prm, effects, seed)
    n_jobs = len(jobs)
    lines_per = world.crew_headcount / prm.f("process", "persons_per_line_crew")
    avail = crew_availability(world, effects, seed)
    setup_h = prm.f("process", "setup_h")
    exp_sec = expected_section_work(prm)
    exp_2 = prm.f("process", "secondary_work_median_h") * np.exp(
        prm.f("process", "secondary_work_sigma") ** 2 / 2
    )

    n_sec = int(np.sum(jobs.kind == SECTION))
    release = np.full(n_jobs, np.inf)
    release[:n_sec] = world.work_ok[jobs.section[:n_sec]]
    expected = np.where(
        jobs.kind == SECTION,
        exp_sec[np.maximum(world.ds[jobs.section], 1) - 1],
        exp_2,
    )
    critical = (jobs.kind == SECTION) & world.critical[jobs.section]
    children: dict[int, list[int]] = {}
    for j in range(n_sec, n_jobs):
        children.setdefault(int(jobs.section[j]), []).append(j)
    feeder_members: dict[int, np.ndarray] = {}
    trunk_sections = np.flatnonzero(world.is_trunk & world.failed)
    for ts in trunk_sections:
        feeder_members[int(ts)] = np.flatnonzero(world.trunk_of == ts)

    own_restore = np.full(len(world.fault_t), np.nan)
    assigned = np.full(n_jobs, np.nan)
    arrive_at = np.full(n_jobs, np.nan)
    start = np.full(n_jobs, np.nan)
    end = np.full(n_jobs, np.nan)
    crew_of = np.full(n_jobs, -1, dtype=int)
    lines_of = np.full(n_jobs, np.nan)

    def eff_restore(s: int) -> float:
        own = own_restore[s] if world.failed[s] else -np.inf
        t = world.trunk_of[s]
        trunk = own_restore[t] if world.failed[t] else -np.inf
        return float(max(own, trunk))

    def on_section_done(s: int) -> None:
        affected = feeder_members.get(s, np.array([s]))
        for a in affected:
            a = int(a)
            if a not in children:
                continue
            if world.failed[a] and np.isnan(own_restore[a]):
                continue
            tr = int(world.trunk_of[a])
            if world.failed[tr] and np.isnan(own_restore[tr]):
                continue
            rel = eff_restore(a)
            for j in children[a]:
                release[j] = rel

    for reg in range(len(world.region_ids)):
        jidx = np.flatnonzero(jobs.region == reg)
        crews = np.flatnonzero(world.crew_region == reg)
        if len(jidx) == 0 or len(crews) == 0:
            continue
        open_mask = np.ones(len(jidx), dtype=bool)
        heap = [(float(avail[c]), int(c)) for c in crews]
        heapq.heapify(heap)
        pos_lat = {int(c): float(world.yard_lat[reg]) for c in crews}
        pos_lon = {int(c): float(world.yard_lon[reg]) for c in crews}
        busy_until = {int(c): float(avail[c]) for c in crews}
        jl, jo = jobs.lat[jidx], jobs.lon[jidx]
        jw, jc, je, jk = jobs.customers[jidx], critical[jidx], expected[jidx], jobs.kind[jidx]
        while heap and open_mask.any():
            t, k = heapq.heappop(heap)
            rel = release[jidx]
            ready = open_mask & (rel <= t)
            if not ready.any():
                waiting = rel[open_mask]
                finite = waiting[np.isfinite(waiting)]
                later = [b for kk, b in busy_until.items() if b > t and kk != k]
                cands = ([float(finite.min())] if len(finite) else []) + ([min(later)] if later else [])
                if not cands:
                    break
                heapq.heappush(heap, (max(min(cands), t + 60.0), k))
                continue
            cand = np.flatnonzero(ready)
            travel = distance_km(pos_lat[k], pos_lon[k], jl[cand], jo[cand]) / world.travel_kmh + setup_h
            lk = float(lines_per[k])
            wall = np.where(jk[cand] == SECTION, travel + je[cand] / lk, (travel + je[cand]) / lk)
            score = jw[cand] / wall + np.where(jc[cand], CRITICAL_BONUS, 0.0)
            b = int(cand[int(np.argmax(score))])
            j = int(jidx[b])
            tr = float(travel[int(np.argmax(score))])
            if jobs.kind[j] == SECTION:
                arrive = float(clock.finish(t, tr))
            else:
                arrive = float(clock.finish(t, tr / lk))
            s0 = max(arrive, float(release[j]))
            e = float(clock.finish(s0, jobs.work[j] / lk))
            arrive_at[j] = arrive
            assigned[j], start[j], end[j], crew_of[j], lines_of[j] = t, s0, e, k, lk
            open_mask[b] = False
            pos_lat[k], pos_lon[k] = float(jl[b]), float(jo[b])
            busy_until[k] = e
            heapq.heappush(heap, (e, k))
            if jobs.kind[j] == SECTION:
                s = int(jobs.section[j])
                own_restore[s] = e
                on_section_done(s)
    out_start, out_end = section_outage(world, own_restore)
    sec_mask = jobs.kind == SECONDARY
    sec_end = np.fmax(out_end[jobs.section[sec_mask]], end[sec_mask])
    return ProcessRun(
        world=world,
        jobs=jobs,
        release=release,
        assigned=assigned,
        arrive=arrive_at,
        start=start,
        end=end,
        crew=crew_of,
        lines=lines_of,
        own_restore=own_restore,
        section_out=(out_start, out_end),
        secondary_out_end=sec_end,
        effects=effects,
    )


def section_outage(world: World, own_restore: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Outage interval per section: from its own or its trunk's fault to the later of the two restores."""
    tf = world.fault_t[world.trunk_of]
    tr = np.where(np.isnan(tf), np.nan, own_restore[world.trunk_of])
    own_end = np.where(world.failed, own_restore, np.nan)
    out_start = np.fmin(world.fault_t, tf)
    out_end = np.fmax(own_end, tr)
    unrestored = ~np.isnan(out_start) & (
        (world.failed & np.isnan(own_restore)) | (~np.isnan(tf) & np.isnan(tr))
    )
    out_end = np.where(unrestored, np.inf, out_end)
    return out_start, out_end
