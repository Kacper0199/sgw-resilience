"""SQL for proposals, approvals and execution tokens (K1 tables from migration 0005). Parameterised only."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

Row = dict[str, Any]

RISK_ORDER = ("very_low", "low", "moderate", "high", "very_high")

PROPOSAL_COLUMNS = """
    p.proposal_id, p.decision_case_id, p.incident_id, p.action_type, p.params, p.targets, p.risk_band,
    p.preconditions, p.tier, p.required_functions::text[] AS required_functions, p.escalators, p.state,
    p.proposal_version, p.action_hash, p.policy_version, p.snapshot_id, p.evidence_ids, p.initiator_kind,
    p.proposed_by, p.run_id, p.region_id, p.domain, p.rationale, p.expires_at, p.created_at, p.updated_at
"""

CASE_COLUMNS = """
    c.decision_case_id AS c_id, c.step AS c_step, c.title AS c_title, c.region_id AS c_region_id,
    c.domain AS c_domain, c.clock_kind AS c_clock_kind, c.consequence_utc AS c_consequence_utc,
    c.consequence_p10_utc AS c_consequence_p10_utc, c.consequence_p90_utc AS c_consequence_p90_utc,
    c.consequence_basis AS c_consequence_basis, c.action_lead_time_min AS c_action_lead_time_min,
    c.lead_time_basis AS c_lead_time_basis, c.decide_by_utc AS c_decide_by_utc,
    c.decide_by_p10_utc AS c_decide_by_p10_utc, c.decide_by_p90_utc AS c_decide_by_p90_utc,
    c.effective_decide_by_utc AS c_effective_decide_by_utc, c.on_critical_path AS c_on_critical_path,
    c.no_regret_share_ppm AS c_no_regret_share_ppm, c.no_regret_verdict AS c_no_regret_verdict,
    c.next_advisory_utc AS c_next_advisory_utc, c.if_late AS c_if_late
"""

PROPOSER_COLUMNS = "u.display_name AS u_display_name, u.function::text AS u_function"
PROPOSER_JOIN = "LEFT JOIN app_user u ON u.user_id = p.proposed_by"


def _one(conn: psycopg.Connection[Any], query: str, params: Sequence[Any] | dict[str, Any]) -> Row | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return cur.fetchone()


def _all(conn: psycopg.Connection[Any], query: str, params: Sequence[Any] | dict[str, Any]) -> list[Row]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def load_user(conn: psycopg.Connection[Any], user_id: str) -> Row | None:
    return _one(
        conn,
        "SELECT user_id, functions::text[] AS functions, can_approve, break_glass_eligible, on_shift"
        " FROM app_user WHERE user_id = %s",
        (user_id,),
    )


def load_case(conn: psycopg.Connection[Any], case_id: str) -> Row | None:
    return _one(conn, f"SELECT {CASE_COLUMNS} FROM decision_case c WHERE c.decision_case_id = %s", (case_id,))  # noqa: S608


CASE_GRAPH = """
SELECT c.decision_case_id, c.title, c.effective_decide_by_utc, c.on_critical_path, c.no_regret_verdict,
       c.next_advisory_utc, s.verdict_basis_utc, s.effective_decide_by_p10_utc,
       ARRAY(SELECT d.prerequisite_id FROM decision_dependency d
             WHERE d.decision_case_id = c.decision_case_id ORDER BY d.prerequisite_id) AS prerequisite_ids,
       (SELECT p.proposal_id FROM proposal p WHERE p.decision_case_id = c.decision_case_id
        ORDER BY p.created_at DESC, p.proposal_id DESC LIMIT 1) AS proposal_id
