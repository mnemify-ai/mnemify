"""Entity-label canonicalization (Stage 4.5).

The chunkers and feature extractor surface entity-like tokens in many
shapes — ``Project Phoenix``, ``phoenix project``, ``Phoenix``,
``[[Phoenix]]``. We need to fold those into a single canonical label
before promoting entities to graph nodes; otherwise we'd emit four
near-duplicate nodes and the chatbot would split membership across them.

This module is intentionally dependency-light: it uses :mod:`difflib`
for fuzzy matching so we don't pull in :mod:`rapidfuzz` for what is
essentially a one-shot dedupe pass.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


_PUNCT = re.compile(r"[^\w\s-]+")
_WIKILINK_SQUARES = re.compile(r"^\[\[(.+?)\]\]$")
_WS = re.compile(r"\s+")


def normalize(raw: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace, drop common
    noise prefixes (``the ``). Returns a key for grouping near-duplicates;
    callers keep the original casing for display."""
    if not raw:
        return ""
    text = unicodedata.normalize("NFKD", raw)
    text = _WIKILINK_SQUARES.sub(r"\1", text.strip())
    text = text.lower()
    text = _PUNCT.sub(" ", text)
    text = _WS.sub(" ", text).strip()
    if text.startswith("the "):
        text = text[4:]
    return text


def fuzzy_canonical_map(
    labels: list[str],
    *,
    similarity_threshold: float = 0.85,
) -> dict[str, str]:
    """Map each input label to a chosen canonical display form.

    Strategy: bucket by normalized form first (exact match after
    normalization); then merge buckets whose normalized forms are
    >= ``similarity_threshold`` similar via difflib. The canonical
    display form is the *longest* original label in the merged bucket
    (longer forms usually carry more context: ``Project Phoenix`` >
    ``Phoenix``).
    """
    if not labels:
        return {}

    # Bucket by exact normalized form first.
    buckets: dict[str, list[str]] = {}
    for label in labels:
        key = normalize(label)
        if not key:
            continue
        buckets.setdefault(key, []).append(label)

    # Merge near-duplicate buckets. O(n^2) but n is small (top-N entities,
    # typically dozens).
    keys = sorted(buckets.keys())
    parent: dict[str, str] = {k: k for k in keys}

    def find(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            if SequenceMatcher(a=a, b=b).ratio() >= similarity_threshold:
                parent[find(b)] = find(a)

    # Collect canonical display form per group: longest original label.
    out: dict[str, str] = {}
    grouped: dict[str, list[str]] = {}
    for key, labels_in_bucket in buckets.items():
        grouped.setdefault(find(key), []).extend(labels_in_bucket)
    for group_labels in grouped.values():
        canonical = max(group_labels, key=lambda s: (len(s), s))
        for label in group_labels:
            out[label] = canonical
    return out
