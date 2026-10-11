"""Lint the sample corpus before harvesting it.

    uv run --project backend python scripts/sample-data/lint_corpus.py

Checks frontmatter (required keys, dates inside the story window, created <=
updated), unique titles per source, Notion parents, Confluence spaces, and
that every Obsidian [[wikilink]] resolves to a note in the vault.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "backend"))
from fixture_plugin import as_date, read_corpus_doc
from sample_guard import corpus_dir

WIKILINK = re.compile(r"!?\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
SPACES = {"ENG", "PLAT", "SEC"}


def main() -> None:
    CORPUS = corpus_dir()
    bible = yaml.safe_load((HERE / "story_bible.yaml").read_text(encoding="utf-8"))
    start = as_date(bible["timeline_start"])
    end = as_date(bible["timeline_end"])
    late_day = date.fromordinal(end.toordinal() + 1)
    problems: list[str] = []
    counts: Counter[str] = Counter()

    def sources():
        for late in (False, True):
            base = CORPUS / "late" if late else CORPUS
            for name, sub in (("notion", "notion"), ("confluence", "confluence"),
                              ("obsidian", "obsidian/Maya"), ("notes", "notes")):
                root = base / sub
                if root.is_dir():
                    yield name, late, root

    vault_stems = {p.stem for p in (CORPUS / "obsidian" / "Maya").rglob("*.md")}
    vault_stems |= {p.stem for p in (CORPUS / "late" / "obsidian" / "Maya").rglob("*.md")}
    titles: dict[str, Counter[str]] = {}

    for name, late, root in sources():
        for path in sorted(root.rglob("*.md")):
            rel = path.relative_to(CORPUS)
            counts[f"{name}{' (late)' if late else ''}"] += 1
            try:
                doc = read_corpus_doc(path)
            except Exception as e:  # noqa: BLE001
                problems.append(f"{rel}: {e}")
                continue
            meta = doc.meta
            titles.setdefault(name, Counter())[str(meta["title"])] += 1
            try:
                created, updated = as_date(meta["created"]), as_date(meta["updated"])
            except ValueError as e:
                problems.append(f"{rel}: bad date ({e})")
                continue
            hi = late_day if late else end
            if not (start <= created <= updated <= hi):
                problems.append(f"{rel}: dates out of order/window (created {created}, updated {updated})")
            if not doc.body.lstrip().startswith("# "):
                problems.append(f"{rel}: body should start with '# <title>'")
            if name == "notion":
                is_root = path.name == "_index.md"
                if is_root and meta.get("parent"):
                    problems.append(f"{rel}: root page must not have a parent")
                if not is_root:
                    if not (path.parent / "_index.md").is_file() and not (
                        CORPUS / "notion" / path.parent.name / "_index.md"
                    ).is_file():
                        problems.append(f"{rel}: no _index.md for {path.parent.name}")
                    if str(meta.get("parent") or "") != path.parent.name:
                        problems.append(f"{rel}: parent {meta.get('parent')!r} != folder {path.parent.name!r}")
            if name == "confluence":
                space = str(meta.get("space") or "")
                if space not in SPACES or space != path.parent.name:
                    problems.append(f"{rel}: space {space!r} must be one of {sorted(SPACES)} and match its folder")
            if name == "obsidian":
                if path.stem != str(meta["title"]):
                    problems.append(f"{rel}: file stem must equal title {meta['title']!r}")
                for target in WIKILINK.findall(doc.body):
                    if target.strip() not in vault_stems:
                        problems.append(f"{rel}: unresolved [[{target.strip()}]]")
            if name != "obsidian" and "[[" in doc.body:
                problems.append(f"{rel}: wikilinks are only for the Obsidian vault")

    for name, c in titles.items():
        for title, n in c.items():
            if n > 1:
                problems.append(f"{name}: duplicate title {title!r} ({n}×)")

    print("corpus: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + f" (total {sum(counts.values())})")
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems[:100]:
            print(f"  - {p}")
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
