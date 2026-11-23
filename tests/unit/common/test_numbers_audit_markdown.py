from __future__ import annotations

from pathlib import Path

from sgw.common import numbers


def test_markdown_literal_is_accepted_only_with_its_key_on_the_line(tmp_path: Path) -> None:
    nf = numbers.load()
    key, entry = next((k, e) for k, e in nf.numbers.items() if isinstance(e.value, int) and e.value >= 12345)
    literal = f"{entry.value:,}"
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(f"cited {literal} (`{key}`)\nbare {literal}\n", encoding="utf-8")
    findings = numbers.audit(nf, root=tmp_path)
    assert findings == [f"docs/guide.md:2: literal {literal} (use numbers key {key})"]
