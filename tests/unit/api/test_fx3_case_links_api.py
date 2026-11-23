"""Through the real app: one decision one id on the Brief, the PS-17 chain on the case payload, a
Timing for every linked decision, and plain feed names on System health."""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from sgw.api.app import create_app
from sgw.api.settings import ApiSettings
from sgw.api.users import seed_users
from sgw.approval import testkit as tk
from sgw.common.sources import SOURCE_NAMES
from sgw.contracts.api_models import ExecutiveBrief, FeedHealthItem, ProposalCard
from sgw.contracts.vocab import NoRegretVerdict
from sgw.models.clocks.ps17 import (
    CASE_CREWS,
    CASE_FUEL,
    CASE_HOSPITAL,
    CASE_POWER,
    CASE_PRESSURE,
    ps17_specs,
)
from sgw.models.clocks.service import compute_queue
from sgw.models.clocks.store import save_queue

PASSWORD = "fx3-" + secrets.token_hex(12)
CREWS_PROPOSAL = "PRP-CREW-AIK-0926A"
POWER_PROPOSAL = "PRP-FX3-PS17-POWER"
BEFORE_ALL = "2024-09-25T12:00:00Z"
INPUTS = json.loads(
    (Path(__file__).parents[1] / "models" / "clocks" / "data" / "wp06_helene_ps17_members.json").read_text(
        "utf-8"
    )
)
NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
INTERNAL_ID = re.compile(r"\b(PRP|DC)-[A-Z0-9-]+")


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: R24 case links need Postgres
    from sgw.approval.seed import run_seed

    with tk.scratch_database("sgw_fx3_t") as url:
        run_seed(url, use_default_ledger=False)
        seed_users(url, PASSWORD)
        with psycopg.connect(url, autocommit=True) as conn:
            save_queue(conn, compute_queue(ps17_specs(INPUTS["advisories"]["N"], INPUTS)))
            columns = [
                r[0]
                for r in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'proposal'"
                    " AND column_name NOT IN ('proposal_id', 'decision_case_id', 'created_at')"
                    " AND is_generated = 'NEVER' ORDER BY ordinal_position"
                ).fetchall()
            ]
            listed = ", ".join(columns)
            conn.execute(
                f"INSERT INTO proposal (proposal_id, decision_case_id, created_at, {listed})"  # noqa: S608
                f" SELECT %s, %s, created_at + interval '1 minute', {listed} FROM proposal"
                " WHERE proposal_id = %s",
                (POWER_PROPOSAL, CASE_POWER, CREWS_PROPOSAL),
            )
            conn.execute(
                "INSERT INTO adapter_health"
                " (source_id, feed_mode, ingest_lag_s, product_age_s, freshness_limit_s) VALUES"
                " ('ami-headend', 'synthetic', 90, 90, 300), ('fsm-crews', 'synthetic', 300, 300, 900),"
                " ('lims', 'synthetic', 3600, 3600, 86400), ('odd_new-feed', 'synthetic', 30, 30, 120)"
            )
        yield url


@pytest.fixture(scope="module")
def client(db_url: str) -> Iterator[TestClient]:
    settings = ApiSettings(
        database_url=db_url, demo_mode=True, cookie_secure=False, login_ip_burst=1000, login_user_burst=1000
    )
    with TestClient(create_app(settings)) as c:
        yield c


