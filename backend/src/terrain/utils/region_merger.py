from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from itertools import combinations
from typing import Any, Callable

import numpy as np

from src.terrain.utils.clusterer import TerrainClusterer
from src.terrain.utils.models import ClusterTreeNode, EnrichedChunk, Position


logger = logging.getLogger(__name__)

CANDIDATE_THRESHOLD = 0.55
MAX_CANDIDATE_PAIRS = 40


def _judge_concurrency() -> int:
    """Max concurrent pair judgments. Shares the compiler's LLM fan-out knob
    (``TERRAIN_LLM_CONCURRENCY``, default 16); ``1`` reproduces the serial loop."""
    try:
        return max(1, int(os.getenv("TERRAIN_LLM_CONCURRENCY", "16")))
    except ValueError:
        return 16


_SYSTEM_PROMPT = (
    "You decide whether two knowledge regions should be combined. You are given "
    "two regions with their names, sample document summaries, and sizes. Decide if they are "
    "(a) the same topic [merge], (b) related subtopics that belong under one parent [nest], "
    "or (c) genuinely distinct [keep_separate]. Be conservative: only merge if they are "
    "clearly about the same thing. Respond with ONLY a JSON object, no prose, no markdown."
)


@dataclass(frozen=True)
class _Candidate:
    a_id: str
    b_id: str
    similarity: float


@dataclass(frozen=True)
class _Verdict:
    a_id: str
    b_id: str
    decision: str
    parent: str | None
    reason: str
    # Audit fields (persisted via the compiler's ``on_verdict`` hook):
    similarity: float = 0.0
    a_label: str = ""
    b_label: str = ""


class _UnionFind:
    def __init__(self, values: list[str]):
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        root = self.parent[value]
        if root != value:
            root = self.find(root)
            self.parent[value] = root
        return root

    def union(self, a: str, b: str) -> None:
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a == root_b:
            return
        if root_b < root_a:
            root_a, root_b = root_b, root_a
        self.parent[root_b] = root_a