FROM decision_case c LEFT JOIN clock_case_state s USING (decision_case_id) ORDER BY c.decision_case_id
"""


def case_graph(conn: psycopg.Connection[Any]) -> list[Row]:
    """Every stored case with its prerequisite edges and latest proposal: the input of the case links."""
    return _all(conn, CASE_GRAPH, ())


def degraded_mode(conn: psycopg.Connection[Any]) -> str:
    row = _one(conn, "SELECT degraded_mode FROM control_state WHERE id = 1", ())
    return str(row["degraded_mode"]) if row else "M0"


def unknown_targets(conn: psycopg.Connection[Any], target_ids: Sequence[str]) -> list[str]:
    rows = _all(
        conn,
        "SELECT t AS target FROM unnest(%s::text[]) AS t"
        " WHERE NOT EXISTS (SELECT 1 FROM asset a WHERE a.asset_id = t)"
        " AND NOT EXISTS (SELECT 1 FROM crew c WHERE c.crew_id = t)",
        (list(target_ids),),
    )
    return sorted(str(r["target"]) for r in rows)


def target_facts(conn: psycopg.Connection[Any], target_ids: Sequence[str]) -> Row:
    """Escalation facts from reference data, failing closed: an asset without `attributes.customers_source`
    has an unknown customer count, and any target without `attributes.in_hazard_zone = false` (crews have
    no zone data yet) counts as entering the hazard zone."""
    row = _one(
        conn,
        "SELECT coalesce(sum(a.customers_served) FILTER (WHERE a.attributes ? 'customers_source'), 0)::bigint"
        " AS customers,"
        " count(*) FILTER (WHERE NOT a.attributes ? 'customers_source') AS customers_unknown,"
        " coalesce(bool_or(a.critical_facility), false) AS critical,"
        " count(*) FILTER (WHERE coalesce((a.attributes ->> 'in_hazard_zone')::boolean, true)) AS in_zone"
        " FROM asset a WHERE a.asset_id = ANY(%(ids)s)",
        {"ids": list(target_ids)},
    )
    crews = _one(conn, "SELECT count(*) AS n FROM crew WHERE crew_id = ANY(%s)", (list(target_ids),))
    facts = row or {"customers": 0, "customers_unknown": 0, "critical": False, "in_zone": 0}
    facts["in_zone"] = int(facts["in_zone"]) + int(crews["n"] if crews else 0)
    return facts


def max_risk_band(conn: psycopg.Connection[Any], target_ids: Sequence[str]) -> str | None:
    rows = _all(
        conn,
        "SELECT DISTINCT r.band FROM risk r JOIN snapshot s USING (snapshot_id)"
        " WHERE r.entity_id = ANY(%s)"
        " AND s.as_of = (SELECT max(s2.as_of) FROM snapshot s2 JOIN risk r2 USING (snapshot_id)"
        " WHERE r2.entity_id = ANY(%s))",
        (list(target_ids), list(target_ids)),
    )
    bands = [str(r["band"]) for r in rows if r["band"] in RISK_ORDER]
    return max(bands, key=RISK_ORDER.index) if bands else None


def insert_proposal(conn: psycopg.Connection[Any], row: Row) -> None:
    conn.execute(
        "INSERT INTO proposal (proposal_id, decision_case_id, incident_id, action_type, params, targets,"
        " risk_band, preconditions, tier, required_functions, escalators, state, proposal_version,"
        " action_hash, policy_version, snapshot_id, evidence_ids, initiator_kind, proposed_by, run_id,"
        " region_id, domain,"
        " rationale, expires_at) VALUES (%(proposal_id)s, %(decision_case_id)s, %(incident_id)s,"
        " %(action_type)s, %(params)s, %(targets)s, %(risk_band)s, %(preconditions)s, %(tier)s,"
        " %(required_functions)s::sgw_approval_function[], %(escalators)s, %(state)s, %(proposal_version)s,"
        " %(action_hash)s, %(policy_version)s, %(snapshot_id)s, %(evidence_ids)s, %(initiator_kind)s,"
        " %(proposed_by)s, %(run_id)s, %(region_id)s, %(domain)s, %(rationale)s, %(expires_at)s)",
        {**row, "params": Jsonb(row["params"]), "preconditions": Jsonb(row["preconditions"])},
    )


def lock_proposal(conn: psycopg.Connection[Any], proposal_id: str) -> Row | None:
    return _one(
        conn,
        f"SELECT {PROPOSAL_COLUMNS} FROM proposal p WHERE p.proposal_id = %s FOR UPDATE",  # noqa: S608
        (proposal_id,),
    )


def get_proposal(conn: psycopg.Connection[Any], proposal_id: str) -> Row | None:
    return _one(
        conn,
        f"SELECT {PROPOSAL_COLUMNS}, {CASE_COLUMNS}, {PROPOSER_COLUMNS} FROM proposal p"  # noqa: S608
        f" JOIN decision_case c USING (decision_case_id) {PROPOSER_JOIN} WHERE p.proposal_id = %s",
        (proposal_id,),
    )


KNOWN_BY = (
    "(%(known_by)s::timestamptz IS NULL OR NOT p.params ? 'known_at_utc'"
    " OR (p.params ->> 'known_at_utc')::timestamptz <= %(known_by)s::timestamptz)"
)
LATEST_OF_RULE = (
    "(NOT p.params ? 'rule_key' OR NOT EXISTS (SELECT 1 FROM proposal q"
    " WHERE q.params ->> 'rule_key' = p.params ->> 'rule_key' AND q.created_at > p.created_at))"
)
LATEST_OF_CASE = (
    "NOT EXISTS (SELECT 1 FROM proposal q WHERE q.decision_case_id = p.decision_case_id"
    " AND q.action_type = p.action_type AND (q.created_at, q.proposal_id) > (p.created_at, p.proposal_id)"
    " AND q.state NOT IN ('withdrawn', 'rejected')"
    " AND (%(known_by)s::timestamptz IS NULL OR NOT q.params ? 'known_at_utc'"
    " OR (q.params ->> 'known_at_utc')::timestamptz <= %(known_by)s::timestamptz))"
)


def list_proposals(
    conn: psycopg.Connection[Any], states: Sequence[str] | None, known_by: datetime | None = None
) -> list[Row]:
    """Proposals in `states` (all when None); with `known_by`, a rule proposal that carries `known_at_utc`
    is listed only once its facts are known at that scenario time (a jump back hides later ones). A rule
    proposal raised again after it expired (same `rule_key`) replaces the earlier one in the list, and so
    does any later proposal of the same decision case and action that was not withdrawn or rejected: every
    queue view shows one row per case and action, the latest."""
    return _all(
        conn,
        f"SELECT {PROPOSAL_COLUMNS}, {CASE_COLUMNS}, {PROPOSER_COLUMNS} FROM proposal p"  # noqa: S608
        f" JOIN decision_case c USING (decision_case_id) {PROPOSER_JOIN}"
        " WHERE (%(states)s::text[] IS NULL OR p.state = ANY(%(states)s::text[]))"
        f" AND {KNOWN_BY} AND {LATEST_OF_RULE} AND {LATEST_OF_CASE}"
        " ORDER BY c.effective_decide_by_utc, p.proposal_id",
        {"states": list(states) if states else None, "known_by": known_by},
    )


def current_approvals(conn: psycopg.Connection[Any], proposal_ids: Sequence[str]) -> list[Row]:
    return _all(
        conn,
        "SELECT a.approval_id, a.proposal_id, a.approver_id, a.function, a.decision, a.created_at,"
        " COALESCE((SELECT e.occurred_at FROM audit_event e"
        " WHERE e.event_key = 'approval_recorded:' || a.approval_id), a.created_at) AS signed_at"
        " FROM approval a JOIN proposal p USING (proposal_id)"
        " WHERE a.proposal_id = ANY(%s) AND a.proposal_version = p.proposal_version"
        " AND a.action_hash = p.action_hash AND a.voided_at IS NULL ORDER BY a.created_at, a.approval_id",
        (list(proposal_ids),),
    )


def open_proposals_for(
    conn: psycopg.Connection[Any], decision_case_id: str, action_type: str, states: Sequence[str]
) -> list[Row]:
    """Undecided agent or system proposals of one case and action, oldest first, each with the scenario
    time it was proposed at (its `proposal_created` audit record)."""
    return _all(
        conn,
        "SELECT p.proposal_id, (SELECT e.occurred_at FROM audit_event e WHERE e.kind = 'proposal_created'"
        " AND e.subject = p.proposal_id ORDER BY e.seq LIMIT 1) AS proposed_at"
        " FROM proposal p WHERE p.decision_case_id = %s AND p.action_type = %s AND p.state = ANY(%s)"
        " AND p.initiator_kind <> 'person' ORDER BY p.created_at, p.proposal_id",
        (decision_case_id, action_type, list(states)),
    )


def voided_approvals(conn: psycopg.Connection[Any], proposal_id: str) -> list[Row]:
    """Signatures a later material version voided (the version rule), oldest first, with the reason of the
    version that voided them."""
    return _all(
        conn,
        "SELECT a.approval_id, a.approver_id, a.function, a.decision,"
        " COALESCE((SELECT e.occurred_at FROM audit_event e"
        " WHERE e.event_key = 'approval_recorded:' || a.approval_id), a.created_at) AS created_at,"
        " a.proposal_version,"
        " a.voided_at, a.voided_by_version, d.change ->> 'reason' AS voided_reason"
        " FROM approval a LEFT JOIN LATERAL (SELECT change FROM proposal_delta"
        " WHERE proposal_id = a.proposal_id AND version = a.voided_by_version AND material"
        " ORDER BY seq DESC LIMIT 1) d ON true"
        " WHERE a.proposal_id = %s AND a.voided_at IS NOT NULL ORDER BY a.created_at, a.approval_id",
        (proposal_id,),
    )


def version_reason(conn: psycopg.Connection[Any], proposal_id: str, version: int) -> str | None:
    row = _one(
        conn,
        "SELECT change ->> 'reason' AS reason FROM proposal_delta WHERE proposal_id = %s AND version = %s"
        " AND material AND change ? 'reason' ORDER BY seq DESC LIMIT 1",
        (proposal_id, version),
    )
    return None if row is None or row["reason"] is None else str(row["reason"])


def insert_approval(conn: psycopg.Connection[Any], row: Row) -> None:
    conn.execute(
        "INSERT INTO approval (approval_id, proposal_id, proposal_version, action_hash, approver_id,"
        " function, decision, reason_code, note, snapshot_id_seen, evidence_oldest_age_s) VALUES"
        " (%(approval_id)s, %(proposal_id)s, %(proposal_version)s, %(action_hash)s, %(approver_id)s,"
        " %(function)s, %(decision)s, %(reason_code)s, %(note)s, %(snapshot_id_seen)s,"
        " %(evidence_oldest_age_s)s)",
        row,
    )


def delete_approval(conn: psycopg.Connection[Any], approval_id: str, approver_id: str) -> None:
    """An approver withdraws their own live signature on an open proposal: the row goes (the unique keys on
    (proposal, version, function) would otherwise block a colleague of the same function); the withdrawal
    is kept in `proposal_delta` and the ledger. Runs through the 4800 definer function."""
    conn.execute("SELECT authority_withdraw_approval(%s, %s)", (approval_id, approver_id))


def set_state(conn: psycopg.Connection[Any], proposal_id: str, state: str) -> None:
    conn.execute("SELECT authority_set_state(%s, %s)", (proposal_id, state))


def update_material(conn: psycopg.Connection[Any], row: Row, expected_version: int) -> None:
    """A revision through the 4800 definer function; the proposal guard re-derives tier and functions."""
    fields = {k: v for k, v in row.items() if k != "proposal_id"}
    if isinstance(fields.get("expires_at"), datetime):
        fields["expires_at"] = fields["expires_at"].isoformat()
    conn.execute("SELECT authority_revise(%s, %s, %s)", (row["proposal_id"], expected_version, Jsonb(fields)))


def set_rationale(conn: psycopg.Connection[Any], proposal_id: str, rationale: str) -> None:
    conn.execute("SELECT authority_set_rationale(%s, %s)", (proposal_id, rationale))


def void_approvals(conn: psycopg.Connection[Any], proposal_id: str, new_version: int) -> list[str]:
    rows = _all(
        conn,
        "SELECT approval_id FROM authority_void_approvals(%s, %s) AS approval_id",
        (proposal_id, new_version),
    )
    return sorted(str(r["approval_id"]) for r in rows)


def add_delta(
    conn: psycopg.Connection[Any], proposal_id: str, version: int, material: bool, change: dict[str, Any]
) -> None:
    conn.execute(
        "INSERT INTO proposal_delta (proposal_id, version, seq, material, change)"
        " SELECT %(pid)s, %(v)s, coalesce(max(seq), 0) + 1, %(m)s, %(c)s FROM proposal_delta"
        " WHERE proposal_id = %(pid)s AND version = %(v)s",
        {"pid": proposal_id, "v": version, "m": material, "c": Jsonb(change)},
    )


def changed_fields_since(conn: psycopg.Connection[Any], proposal_id: str, seen_version: int) -> list[str]:
    rows = _all(
        conn,
        "SELECT DISTINCT jsonb_array_elements_text(change -> 'fields') AS field FROM proposal_delta"
        " WHERE proposal_id = %s AND version > %s AND material AND change ? 'fields'",
        (proposal_id, seen_version),
    )
    return sorted(str(r["field"]) for r in rows)


def retracted_evidence(conn: psycopg.Connection[Any], proposal_id: str) -> list[str]:
    rows = _all(
        conn,
        "SELECT DISTINCT jsonb_array_elements_text(change -> 'retracted_evidence_ids') AS id"
        " FROM proposal_delta WHERE proposal_id = %s AND material AND change ? 'retracted_evidence_ids'",
        (proposal_id,),
    )
    return sorted(str(r["id"]) for r in rows)


def envelope_for(conn: psycopg.Connection[Any], proposal_id: str) -> Row | None:
    return _one(
        conn,
        "SELECT envelope_id, proposal_id, bounds, valid_until FROM envelope WHERE proposal_id = %s",
        (proposal_id,),
    )


def break_glass_for(conn: psycopg.Connection[Any], proposal_id: str) -> Row | None:
    return _one(
        conn,
        "SELECT proposal_id, ic_id, reason, used_at, cosign_due, cosigned_by, cosigned_at, flagged"
        " FROM break_glass WHERE proposal_id = %s ORDER BY break_glass_id DESC LIMIT 1",
        (proposal_id,),
    )


def drop_unburned_token(conn: psycopg.Connection[Any], proposal_id: str) -> None:
    conn.execute("SELECT authority_drop_unburned_token(%s)", (proposal_id,))


def insert_token(
    conn: psycopg.Connection[Any], proposal_id: str, version: int, action_hash: str, expires_at: datetime
) -> str:
    row = _one(
        conn,
        "INSERT INTO execution_token (proposal_id, proposal_version, action_hash, expires_at)"
        " VALUES (%s, %s, %s, %s) RETURNING token_id::text AS token_id",
        (proposal_id, version, action_hash, expires_at),
    )
    assert row is not None
    return str(row["token_id"])


def bound_by_case(conn: psycopg.Connection[Any], decision_case_id: str) -> str | None:
    """The dependent case that binds this case's effective decide-by (P50), from the stored clock queue."""
    row = _one(
        conn,
        "SELECT bound_by_case_id FROM clock_case_state WHERE decision_case_id = %s",
        (decision_case_id,),
    )
    return None if row is None else row["bound_by_case_id"]