def login(c: TestClient, user_id: str) -> dict[str, str]:
    r = c.post("/api/auth/login", json={"user_id": user_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": c.cookies["sgw_csrf"]}


def seek(c: TestClient, at: str) -> None:
    csrf = login(c, "ic_01")
    assert c.post("/api/scenario", json={"action": "pause"}, headers=csrf).status_code == 200
    r = c.post("/api/scenario", json={"action": "seek", "scenario_time": at}, headers=csrf)
    assert r.status_code == 200, r.text


def card(c: TestClient, proposal_id: str) -> ProposalCard:
    r = c.get(f"/api/proposals/{proposal_id}")
    assert r.status_code == 200, r.text
    return ProposalCard.model_validate(r.json())


def test_the_ps17_case_payload_carries_its_chain_and_links(client: TestClient) -> None:
    seek(client, BEFORE_ALL)
    login(client, "ops_dm_01")
    power = card(client, POWER_PROPOSAL).case
    assert power.prerequisite_ids == power.blocked_by == sorted([CASE_CREWS, CASE_FUEL])
    assert power.blocks == [CASE_PRESSURE]
    order = [s.decision_case_id for s in power.chain or []]
    assert sorted(order) == sorted([CASE_CREWS, CASE_FUEL, CASE_POWER, CASE_PRESSURE, CASE_HOSPITAL])
    assert order[-3:] == [CASE_POWER, CASE_PRESSURE, CASE_HOSPITAL]
    assert power.chain_order == order.index(CASE_POWER) + 1
    proposals = {s.decision_case_id: s.proposal_id for s in power.chain or []}
    assert (proposals[CASE_CREWS], proposals[CASE_POWER], proposals[CASE_FUEL]) == (
        CREWS_PROPOSAL,
        POWER_PROPOSAL,
        None,
    )
    crews = card(client, CREWS_PROPOSAL).case
    assert (crews.blocked_by, crews.blocks) == ([], [CASE_POWER])
    assert [s.decision_case_id for s in crews.chain or []] == order


def test_every_linked_decision_has_a_timing(client: TestClient) -> None:
    seek(client, BEFORE_ALL)
    login(client, "ops_dm_01")
    power = card(client, POWER_PROPOSAL).case
    crews = card(client, CREWS_PROPOSAL).case
    assert power.no_regret_verdict is not NoRegretVerdict.NOT_APPLICABLE
    assert (power.timing, power.timing_reason) == (power.no_regret_verdict, None)
    assert crews.no_regret_verdict is NoRegretVerdict.NOT_APPLICABLE, "the stored verdict is unchanged"
    assert crews.timing is power.no_regret_verdict
    assert crews.timing_reason and power.title in crews.timing_reason
    assert not INTERNAL_ID.search(crews.timing_reason)


def test_the_brief_lead_is_plain_and_open_decisions_carry_their_case_id(client: TestClient) -> None:
    seek(client, BEFORE_ALL)
    login(client, "exec_01")
    doc = ExecutiveBrief.model_validate(client.get("/api/brief").json())
    open_ids = {p.proposal_id: p.decision_case_id for p in doc.open_t3}
    assert open_ids == {CREWS_PROPOSAL: CASE_CREWS, POWER_PROPOSAL: CASE_POWER}
    if doc.status_word in ("Emergency", "Warning", "Watch") and "decision" in doc.status_basis:
        assert re.match(r"^(One|Two) decisions? needs? two teams to sign", doc.status_basis), doc.status_basis
    for text in (doc.status_basis, *(f.sentence for f in doc.functions)):
        assert not INTERNAL_ID.search(text), text
        assert "T3" not in text, text
    command = next(f.sentence for f in doc.functions if f.function.value == "command")
    assert re.search(r"\d\d:\d\d ET \(\d\d:\d\dZ\)", command), command
    for n in doc.numbers:
        assert "/" not in n.provenance.source and ".jsonl" not in n.provenance.source, n.provenance.source


def test_brief_lead_sentence_counts_and_names_the_first_decision() -> None:
    from sgw.api.readmodels.brief import lead_sentence
    from sgw.contracts.api_models import ProposalSummary
    from sgw.contracts.vocab import ApprovalFunction

    def summary(title: str) -> ProposalSummary:
        return ProposalSummary.model_construct(
            title=title, functions_required=[ApprovalFunction.OPERATIONS, ApprovalFunction.WATER_OPERATIONS]
        )

    first, second = summary("Hook up the portable generator at PS-17"), summary("Pre-position crews")
    assert lead_sentence([first], first) == (
        "One decision needs two teams to sign: Hook up the portable generator at PS-17."
    )
    assert lead_sentence([first, second], first) == (
        "Two decisions need two teams to sign; the most urgent: Hook up the portable generator at PS-17."
    )


def test_feed_health_has_plain_names_from_the_registry(client: TestClient) -> None:
    login(client, "ops_dm_01")
    r = client.get("/api/feeds/health")
    assert r.status_code == 200, r.text
    names = {f.source_id: f.display_name for f in (FeedHealthItem.model_validate(x) for x in r.json())}
    assert names["ami-headend"] == SOURCE_NAMES["ami-headend"] == "Smart meters"
    assert names["fsm-crews"] == "Crew tracking"
    assert names["lims"] == "Lab results"
    assert names["odd_new-feed"] == "Odd new feed"
