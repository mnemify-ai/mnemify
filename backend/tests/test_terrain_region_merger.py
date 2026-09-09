from __future__ import annotations

import json

from src.terrain.utils.models import ChunkFeatures, ClusterTreeNode, EnrichedChunk, TerrainChunk
from src.terrain.utils.region_merger import RegionMerger


def enriched_chunk(chunk_id: str, embedding: list[float], summary: str) -> EnrichedChunk:
    return EnrichedChunk(
        chunk=TerrainChunk(
            id=chunk_id,
            doc_id=f"doc-{chunk_id}",
            source_type="notion",
            source_id=f"source-{chunk_id}",
            doc_title=f"Doc {chunk_id}",
            content=summary,
            content_hash=f"hash-{chunk_id}",
        ),
        features=ChunkFeatures(
            summary=summary,
            entities=[summary.split()[0].title()],
            tags=summary.split()[:4],
            theme="General",
            subtopic="General",
        ),
        embedding=embedding,
    )


class FakeJudge:
    model = "fake-model"

    def __init__(self, decision: str, parent=None):
        self.decision = decision
        self.parent = parent
        self.calls = 0

    def judge_region_pair(self, *_args):
        self.calls += 1
        return json.dumps(
            {
                "decision": self.decision,
                "parent": self.parent,
                "reason": "test verdict",
            }
        )


def test_region_merger_skips_llm_when_no_candidates():
    chunks = [
        enriched_chunk("a", [1.0, 0.0], "invoice extraction models"),
        enriched_chunk("b", [0.0, 1.0], "field inspection imagery"),
    ]
    roots = [
        ClusterTreeNode(id="A", name="Invoices", chunk_ids=["a"]),
        ClusterTreeNode(id="B", name="Inspection", chunk_ids=["b"]),
    ]
    judge = FakeJudge("merge")

    result = RegionMerger(judge).merge(roots, chunks)

    assert result == roots
    assert judge.calls == 0


def test_region_merger_merges_candidate_pair():
    chunks = [
        enriched_chunk("a", [1.0, 0.0], "neural network architecture"),
        enriched_chunk("b", [0.9, 0.1], "machine learning paradigms"),
    ]
    roots = [
        ClusterTreeNode(id="A", name="Neural Network Architectures", chunk_ids=["a"]),
        ClusterTreeNode(id="B", name="Machine Learning Paradigms", chunk_ids=["b"]),
    ]
    judge = FakeJudge("merge")

    result = RegionMerger(judge).merge(roots, chunks)

    assert judge.calls == 1
    assert len(result) == 1
    assert result[0].id.startswith("node_")
    assert result[0].id not in {"A", "B"}
    assert result[0].chunk_ids == ["a", "b"]
    assert result[0].children == []


def test_region_merger_nests_under_named_parent():
    chunks = [
        enriched_chunk("a", [1.0, 0.0], "machine learning overview"),
        enriched_chunk("b", [0.9, 0.1], "neural network architecture"),
    ]
    roots = [
        ClusterTreeNode(id="A", name="Machine Learning", chunk_ids=["a"]),
        ClusterTreeNode(id="B", name="Neural Networks", chunk_ids=["b"]),
    ]
    judge = FakeJudge("nest", parent="A")

    result = RegionMerger(judge).merge(roots, chunks)

    assert len(result) == 1
    assert result[0].id == "A"
    assert result[0].chunk_ids == ["a", "b"]
    assert [child.id for child in result[0].children] == ["B"]


def test_region_merger_nests_under_synthesized_parent():
    chunks = [
        enriched_chunk("a", [1.0, 0.0], "neural network architecture"),
        enriched_chunk("b", [0.9, 0.1], "machine learning paradigms"),
    ]
    roots = [
        ClusterTreeNode(id="A", name="Neural Networks", chunk_ids=["a"]),
        ClusterTreeNode(id="B", name="Machine Learning", chunk_ids=["b"]),
    ]
    judge = FakeJudge("nest", parent=None)

    result = RegionMerger(judge).merge(roots, chunks)

    assert len(result) == 1
    assert result[0].id.startswith("node_")
    assert result[0].chunk_ids == ["a", "b"]
    assert [child.id for child in result[0].children] == ["A", "B"]


