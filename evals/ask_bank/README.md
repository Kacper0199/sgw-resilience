# Ask AI question bank (R33)

End-to-end evaluation of Ask AI through the API, as each seeded persona, at each demo moment. Written from the
platform's own content (personas in `data/seed/users.yaml`, moments in `src/sgw/demo/bookmarks.py`, named
assets, the decision catalog, damage photos in `data/artefacts/cv/review_queue.json`, pages and tabs in
`web/src/app/modules.ts`, the glossary in `web/src/content/`, the corpus manifest, the Ask starters) and from
the questions users actually asked (requests 027 and 030). Not by an independent eval author: a known limit.

| Path | Who reads it |
| --- | --- |
| `dev/*.yaml` | developers: tune and debug on these |
| `heldout/*.yaml` | the eval harness and reviewers only; never read while building a prompt, router or worker |
| `smoke.yaml` | 40 dev ids covering every class, persona and moment: the quick check for a branch |

Split: an item is held out when `int(sha256(id)[:8], 16) % 10 < 3` (about 30 %); a test checks every item
sits in the file its id dictates. A follow-up chain is one item.

## Item

`id`, `lang` (en, pl, de, es, fr; the answer must be in the same language), `persona`, `moment` (at-n1,
morning-after, notices-lifted), `page`, `klass`, `tags` (typo, no_diacritics, vague, starter, user_reported,
link_request, other_language, ...), `turns` (prior questions of a follow-up), `question`, `expect`
(`answer`, `links` as `page` or `page:target`, `mentions_any`, `mentions_all`, `forbid`, `photos`), `judge`.

Classes: `data`, `overview`, `navigate`, `explain`, `photos`, `followup`, `role`, `clarify` (a "did you
mean" with concrete options), `near_miss` (the thing does not exist, something related does),
`refuse_unrelated`, `refuse_write`, `refuse_injection`.

## Graders (code, `src/sgw/evals/ask_bank/graders.py`)

An item passes when no applicable grader fails. The bank grades a permissive, helpful assistant (D-103):

- `not_bare_refusal`: an in-domain or helpful question is never refused as out of scope; an honest "not on the
  platform" passes only with a deep link, a suggested question or a "did you mean".
- `refuses`, `helpful_refusal`: unrelated topics, write actions and injections are declined, with at least two
  suggested questions.
- `clarifies`, `near_miss`: as described above.
- `no_write`, `language`, `links`, `role_links` (no Admin link for other roles), `mentions_any`,
  `mentions_all`, `forbid`, `photos`.

Links are read from the answer's `links`, its typed `references` (mapped to the routes the UI opens) and app
paths in the text. A sampled LLM judge (`--judge N`) scores helpfulness and plainness; it is not calibrated
against human labels and never gates.

## Run

```
uv run python -m sgw.evals.ask_bank.run --split dev --smoke --label <name>
uv run python -m sgw.evals.ask_bank.run --split all --sample 100 --label <name> --cap-usd 2.5
uv run python -m sgw.evals.ask_bank.run --regrade data/artefacts/evals/ask_bank/<name>.json
```

The runner starts a private stack (OPA, an LLM gateway in `replay_then_live` on the shared spend ledger, the
API in demo mode with `SGW_DB_POOL_MAX=2` on a scratch database copied from the demo template), loads each
moment, asks, grades and writes `data/artefacts/evals/ask_bank/<name>.json` and `.md` with pass rates by
class, persona, language, moment, page, split and tag. Live calls are tagged `x-sgw-purpose: eval`; the run
stops spending at `--cap-usd`. Options: `--ids`, `--klass`, `--sample`, `--api-port`, `--gateway-port`,
`--db`, `--judge`.
