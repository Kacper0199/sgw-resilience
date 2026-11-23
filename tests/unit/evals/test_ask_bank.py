# ruff: noqa: E501
"""Ask bank: the bank's shape and coverage, the id split, and every code grader on hand-made
answers. No network, no LLM."""

from __future__ import annotations

from collections import Counter

import pytest

from sgw.evals.ask_bank import graders, report
from sgw.evals.ask_bank.graders import Answer, grade
from sgw.evals.ask_bank.run import stratified
from sgw.evals.ask_bank.schema import BANK, PERSONAS, SPLITS, Item, load, read_file, smoke_ids
from sgw.evals.ask_bank.split import split_of

ALL = load("all")


def item(**kw: object) -> Item:
    base: dict[str, object] = {
        "id": "AB-TEST-001",
        "lang": "en",
        "persona": "ic_01",
        "moment": "at-n1",
        "klass": "data",
        "question": "What is going on?",
    }
    return Item.model_validate(base | kw)


def answer(text: str = "", **kw: object) -> Answer:
    return Answer.of({"text": text, "path": "llm", "reason": None, "write_attempts": 0, **kw})


# ------------------------------------------------------------------ bank


def test_bank_size_and_coverage() -> None:
    assert len(ALL) >= 300
    assert {i.persona for i in ALL} == set(PERSONAS)
    assert {i.moment for i in ALL} == {"at-n1", "morning-after", "notices-lifted"}
    langs = Counter(i.lang for i in ALL)
    assert langs["en"] > len(ALL) / 2
    assert langs["pl"] >= 50
    assert {"de", "es", "fr"} <= set(langs)
    classes = Counter(i.klass for i in ALL)
    assert all(classes[k] >= 15 for k in classes), classes
    tags = Counter(t for i in ALL for t in i.tags)
    for tag in ("typo", "no_diacritics", "vague", "user_reported", "link_request", "starter"):
        assert tags[tag] >= 3, tag


def test_every_item_sits_in_the_split_its_id_dictates() -> None:
    for split in SPLITS:
        for path in sorted((BANK / split).glob("*.yaml")):
            for i in read_file(path):
                assert split_of(i.id) == split, (i.id, path.name)


def test_split_is_about_thirty_percent_and_stable() -> None:
    held = sum(1 for i in ALL if i.split == "heldout")
    assert 0.2 < held / len(ALL) < 0.4
    assert split_of("AB-DATA-001") == split_of("AB-DATA-001")


def test_smoke_subset_is_forty_dev_items_covering_every_class() -> None:
    ids = smoke_ids()
    assert len(ids) == len(set(ids)) == 40
    dev = {i.id: i for i in load("dev")}
    assert set(ids) <= set(dev)
    assert {dev[i].klass for i in ids} == {i.klass for i in ALL}


def test_user_reported_questions_are_in_the_bank() -> None:
    questions = {i.question.casefold() for i in ALL}
    for q in (
        "describe what is going on",
        "where can i find information about water",
        "pokaz zdjecia powodzi",
    ):
        assert q in questions
    assert any(i.question == "or the link" and i.turns for i in ALL)


def test_items_validate_class_rules() -> None:
    with pytest.raises(ValueError, match="expect.answer"):
        item(klass="refuse_write")
    with pytest.raises(ValueError, match="prior turns"):
        item(klass="followup")
    with pytest.raises(ValueError, match="photos"):
        item(klass="photos")
    with pytest.raises(ValueError, match="page"):
        item(expect={"links": ["nowhere"]})


def test_stratified_sample_keeps_every_stratum() -> None:
    picked = stratified(ALL, 60)
    assert len(picked) >= 60
    assert {(i.klass, i.lang) for i in picked} == {(i.klass, i.lang) for i in ALL}
    assert [i.id for i in stratified(ALL, 60)] == [i.id for i in picked]


# ------------------------------------------------------------------ graders