class RegionMerger:
    """Post-process top-level HDBSCAN regions with bounded LLM judgment."""

    def __init__(self, llm_client: Any | None = None, *, model: str | None = None):
        self.llm_client = llm_client
        self.model = model or getattr(llm_client, "model", None) or "gpt-5.6-luna"
        self._clusterer = TerrainClusterer()

    def merge(
        self,
        roots: list[ClusterTreeNode],
        chunks: list[EnrichedChunk],
        *,
        allow_merge: bool = True,
        on_verdict: Callable[[_Verdict], None] | None = None,
    ) -> list[ClusterTreeNode]:
        """Audit the top-level regions with bounded LLM judgment.

        ``on_verdict`` receives every judged pair (with the candidate
        similarity and the heuristic labels the judge saw) so callers can log
        and persist the decisions — they were previously visible only in the
        process log. It fires with the *raw* verdict, before any
        ``allow_merge`` downgrade.

        ``allow_merge=False`` runs the merger as a conservative janitor over a
        source-native backbone (container clustering): it may still *nest*
        related folders under a parent, but it will never *merge* one sibling
        folder away into another. This preserves every folder as its own
        region — without it, tight sibling folders (a CTO vault's
        Architecture / Engineering-Leadership / Strategy) clear the candidate
        cosine and silently collapse, undoing the container structure.
        """
        if len(roots) < 2 or not chunks:
            return roots

        chunks_by_id = {item.chunk.id: item for item in chunks}
        candidates = self._candidates(roots, chunks_by_id)
        if not candidates:
            logger.info("terrain: region merger found no candidate pairs")
            return roots

        if self.llm_client is None:
            logger.info(
                "terrain: region merger skipped %s candidate pair(s); no LLM client",
                len(candidates),
            )
            return roots

        # Judge candidate pairs concurrently. Each judgment reads only the
        # static ``roots``/``chunks_by_id`` (never a prior verdict), and
        # ``_apply_verdicts`` is order-independent (union-find), so fanning
        # out changes wall time only. Results are collected back in candidate
        # order so ``on_verdict`` fires — and the audit rows persist — in the
        # same deterministic order as the previous serial loop.
        workers = max(1, min(len(candidates), _judge_concurrency()))
        if workers == 1:
            verdicts = [self._judge_pair(c, roots, chunks_by_id) for c in candidates]
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                verdicts = list(
                    executor.map(
                        lambda c: self._judge_pair(c, roots, chunks_by_id), candidates
                    )
                )
        if on_verdict is not None:
            for verdict in verdicts:
                on_verdict(verdict)
        if not allow_merge:
            # Downgrade merges to keep_separate; nest verdicts still apply.
            verdicts = [
                v if v.decision != "merge"
                else replace(v, decision="keep_separate", parent=None)
                for v in verdicts
            ]
        return self._apply_verdicts(roots, chunks_by_id, verdicts)

    def _candidates(
        self,
        roots: list[ClusterTreeNode],
        chunks_by_id: dict[str, EnrichedChunk],
    ) -> list[_Candidate]:
        centroids: dict[str, np.ndarray] = {}
        for root in roots:
            members = [chunks_by_id[cid] for cid in root.chunk_ids if cid in chunks_by_id]
            if members:
                centroids[root.id] = self._clusterer._normalized_centroid(members)

        candidates: list[_Candidate] = []
        for a, b in combinations(roots, 2):
            centroid_a = centroids.get(a.id)
            centroid_b = centroids.get(b.id)
            if centroid_a is None or centroid_b is None:
                continue
            similarity = float(centroid_a @ centroid_b)
            if similarity >= CANDIDATE_THRESHOLD:
                candidates.append(_Candidate(a.id, b.id, similarity))

        candidates.sort(key=lambda item: (-item.similarity, item.a_id, item.b_id))
        return candidates[:MAX_CANDIDATE_PAIRS]

    def _judge_pair(
        self,
        candidate: _Candidate,
        roots: list[ClusterTreeNode],
        chunks_by_id: dict[str, EnrichedChunk],
    ) -> _Verdict:
        nodes = {root.id: root for root in roots}
        a = nodes[candidate.a_id]
        b = nodes[candidate.b_id]
        a_chunks = self._members(a, chunks_by_id)
        b_chunks = self._members(b, chunks_by_id)
        raw = self._call_llm(
            self._region_name(a, a_chunks),
            len(a.chunk_ids),
            self._summaries(a_chunks),
            self._region_name(b, b_chunks),
            len(b.chunk_ids),
            self._summaries(b_chunks),
        )
        verdict = replace(
            self._parse_verdict(raw, candidate.a_id, candidate.b_id),
            similarity=candidate.similarity,
            a_label=self._region_name(a, a_chunks),
            b_label=self._region_name(b, b_chunks),
        )
        logger.info(
            "terrain: region merger verdict %s ~ %s (sim %.3f): %s parent=%s reason=%s",
            candidate.a_id,
            candidate.b_id,
            candidate.similarity,
            verdict.decision,
            verdict.parent,
            verdict.reason,
        )
        return verdict

    def _call_llm(
        self,
        a_name: str,
        a_count: int,
        a_summaries: list[str],
        b_name: str,
        b_count: int,
        b_summaries: list[str],
    ) -> str:
        if hasattr(self.llm_client, "judge_region_pair"):
            return str(
                self.llm_client.judge_region_pair(
                    a_name, a_count, a_summaries, b_name, b_count, b_summaries
                )
            )

        user_prompt = "\n".join(
            [
                f"Region A - name: {a_name}, size: {a_count} chunks",
                f"Sample summaries: {json.dumps(a_summaries, ensure_ascii=False)}",
                "",
                f"Region B - name: {b_name}, size: {b_count} chunks",
                f"Sample summaries: {json.dumps(b_summaries, ensure_ascii=False)}",
                "",
                'Return: {"decision": "merge"|"nest"|"keep_separate", '
                '"parent": "A"|"B"|null, "reason": "..."}',
            ]
        )
        # Effort travels with the namer (the judge shares its model + setting).
        llm_kwargs = getattr(self.llm_client, "_llm_kwargs", None)
        extra = llm_kwargs() if callable(llm_kwargs) else {}
        response = self.llm_client._client().responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            **extra,
        )
        # Real OpenAI client returns usage; the shims record their own.
        from src.terrain.agents.usage import ledger
        ledger.record_openai(getattr(response, "usage", None), model=self.model)
        return str(getattr(response, "output_text", ""))

    def _parse_verdict(self, raw: str, a_id: str, b_id: str) -> _Verdict:
        try:
            text = (raw or "").strip()
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)
            decision = str(data.get("decision") or "keep_separate")
            if decision not in {"merge", "nest", "keep_separate"}:
                decision = "keep_separate"
            parent_raw = data.get("parent")
            parent = parent_raw if parent_raw in {"A", "B", None} else None
            reason = str(data.get("reason") or "No reason provided.")[:240]
            if decision != "nest":
                parent = None
            return _Verdict(a_id, b_id, decision, parent, reason)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "terrain: region merger could not parse LLM verdict for %s ~ %s: %s",
                a_id,
                b_id,
                exc,
            )
            return _Verdict(a_id, b_id, "keep_separate", None, "Invalid LLM JSON.")

    def _apply_verdicts(
        self,
        roots: list[ClusterTreeNode],
        chunks_by_id: dict[str, EnrichedChunk],
        verdicts: list[_Verdict],
    ) -> list[ClusterTreeNode]:
        roots_by_id = {root.id: root.model_copy(deep=True) for root in roots}
        uf = _UnionFind(list(roots_by_id))
        for verdict in verdicts:
            if verdict.decision == "merge":
                uf.union(verdict.a_id, verdict.b_id)

        grouped: dict[str, list[str]] = {}
        for root_id in roots_by_id:
            grouped.setdefault(uf.find(root_id), []).append(root_id)

        redirected: dict[str, str] = {}
        merged_roots: dict[str, ClusterTreeNode] = {}
        for root_id, member_ids in grouped.items():
            member_ids = sorted(member_ids)
            if len(member_ids) == 1:
                merged_roots[root_id] = roots_by_id[root_id]
                redirected[root_id] = root_id
                continue
            members = [roots_by_id[mid] for mid in member_ids]
            merged = self._merged_node(member_ids, members, chunks_by_id)
            merged_roots[merged.id] = merged
            for member_id in member_ids:
                redirected[member_id] = merged.id

        ordered = [
            merged_roots[redirected[root.id]]
            for root in roots
            if redirected[root.id] in merged_roots
        ]
        deduped: list[ClusterTreeNode] = []
        seen: set[str] = set()
        for root in ordered:
            if root.id in seen:
                continue
            deduped.append(root)
            seen.add(root.id)

        top_level = {root.id: root for root in deduped}
        for verdict in verdicts:
            if verdict.decision != "nest":
                continue
            a_id = redirected.get(verdict.a_id, verdict.a_id)
            b_id = redirected.get(verdict.b_id, verdict.b_id)
            if a_id == b_id:
                continue
            if verdict.parent == "A":
                self._move_child(top_level, parent_id=a_id, child_id=b_id, chunks_by_id=chunks_by_id)
            elif verdict.parent == "B":
                self._move_child(top_level, parent_id=b_id, child_id=a_id, chunks_by_id=chunks_by_id)
            else:
                self._synth_parent(top_level, a_id, b_id, chunks_by_id)

        return list(top_level.values())

    def _merged_node(
        self,
        member_ids: list[str],
        members: list[ClusterTreeNode],
        chunks_by_id: dict[str, EnrichedChunk],
    ) -> ClusterTreeNode:
        chunk_ids = sorted({cid for member in members for cid in member.chunk_ids})
        children = [child for member in members for child in member.children]
        if children:
            # A childless member IS its own leaf. Dissolving it would leave its
            # chunks covered by no child of the merged node, and downstream
            # tags/notes are minted from leaf membership only — the member's
            # docs would silently lose their tags, notes, and graph presence.
            # Demote such members to children so they survive as leaves. When
            # every member is childless the merged node is itself a leaf and
            # nothing is lost.
            children.extend(member for member in members if not member.children)
        node_id = self._fresh_node_id(f"merge_{'|'.join(member_ids)}", chunk_ids, chunks_by_id)
        return ClusterTreeNode(
            id=node_id,
            name="",
            position=Position(x=0.0, z=0.0),
            height=max((member.height for member in members), default=1),
            chunk_ids=chunk_ids,
            children=children,
        )

    def _move_child(
        self,
        top_level: dict[str, ClusterTreeNode],
        *,
        parent_id: str,
        child_id: str,
        chunks_by_id: dict[str, EnrichedChunk],
    ) -> None:
        parent = top_level.get(parent_id)
        child = top_level.get(child_id)
        if parent is None or child is None:
            return
        if not parent.children:
            # The parent was a leaf. Giving it a child turns it into an
            # internal node, and tags/notes/graph nodes are minted from
            # leaves only — so its own chunks would silently drop out of the
            # map (same hazard ``_merged_node`` guards against). Keep them
            # reachable as a sibling leaf, the way the clusterer does for a
            # folder that has both notes and sub-folders (``__direct__``).
            own = sorted(set(parent.chunk_ids) - set(child.chunk_ids))
            if own:
                parent.children.append(
                    ClusterTreeNode(
                        id=self._fresh_node_id(f"{parent.id}/__direct__", own, chunks_by_id),
                        name="",
                        position=Position(x=0.0, z=0.0),
                        height=parent.height,
                        chunk_ids=own,
                        children=[],
                    )
                )
        parent.children = [existing for existing in parent.children if existing.id != child.id]
        parent.children.append(child)
        parent.chunk_ids = sorted(set(parent.chunk_ids) | set(child.chunk_ids))
        del top_level[child_id]

    def _synth_parent(
        self,
        top_level: dict[str, ClusterTreeNode],
        a_id: str,
        b_id: str,
        chunks_by_id: dict[str, EnrichedChunk],
    ) -> None:
        a = top_level.get(a_id)
        b = top_level.get(b_id)
        if a is None or b is None:
            return
        chunk_ids = sorted(set(a.chunk_ids) | set(b.chunk_ids))
        node_id = self._fresh_node_id(f"nest_{a_id}|{b_id}", chunk_ids, chunks_by_id)
        parent = ClusterTreeNode(
            id=node_id,
            name="",
            position=Position(x=0.0, z=0.0),
            height=max(a.height, b.height),
            chunk_ids=chunk_ids,
            children=[a, b],
        )
        del top_level[a_id]
        del top_level[b_id]
        top_level[node_id] = parent

    def _fresh_node_id(
        self,
        path: str,
        chunk_ids: list[str],
        chunks_by_id: dict[str, EnrichedChunk],
    ) -> str:
        members = [chunks_by_id[cid] for cid in chunk_ids if cid in chunks_by_id]
        return self._clusterer._node_id(path, members)

    def _members(
        self,
        node: ClusterTreeNode,
        chunks_by_id: dict[str, EnrichedChunk],
    ) -> list[EnrichedChunk]:
        return [chunks_by_id[cid] for cid in node.chunk_ids if cid in chunks_by_id]

    def _summaries(self, items: list[EnrichedChunk]) -> list[str]:
        summaries = [item.features.summary.strip() for item in items if item.features.summary.strip()]
        return summaries[:3]

    def _region_name(self, node: ClusterTreeNode, items: list[EnrichedChunk]) -> str:
        if node.name.strip():
            return node.name.strip()
        values: list[str] = []
        for item in items:
            f = item.features
            values.extend(f.products[:2] + f.customers[:2] + f.entities[:4])
        top = [value for value, _ in Counter(v for v in values if v).most_common(5)]
        return ", ".join(top) if top else "Unnamed Region"
