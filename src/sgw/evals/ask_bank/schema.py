"""Ask AI question bank: one item per question or follow-up chain, asked through the API as a
seeded persona at a demo moment. Expectations are code-checkable (`graders.py`)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

REPO = Path(__file__).resolve().parents[4]
BANK = REPO / "evals" / "ask_bank"
SPLITS = ("dev", "heldout")

Lang = Literal["en", "pl", "de", "es", "fr"]
Moment = Literal["at-n1", "morning-after", "notices-lifted"]
Page = Literal[
    "decisions",
    "map",
    "forecast",
    "crews",
    "water",
    "ask",
    "brief",
    "after_action",
    "health",
    "readiness",
    "admin",
    "notifications",
    "help",
    "none",
]
Klass = Literal[
    "data",
    "overview",
    "navigate",
    "explain",
    "photos",
    "followup",
    "role",
    "clarify",
    "near_miss",
    "refuse_unrelated",
    "refuse_write",
    "refuse_injection",
]
REFUSE_CLASSES = frozenset({"refuse_unrelated", "refuse_write", "refuse_injection"})
PERSONAS = (
    "ic_01",
    "ops_dm_01",
    "ops_dm_02",
    "plan_etr_01",
    "log_01",
    "wtr_lead_01",
    "wtr_comp_01",
    "exec_01",
    "audit_01",
    "admin_01",
    "ml_01",
)
PAGES: tuple[str, ...] = Page.__args__  # type: ignore[attr-defined]


class Expect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: bool = True
    links: list[str] = Field(default_factory=list)
    mentions_any: list[str] = Field(default_factory=list)
    mentions_all: list[str] = Field(default_factory=list)
    forbid: list[str] = Field(default_factory=list)
    photos: int = 0

    @model_validator(mode="after")
    def _links_name_pages(self) -> Expect:
        for link in self.links:
            if link.split(":", 1)[0] not in PAGES:
                raise ValueError(f"link {link!r} does not name a page")
        return self


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^AB-[A-Z]+-\d{3}$")
    lang: Lang
    persona: Literal[PERSONAS]  # type: ignore[valid-type]
    moment: Moment
    page: Page = "none"
    klass: Klass
    tags: list[str] = Field(default_factory=list)
    turns: list[str] = Field(default_factory=list)
    question: str = Field(min_length=2)
    expect: Expect = Field(default_factory=Expect)
    judge: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> Item:
        refuse = self.klass in REFUSE_CLASSES
        if refuse == self.expect.answer:
            raise ValueError(f"{self.id}: klass {self.klass} needs expect.answer={not refuse}")
        if self.klass == "followup" and not self.turns:
            raise ValueError(f"{self.id}: a follow-up needs prior turns")
        if self.klass == "photos" and self.expect.photos < 1:
            raise ValueError(f"{self.id}: a photo question expects photos >= 1")
        return self

    @property
    def split(self) -> str:
        from sgw.evals.ask_bank.split import split_of

        return split_of(self.id)


def read_file(path: Path) -> list[Item]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Item.model_validate(i) for i in raw.get("items") or []]


def load(split: str = "dev", bank: Path = BANK) -> list[Item]:
    """Items of one split (`dev`, `heldout`) or `all`; ids are unique across both."""
    splits = SPLITS if split == "all" else (split,)
    items = [i for s in splits for f in sorted((bank / s).glob("*.yaml")) for i in read_file(f)]
    ids = [i.id for i in items]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"duplicate ids: {dupes}")
    return items


def smoke_ids(bank: Path = BANK) -> list[str]:
    data = yaml.safe_load((bank / "smoke.yaml").read_text(encoding="utf-8"))
    return [str(i) for i in data["ids"]]