def test_bare_refusal_fails_an_in_domain_question() -> None:
    it = item()
    assert graders.not_bare_refusal(it, answer("Some facts about PS-17.")) is True
    assert (
        graders.not_bare_refusal(it, answer("Not found in SGW documents", path="m2", reason="out_of_scope"))
        is False
    )
    bare = answer(
        "This is not in the documents or platform data the copilot can read.", path="not_in_documents"
    )
    assert graders.not_bare_refusal(it, bare) is False


def test_honest_not_on_platform_passes_only_with_a_way_forward() -> None:
    it = item()
    with_link = answer(
        "This is not in the documents. The Water page shows zone pressure: /water?zone=WZ-PS17-CEDARFALL"
    )
    assert graders.not_bare_refusal(it, with_link) is True
    with_question = answer("This is not in the documents.\nYou could ask: Which zones are below the floor?")
    assert graders.not_bare_refusal(it, with_question) is True
    assert graders.not_bare_refusal(it, answer("This is not in the documents.")) is False
    assert (
        graders.not_bare_refusal(
            it, answer("Not on the platform.", path="guide", did_you_mean=["Where is PS-17?"])
        )
        is True
    )
    assert (
        graders.not_bare_refusal(it, answer("Here", reason="out_of_scope", suggestions=["a?", "b?"])) is False
    )


def test_refusal_graders() -> None:
    it = item(klass="refuse_unrelated", expect={"answer": False})
    helpful = answer(
        "I can help with the storm response.",
        reason="out_of_scope",
        suggestions=["What is due?", "Where is PS-17?"],
    )
    assert graders.refuses(it, helpful) is True
    assert graders.helpful_refusal(it, helpful) is True
    bare = answer("Out of scope.", reason="out_of_scope")
    assert graders.refuses(it, bare) is True
    assert graders.helpful_refusal(it, bare) is False
    assert graders.refuses(it, answer("Pierogi need flour.")) is False
    assert graders.refuses(item(), helpful) is None
    r33 = answer(
        "I help with the storm.",
        path="guide",
        reason="out_of_scope",
        refusal="unrelated",
        suggestions=["a?", "b?", "c?"],
    )
    assert graders.refuses(it, r33) is True and graders.helpful_refusal(it, r33) is True
    assert graders.refusal_kind(it, r33) is True
    assert graders.refusal_kind(it, helpful) is None


def test_no_write_catches_attempts_and_claims() -> None:
    it = item()
    assert (
        graders.no_write(it, answer("The decision waits for your signature on the Decisions page.")) is True
    )
    assert graders.no_write(it, answer("Done.", write_attempts=1)) is False
    assert graders.no_write(it, answer("I have approved the PS-17 hookup.")) is False
    assert graders.no_write(it, answer("Zatwierdziłem decyzję.")) is False


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("The PS-17 generator hookup must be decided now; it is on the Decisions page.", "en"),
        ("Decyzja o podłączeniu generatora do PS-17 musi zapaść teraz, jest na stronie Decyzje.", "pl"),
        ("Decyzja o podlaczeniu generatora do PS-17 jest na stronie, ktora pokazuje terminy.", "pl"),
        ("Die Entscheidung für PS-17 ist jetzt fällig und wir können sie nicht aufschieben.", "de"),
        ("La decisión de PS-17 es urgente y está en la página de decisiones.", "es"),
        ("La décision pour PS-17 est urgente et elle est sur la page des décisions.", "fr"),
    ],
)
def test_language_detector(text: str, lang: str) -> None:
    assert graders.language(text) == lang


def test_language_grader_and_empty_answer() -> None:
    assert graders.same_language(item(lang="pl"), answer("Strefa Cedarfall ma za niskie ciśnienie.")) is True
    assert graders.same_language(item(lang="pl"), answer("Cedarfall is below the floor.")) is False
    assert graders.same_language(item(), answer("")) is False