def test_region_merger_allow_merge_false_keeps_folders_separate():
    # A merge verdict must NOT collapse two container folders when the backbone
    # is source-native (allow_merge=False).
    chunks = [
        enriched_chunk("a", [1.0, 0.0], "neural network architecture"),
        enriched_chunk("b", [0.9, 0.1], "machine learning paradigms"),
    ]
    roots = [
        ClusterTreeNode(id="A", name="Architecture", chunk_ids=["a"]),
        ClusterTreeNode(id="B", name="Engineering Leadership", chunk_ids=["b"]),
    ]
    judge = FakeJudge("merge")

    result = RegionMerger(judge).merge(roots, chunks, allow_merge=False)

    assert judge.calls == 1  # still consulted
    assert [root.id for root in result] == ["A", "B"]  # but not merged away


def test_region_merger_allow_merge_false_still_nests():
    # Nesting is still permitted — it preserves both folders as distinct nodes.
    chunks = [
        enriched_chunk("a", [1.0, 0.0], "machine learning overview"),
        enriched_chunk("b", [0.9, 0.1], "neural network architecture"),
    ]
    roots = [
        ClusterTreeNode(id="A", name="Machine Learning", chunk_ids=["a"]),
        ClusterTreeNode(id="B", name="Neural Networks", chunk_ids=["b"]),
    ]
    judge = FakeJudge("nest", parent="A")

    result = RegionMerger(judge).merge(roots, chunks, allow_merge=False)

    assert len(result) == 1
    assert result[0].id == "A"
    assert [child.id for child in result[0].children] == ["B"]


def test_region_merger_merge_keeps_childless_member_as_leaf_child():
    # A merge between a region with sub-clusters and a childless (leaf) region
    # must keep the leaf as a child of the merged node. Dissolving it leaves
    # its chunks covered by no leaf, so they never get a tag — and their docs
    # never become notes or graph nodes (the "invisible fundraising docs" bug).
    chunks = [
        enriched_chunk("a1", [1.0, 0.0], "engineering leadership rituals"),
        enriched_chunk("a2", [0.98, 0.02], "engineering hiring process"),
        enriched_chunk("b", [0.9, 0.1], "series b fundraising prep"),
    ]
    roots = [
        ClusterTreeNode(
            id="A",
            name="Engineering Leadership",
            chunk_ids=["a1", "a2"],
            children=[
                ClusterTreeNode(id="A1", name="Rituals", chunk_ids=["a1"]),
                ClusterTreeNode(id="A2", name="Hiring", chunk_ids=["a2"]),
            ],
        ),
        ClusterTreeNode(id="B", name="Fundraising", chunk_ids=["b"]),
    ]
    judge = FakeJudge("merge")

    result = RegionMerger(judge).merge(roots, chunks)

    assert len(result) == 1
    merged = result[0]
    assert merged.chunk_ids == ["a1", "a2", "b"]
    assert [child.id for child in merged.children] == ["A1", "A2", "B"]

    # Invariant the compiler relies on: every chunk of the merged node is
    # reachable through some leaf.
    def leaf_chunks(node: ClusterTreeNode) -> set[str]:
        if not node.children:
            return set(node.chunk_ids)
        covered: set[str] = set()
        for child in node.children:
            covered |= leaf_chunks(child)
        return covered

    assert leaf_chunks(merged) == set(merged.chunk_ids)


def test_region_merger_merge_of_two_childless_members_stays_leaf():
    # When every merged member is childless the merged node is itself a leaf;
    # it must NOT sprout its members as children (that would double a tag into
    # tag + sub-tags for what is a single merged topic).
    chunks = [
        enriched_chunk("a", [1.0, 0.0], "neural network architecture"),
        enriched_chunk("b", [0.9, 0.1], "machine learning paradigms"),
    ]
    roots = [
        ClusterTreeNode(id="A", name="Neural Networks", chunk_ids=["a"]),
        ClusterTreeNode(id="B", name="Machine Learning", chunk_ids=["b"]),
    ]
    judge = FakeJudge("merge")

    result = RegionMerger(judge).merge(roots, chunks)

    assert len(result) == 1
    assert result[0].chunk_ids == ["a", "b"]
    assert result[0].children == []


def test_region_merger_bad_json_defaults_keep_separate():
    class BadJudge:
        model = "fake-model"
        calls = 0

        def judge_region_pair(self, *_args):
            self.calls += 1
            return "```json\nnot-json\n```"

    chunks = [
        enriched_chunk("a", [1.0, 0.0], "neural network architecture"),
        enriched_chunk("b", [0.9, 0.1], "machine learning paradigms"),
    ]
    roots = [
        ClusterTreeNode(id="A", name="Neural Network Architectures", chunk_ids=["a"]),
        ClusterTreeNode(id="B", name="Machine Learning Paradigms", chunk_ids=["b"]),
    ]
    judge = BadJudge()

    result = RegionMerger(judge).merge(roots, chunks)

    assert judge.calls == 1
    assert [root.id for root in result] == ["A", "B"]