def token_for(conn: psycopg.Connection[Any], proposal_id: str) -> Row | None:
    return _one(
        conn,
        "SELECT token_id::text AS token_id, proposal_id, proposal_version, action_hash, expires_at,"
        " burned_at"
        " FROM execution_token WHERE proposal_id = %s",
        (proposal_id,),
    )


def burn_token(conn: psycopg.Connection[Any], params: dict[str, Any]) -> bool:
    """Burn once through the 4800 definer function: approved, current version and hash, unexpired, and
    signed by every required function (or a bound break-glass)."""
    row = _one(
        conn,
        "SELECT authority_burn_token(%(token_id)s::uuid, %(proposal_id)s, %(version)s, %(action_hash)s,"
        " %(now)s) AS token_id",
        params,
    )
    return row is not None and row["token_id"] is not None


def insert_effect(
    conn: psycopg.Connection[Any], effect_id: str, proposal_id: str, channel: str, token_id: str
) -> None:
    """One effect per burned token (4801: unique token_id)."""
    conn.execute(
        "INSERT INTO effect (effect_id, proposal_id, channel, token_id) VALUES (%s, %s, %s, %s::uuid)"
        " ON CONFLICT (effect_id) DO NOTHING",
        (effect_id, proposal_id, channel, token_id),
    )


def expire_due(conn: psycopg.Connection[Any], now: datetime) -> list[str]:
    rows = _all(
        conn,
        "SELECT proposal_id FROM authority_expire_due(%s) AS proposal_id",
        (now,),
    )
    return sorted(str(r["proposal_id"]) for r in rows)