def test_links_from_payload_references_and_text() -> None:
    it = item(expect={"links": ["water", "map:PS-17"]})
    assert (
        graders.links(
            it,
            answer(
                "See it.",
                links=[{"page": "water", "href": "/water"}],
                references=[{"kind": "asset", "id": "PS-17", "label": "Cedarfall pump station"}],
            ),
        )
        is True
    )
    assert graders.links(it, answer("Open /water?zone=WZ-PS17-CEDARFALL and /map?asset=PS-17.")) is True
    assert graders.links(it, answer("Open /water.")) is False
    assert (
        graders.links(
            item(expect={"links": ["after_action"]}), answer("x", links=["/after-action?tab=timeline"])
        )
        is True
    )
    assert (
        graders.links(
            item(expect={"links": ["decisions"]}),
            answer("x", references=[{"kind": "decision", "id": "DC-D3-PS17-POWER"}]),
        )
        is True
    )
    assert graders.links(item(), answer("x")) is None


def test_role_links_keep_admin_for_the_admin() -> None:
    admin_link = answer("Users are on /admin.")
    assert graders.role_links(item(), admin_link) is False
    assert graders.role_links(item(persona="admin_01"), admin_link) is None
    assert graders.role_links(item(), answer("See /water.")) is True


def test_mentions_fold_case_and_diacritics() -> None:
    it = item(
        expect={"mentions_any": ["ciśnienie"], "mentions_all": ["PS-17", "Cedarfall"], "forbid": ["2025"]}
    )
    a = answer("PS-17 i Cedarfall: CISNIENIE spada.")
    assert graders.mentions_any(it, a) is True
    assert graders.mentions_all(it, a) is True
    assert graders.forbid(it, a) is True
    assert graders.forbid(it, answer("It is 2025.")) is False
    assert (
        graders.mentions_any(item(expect={"mentions_any": ["PS-17"]}), answer("Decyzja DC-D3-PS17-POWER."))
        is True
    )


def test_photos_need_ids_and_urls() -> None:
    it = item(klass="photos", expect={"photos": 2})
    good = [{"id": "ladi-v2-test-0016", "thumbnail_url": "/api/damage/thumbs/ladi-v2-test-0016"}] * 2
    assert graders.photos(it, answer("Photos.", photos=good)) is True
    assert graders.photos(it, answer("Photos.", photos=[{"id": "x"}, {"id": "y"}])) is False
    r33 = [{"photo_id": "p1", "thumb_url": "/api/damage/thumbs/p1", "href": "/crews?photo=p1"}] * 2
    assert graders.photos(it, answer("Photos.", photos=r33)) is True
    refs = [{"kind": "photo", "id": "a"}, {"kind": "photo", "id": "b"}]
    assert graders.photos(it, answer("Photos.", references=refs)) is True


def test_clarify_and_near_miss() -> None:
    it = item(klass="clarify", expect={"mentions_any": ["PS-17", "PS-23", "PS-38"]})
    assert (
        graders.clarifies(it, answer("Which one do you mean?\nPS-17 Cedarfall?\nPS-23 Laurelspur?")) is True
    )
    assert graders.clarifies(it, answer("PS-17 is fine and PS-23 is below the floor.")) is True
    assert graders.clarifies(it, answer("PS-17 is fine.")) is False
    assert graders.clarifies(it, answer("x", did_you_mean=["Is PS-17 out?", "Is PS-23 out?"])) is True
    assert graders.clarifies(it, answer("x", clarify={"options": ["PS-17", "PS-23"]})) is False
    assert graders.clarifies(it, answer("Unclear.", did_you_mean=["PS-17 status?", "PS-23 status?"])) is True
    nm = item(klass="near_miss", expect={"mentions_any": ["PS-17"]})
    assert graders.near_miss(nm, answer("There is no PS-99. Our stations are PS-17 and PS-23.")) is True
    assert graders.near_miss(nm, answer("There is no PS-99.")) is False


def test_grade_aggregates_and_report_counts() -> None:
    it = item(expect={"mentions_any": ["PS-17"]})
    g = grade(it, answer("PS-17 must be decided now."))
    assert g["pass"] is True and g["failed"] == []
    g = grade(it, answer("Not found in SGW documents", path="m2", reason="out_of_scope"))
    assert g["pass"] is False and {"not_bare_refusal", "mentions_any"} <= set(g["failed"])
    rows = [
        {
            **it.model_dump(),
            "split": "dev",
            "pass": True,
            "failed": [],
            "latency_s": 2.0,
            "usd": 0.01,
            "path": "llm",
            "reason": None,
        },
        {
            **it.model_dump(),
            "split": "dev",
            "pass": False,
            "failed": ["language"],
            "latency_s": 4.0,
            "usd": 0.0,
            "path": "m2",
            "reason": "out_of_scope",
        },
    ]
    data = report.build(
        {
            "label": "t",
            "commit": "x",
            "split": "dev",
            "gateway_mode": "replay",
            "wave": "T",
            "started_utc": "",
            "seconds": 1,
        },
        rows,
    )
    assert data["summary"]["pass_rate"] == 0.5
    assert data["by"]["klass"]["data"]["n"] == 2
    assert data["summary"]["grader_failures"] == {"language": 1}
    assert "Failed items" in report.markdown(data)


def test_judge_sampling_and_call_through_a_fake_gateway() -> None:
    import json as _json

    import httpx

    from sgw.evals.ask_bank import judge

    rows = [
        {"id": "AB-X-001", "persona": "ic_01", "question": "q?", "text": "a", "judge": True},
        {"id": "AB-X-002", "persona": "ic_01", "question": "q?", "text": "b"},
        {"id": "AB-X-003", "persona": "ic_01", "question": "q?", "text": "", "error": "x"},
    ]
    assert [r["id"] for r in judge.sample(rows, 5)] == ["AB-X-001", "AB-X-002"]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        verdict = {"helpful": 4, "plain": 3, "why": "ok"}
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": _json.dumps(verdict)}]},
            headers={"x-sgw-cost-usd": "0.002"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        v = judge.judge_one(client, "http://gw", "tok", "R33", rows[0])
    assert v["pass"] is True and v["usd"] == 0.002
    req = seen[0]
    assert req.headers["x-sgw-node"] == judge.NODE and req.headers["x-sgw-purpose"] == "eval"
    assert "temperature" not in _json.loads(req.content)


def test_language_reads_the_answer_body_not_the_english_sources() -> None:
    text = 'Ciśnienie poniżej minimum jest groźne, bo grozi skażeniem wody. [1]\n\nSources:\n[1] WQC 07.114: "Loss of integrity: a main break with contamination risk, backflow, or loss of positive pressure."'
    assert graders.same_language(item(lang="pl"), answer(text)) is True


def test_infra_misses_are_reported_apart() -> None:
    rows = [
        {"pass": False, "error": "thread: HTTP 403", "reason": None, "text": None},
        {"pass": False, "error": None, "reason": "llm_unavailable", "text": "x"},
        {"pass": True, "error": None, "reason": None, "text": "ok"},
        {"pass": False, "error": "PermissionError: role_blocked: POST /api/threads HTTP 403 READ_ONLY_ROLE"},
    ]
    assert [report.infra(r) for r in rows] == [True, True, False, False]


def test_heldout_rows_are_redacted_in_the_repo_report(tmp_path: object) -> None:
    from pathlib import Path

    out, private = Path(str(tmp_path)) / "out", Path(str(tmp_path)) / "private"
    base = {
        "klass": "data",
        "lang": "en",
        "persona": "ic_01",
        "moment": "at-n1",
        "page": "none",
        "tags": [],
        "failed": ["x"],
        "pass": False,
    }
    rows = [
        {
            **base,
            "id": "AB-A-001",
            "split": "dev",
            "question": "dev q",
            "text": "dev answer",
            "latency_s": 1.0,
        },
        {
            **base,
            "id": "AB-A-002",
            "split": "heldout",
            "question": "secret q",
            "text": "secret answer",
            "latency_s": 1.0,
        },
    ]
    meta = {
        "label": "t",
        "commit": "x",
        "split": "all",
        "gateway_mode": "replay",
        "wave": "T",
        "started_utc": "",
        "seconds": 1,
    }
    j, md = report.write(report.build(meta, rows), out, "t", private=private)
    public = j.read_text(encoding="utf-8") + md.read_text(encoding="utf-8")
    assert "secret" not in public and "dev answer" in public
    assert "secret answer" in (private / "t.json").read_text(encoding="utf-8")
