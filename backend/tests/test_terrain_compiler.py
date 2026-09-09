from __future__ import annotations

import time
from pathlib import Path
from os import PathLike

from src.harvester.manifest import HarvestManifest
from src.terrain import TerrainCompiler
from src.terrain.utils.namer import ClusterNamer
from src.terrain.utils.store import TerrainStore


def write_doc(root: Path, name: str, text: str) -> str:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def seed_manifest(root: str | PathLike[str]) -> None:
    root = Path(root)
    manifest = HarvestManifest(root / "harvest-manifest.db")
    try:
        # ── Cluster A: Document Intelligence / Invoice Extraction ──────────────────

        p1 = write_doc(
            root,
            "normalized/confluence/acme_sales_notes.md",
            """# ACME Corp — Sales & Document Intelligence Notes

        ## Overview

        ACME Corp is one of our largest enterprise prospects in the construction supply chain vertical.
        Primary contact is Thomas Brauer (VP of Operations) and secondary is Lena Fischer (Finance Lead).
        The deal is currently in late-stage evaluation. Contract value estimated at €120k ARR.

        ## Problem Statement

        ACME processes roughly 4,000 supplier invoices per month across 6 regional warehouses.
        Currently, their AP team manually re-keys line items from PDFs into SAP. Error rate is
        estimated at 2.1%, leading to reconciliation delays and strained supplier relationships.
        They have tried two off-the-shelf OCR tools in the past (ABBYY and Kofax) but neither
        handled multi-language invoices (German/Italian) or non-standard layouts reliably.

        ## Our Proposed Solution

        We proposed our Document Intelligence pipeline, which covers:
        - Automated invoice ingestion from email, SFTP, and supplier portals
        - Layout-aware extraction using our fine-tuned LayoutLM model
        - Line-item normalization against their SAP item master
        - Human-in-the-loop review queue for low-confidence extractions
        - Audit trail and explainability panel for finance compliance

        During the demo, Thomas was particularly impressed by the table extraction on a complex
        Italian invoice with merged cells. Lena had concerns about GDPR data residency — we need
        to confirm that our EU deployment can guarantee data stays within Frankfurt region.

        ## Action Items

        - Erekle to prepare a data residency confirmation letter by end of week
        - Schedule a technical deep-dive with ACME's IT architect (Markus Vogel)
        - Send 3 reference customers in the manufacturing sector
        - Prepare ROI model: assume 80% reduction in manual keying time, €35/hr labor cost
        - Follow up on the 2 sample invoice batches ACME shared — extraction results pending QA

        ## Open Issues

        The two invoice batches provided by ACME contain some edge cases we haven't seen before:
        Hungarian VAT numbers formatted in a non-standard way, and one supplier who embeds line
        items as an image inside a PDF rather than as selectable text. The image-PDF case is
        going to require our vision extraction path, which adds ~400ms latency per document.
        Erekle will loop in the ML team to confirm throughput SLA can still be met.

        ## Next Meeting

        Demo follow-up call scheduled for Thursday 14:00 CET. Attendees: Thomas, Lena, Erekle,
        and Giorgi from our solutions engineering team.
        """,
        )

        p2 = write_doc(
            root,
            "normalized/notion/invoice_extraction_research.md",
            """# Invoice Extraction — Internal Research Notes

        ## Background

        This page consolidates findings from our ongoing R&D effort to improve extraction accuracy
        on long-tail invoice formats. Updated continuously by the ML team.

        ## Dataset Statistics

        Current training corpus: 210,000 invoices across 14 languages.
        - 68% are standard single-vendor, single-currency layouts
        - 19% are multi-page with running totals across pages
        - 8% are scanned PDFs (requires OCR pre-processing)
        - 5% are image-only (embedded JPEG/PNG inside PDF shell)

        Average extraction F1 on held-out test set: 0.912 for header fields, 0.874 for line items.
        Lowest performance observed on: handwritten annotations, colored table backgrounds,
        and invoices with non-Latin scripts (Arabic, Japanese) where bounding box alignment drifts.

        ## Chunking Strategy for Long Invoices

        Invoices longer than 12 pages are split at logical page-group boundaries before passing
        to the extraction model. We use a rule-based splitter that detects "subtotal" and
        "continued on next page" markers to find clean cut points. This avoids splitting a
        line-item table mid-row, which previously caused ~3% of line items to be dropped.

        ## Key Findings — Last Sprint

        1. Fine-tuning on ACME's Hungarian VAT format improved F1 from 0.61 to 0.89 on that subset.
        2. The image-in-PDF path now routes through our vision model (Claude claude-sonnet-4-20250514) for
        initial layout detection, then falls back to LayoutLM for field extraction. End-to-end
        latency: 380ms average, P99 at 910ms — within SLA.
        3. Confidence calibration: we retrained the calibration layer and reduced ECE from 0.14 to 0.07.
        Human review queue volume dropped by 22% as a result.

        ## Open Questions

        - Should we expose a "layout cluster" label to end users so they can audit which template
        family a new invoice was matched to? Thomas at ACME asked about this for explainability.
        - Merging the scanned-PDF and image-only pipelines into a single vision-first path is on
        the roadmap for Q3. Need to benchmark latency impact before committing.
        """,
        )

        # ── Cluster B: Image QA / Defect Detection ────────────────────────────────

        p3 = write_doc(
            root,
            "normalized/notion/sitelens_image_qa.md",
            """# Sitelens — Image QA & Defect Detection

        ## Project Summary

        Sitelens is our computer vision product targeted at infrastructure inspection.
        It analyzes images and video frames captured by field engineers to automatically
        detect structural defects: cracks, spalling, delamination, corrosion, and joint failures.
        The project has been in active development for 14 months.

        ## Customer Context

        Two enterprise customers are currently in pilot:
        - **Terna** (Italian electricity grid operator): using Sitelens to inspect high-voltage
        pylon foundations. Their inspection teams capture ~8,000 images per quarter per region.
        Current workflow: manual review by a senior engineer, taking 3-4 days per batch.
        With Sitelens, initial triage is done in under 2 hours.
        - **Hilti** (construction tools & fasteners): exploring use of Sitelens for quality control
        on their anchor bolt production line. This is a different use case — manufacturing QA
        rather than infrastructure inspection — so the defect taxonomy needs to be extended.
        Hilti is not yet confirmed as a paying pilot; contract discussion is ongoing.

        There is a third company that has expressed interest but I need to double-check —
        it may have been Hilti's subsidiary or a separate utility company from Germany.
        Giorgi is following up to clarify before the next steering committee meeting.

        ## Current Model Performance

        Detection model: YOLOv8-based with domain adaptation on our proprietary defect dataset.
        - Crack detection mAP@0.5: 0.87 (target: 0.90)
        - Spalling detection mAP@0.5: 0.81 (target: 0.85)
        - Corrosion detection mAP@0.5: 0.79 (target: 0.85)
        - False positive rate: 4.2% (Terna's tolerance: <5%, so currently within spec)

        Terna's QA team has flagged that in low-light tunnel images the model struggles.
        We collected 600 additional labeled tunnel images last sprint; retraining is in progress.

        ## Feedback from Terna Review Session

        The Terna team was unsatisfied with the current review interface. Specific complaints:
        1. No ability to zoom into a defect bounding box without losing context of the full image
        2. Severity score (1–5) is not explained anywhere in the UI — engineers don't trust it
        3. Export to their internal inspection report format (a proprietary XML schema) is missing

        We need to address all three before the end of Q2 or risk losing the contract renewal.
        Action owner: product team lead. Engineering estimate: 3 sprints.

        ## Investor Demo Preparation

        Two investors have asked for a live demo of Sitelens at the upcoming Series A pitch.
        We will demonstrate crack detection on a live video feed using a sample bridge inspection
        video. The ML team needs to ensure the model checkpoint from last week (v2.3.1) is stable
        and deployed to the demo environment. Do not use the experimental v2.4 branch — it has
        a known regression on high-contrast images.
        """,
        )

        p4 = write_doc(
            root,
            "normalized/confluence/sitelens_model_architecture.md",
            """# Sitelens — Model Architecture & Training Infrastructure

        ## Architecture Overview

        The Sitelens defect detection stack consists of three stages:

        ### Stage 1 — Preprocessing
        Raw images from field devices arrive in varying resolutions (1080p to 4K) and lighting
        conditions. The preprocessing pipeline normalizes brightness using CLAHE (Contrast Limited
        Adaptive Histogram Equalization), applies camera-specific lens distortion correction using
        calibration files stored per device ID, and resizes to 1280×1280 before inference.

        ### Stage 2 — Defect Detection
        We use a YOLOv8-Large backbone fine-tuned on our proprietary DefectNet-22k dataset.
        DefectNet-22k contains 22,400 labeled images across 9 defect categories sourced from
        infrastructure inspection archives provided by Terna, a Swiss cantonal road authority,
        and two anonymized industrial partners.

        Training configuration:
        - Batch size: 32 (gradient accumulation over 4 steps → effective 128)
        - Learning rate: 1e-4 with cosine annealing, warmup 5 epochs
        - Augmentation: mosaic, random flip, HSV jitter, cutout, MixUp (α=0.2)
        - Hardware: 4× A100 80GB, DDP training, ~18 hours per full run

        ### Stage 3 — Post-Processing & Severity Scoring
        Detected bounding boxes are passed to a lightweight MLP severity scorer.
        Features: bounding box area relative to component area, defect class, confidence score,
        aspect ratio, and distance from nearest structural joint (computed from the segmentation
        mask output by a separate component segmentation model).

        The severity scorer outputs a 1–5 ordinal score. This model was trained on 3,200
        manually graded examples from Terna's senior engineers. Inter-annotator agreement κ=0.71.

        ## Known Issues

        - Severity scorer confidence is poorly calibrated for score=3 (the ambiguous middle case).
        Engineers distrust this score specifically. Calibration retraining is planned.
        - The component segmentation model was trained only on above-ground infrastructure.
        It fails on underground utility tunnels, which explains the Terna tunnel image issues.
        A targeted collection drive for tunnel images is underway (target: 2,000 new images).

        ## Roadmap

        Q3: Merge preprocessing and detection into a single ONNX export for on-device inference.
            This is required for Hilti's production line use case where cloud latency is unacceptable.
        Q4: Add temporal defect tracking — linking detections across inspection sessions to show
            defect growth over time. This is the feature Terna cares most about long-term.
        """,
        )

        p5 = write_doc(
            root,
            "normalized/hubspot/q2_pipeline_review.md",
            """# Q2 2024 Pipeline Review — Sales Team

        ## Executive Summary

        Total qualified pipeline as of week 18: €2.1M ARR across 14 active opportunities.
        Weighted pipeline (probability-adjusted): €870k. Team is tracking at 94% of Q2 target.
        Three deals are in final negotiation; one (ACME) is expected to close by end of May.

        ## Deal Breakdown

        ### Tier 1 — High Confidence (>70% probability)

        | Account        | ARR     | Stage             | Expected Close | Owner   |
        |----------------|---------|-------------------|----------------|---------|
        | ACME Corp      | €120k   | Contract Review   | May 31         | Erekle  |
        | Stadtwerke München | €85k | Verbal Commit    | Jun 7          | Giorgi  |
        | NordBau GmbH   | €60k    | Proposal Sent     | Jun 21         | Lena    |

        ACME is the most strategically important deal this quarter. It opens the door to the
        broader German manufacturing segment. Erekle has a strong relationship with Thomas Brauer.
        Main remaining risk: legal sign-off on data residency terms (GDPR Annex).

        Stadtwerke München deal is for our utility inspection module (Sitelens-adjacent use case).
        They want on-premise deployment, which complicates our standard SaaS pricing model.
        Giorgi is working with product to scope a hybrid deployment option.

        ### Tier 2 — Medium Confidence (40–70%)

        | Account           | ARR    | Stage            | Expected Close | Owner   |
        |-------------------|--------|------------------|----------------|---------|
        | Hilti AG          | €95k   | Technical Eval   | Jul 10         | Tamta   |
        | Brenntag SE       | €75k   | Discovery Done   | Jul 22         | Erekle  |
        | Terna SpA (expand)| €55k   | Renewal Upsell   | Jun 30         | Giorgi  |

        Hilti evaluation has been going well technically, but procurement is slow. Tamta should
        escalate to the economic buyer (CFO's office) if we don't hear back on the MSA by May 22.

        Terna upsell is contingent on their satisfaction with the Q2 Sitelens delivery.
        If we solve the review interface issues by end of May, Giorgi expects the expansion to
        convert without further negotiation.

        ## Risks & Mitigations

        1. **ACME GDPR annex delay**: Legal team to review and return by May 17. If delayed,
        push close date to June 14 and adjust forecast accordingly.
        2. **Hilti slow procurement**: Tamta to request an internal champion letter from the
        engineering director who sponsored the eval. This will unblock legal review.
        3. **Headcount risk**: Two SDRs are on PTO in late June, reducing outbound capacity.
        Compensate by prioritizing inbound leads from the Munich trade show (ConExpo, June 3–5).

        ## Next Steps

        - All-hands pipeline review every Monday 9:00 CET
        - Erekle to send ACME ROI model and reference contacts by May 15
        - Giorgi to finalize Stadtwerke hybrid deployment scoping by May 20
        - Tamta to send Hilti escalation email by May 22
        """,
        )

        p6 = write_doc(
            root,
            "normalized/confluence/platform_architecture.md",
            """# Platform Architecture — DocnosticAI Core Services

        ## Overview

        This document describes the high-level architecture of the Docnostic platform as of Q2 2024.
        The platform powers both the Document Intelligence product (invoice extraction, compliance checks,
        RFP analysis) and the Sitelens Image QA product. Shared infrastructure components are
        managed by the platform team; product-specific services are owned by the respective ML teams.

        ## Service Map
        """
        )

        manifest.upsert_document(
            "confluence",
            "a",
            "ACME Sales",
            source_url="https://example.test/a",
            content_hash="sha256:a",
            metadata={
                "parent_id": "customers",
                "parent_title": "Customers",
                "ancestors": [{"id": "doc-analysis", "title": "Document Analysis"}],
            },
        )
        manifest.set_normalized_path("confluence", "a", p1)
        manifest.upsert_document(
            "notion",
            "b",
            "Image QA",
            source_url="https://example.test/b",
            content_hash="sha256:b",
            metadata={"parent_id": "workspace", "parent_type": "workspace"},
        )
        manifest.set_normalized_path("notion", "b", p2)

        manifest.upsert_document(
            "notion",
            "c",
            "Image QA - Part 2",
            source_url="https://example.test/c",
            content_hash="sha256:c",
            metadata={"parent_id": "b", "parent_type": "document"},
        )
        manifest.set_normalized_path("notion", "c", p3)
        
        manifest.upsert_document(
            "notion",
            "d",
            " Sitelens — Model Architecture",
            source_url="https://example.test/d",
            content_hash="sha256:d",
            metadata={"parent_id": "workspace", "parent_type": "workspace"},
        )
        manifest.set_normalized_path("notion", "d", p4)
        
        manifest.upsert_document(
            "notion",
            "e",
            "Sales Pipeline - Q2",
            source_url="https://example.test/e",
            content_hash="sha256:e",
            metadata={"parent_id": "workspace", "parent_type": "workspace"},
        )
        manifest.set_normalized_path("notion", "e", p5)

        manifest.upsert_document(
            "confluence",
            "f",
            "Platform Architecture",
            source_url="https://example.test/f",
            content_hash="sha256:f",
            metadata={"parent_id": "workspace", "parent_type": "workspace"},
        )
        manifest.set_normalized_path("confluence", "f", p6)

    finally:
        manifest.close()


def test_terrain_compiler_builds_valid_json_and_state(tmp_path):
    seed_manifest(tmp_path)
    compiler = TerrainCompiler(data_dir=tmp_path, ai_mode="local")

    try:
        result = compiler.build()
    finally:
        compiler.store.close()

    terrain_path = Path(result.terrain_path)
    notes_path = Path(result.notes_path)
    render_data_path = Path(result.render_data_path)
    assert terrain_path.exists()
    assert notes_path.exists()
    assert render_data_path.exists()
    # Outputs land only under the data dir — never the repo working tree.
    assert terrain_path == tmp_path / "terrain.json"
    assert notes_path == tmp_path / "mocknotes.json"
    assert render_data_path == tmp_path / "render-data.json"
    assert result.stats.notes == 6
    assert result.stats.tagsTotal >= 1
    assert result.stats.regions >= 1
    assert (tmp_path / "terrain.db").exists()

    # ── Weighted many-to-many region membership ──────────────────────────
    import json as _json
    render = _json.loads(render_data_path.read_text())
    # arcs are RETAINED (the app/data layer derives related-tags from them);
    # only the 3D arc rendering was removed.
    assert "arcs" in render
    # tagRegionWeights is parallel to tagIndex and well-formed.
    trw = render["tagRegionWeights"]
    assert len(trw) == len(render["tagIndex"])
    assert len(render["tagAttentionScore"]) == len(render["tagIndex"])
    assert len(render["tagAttentionLevel"]) == len(render["tagIndex"])
    assert all("attentionScore" in r for r in render["regions"])
    assert all("attentionLevel" in r for r in render["regions"])
    region_count = len(render["regions"])
    for entries in trw:
        homes = [e for e in entries if e["isHome"]]
        # Every emitted tag has exactly one home region, weight 1.0.
        assert len(homes) == 1, entries
        assert homes[0]["weight"] == 1.0
        for e in entries:
            assert 0 <= e["regionIdx"] < region_count
            assert 0.0 <= e["weight"] <= 1.0
        # Sorted strongest-first.
        weights = [e["weight"] for e in entries]
        assert weights == sorted(weights, reverse=True)

    # Verify hierarchy shape and uniform node fields.
    import json
    knowledge_map = json.loads(terrain_path.read_text())
    assert knowledge_map["version"] == 2
    assert knowledge_map["tree"], "tree should be non-empty"

    def _walk(nodes):
        for node in nodes:
            yield node
            yield from _walk(node.get("children", []))

    for node in _walk(knowledge_map["tree"]):
        assert {"id", "name", "position", "height", "chunk_ids", "children"} <= set(node)
        assert "attentionScore" in node
        assert "attentionLevel" in node
        assert "signals" in node
        for tag in node.get("tags", []):
            assert "attentionScore" in tag
            assert "attentionLevel" in tag
            assert "signals" in tag

    signals = [
        signal
        for node in _walk(knowledge_map["tree"])
        for signal in node.get("signals", [])
    ]
    assert any(s["kind"] == "risk" for s in signals)
    assert any(s["kind"] == "todo" for s in signals)

    def _get_max_depth(nodes, current_depth=0):
        if not nodes:
            return current_depth
        return max(_get_max_depth(node.get("children", []), current_depth + 1) for node in nodes)
        
    assert _get_max_depth(knowledge_map["tree"]) >= 1
    names = {node["name"] for node in _walk(knowledge_map["tree"])}
    assert "R&D" not in names
    assert "Platform Architecture" not in names


def _minimal_knowledge_map(tag_region_weights):
    """A 1-region / 1-tag / 1-note KnowledgeMap that passes every per-model
    validator, parameterized only on the tag's regionWeights so a test can
    drive validate_bidirectional's new invariant."""
    from src.terrain.utils.models import (
        AggregateCounts, Bounds, KnowledgeMap, KnowledgeMapNotes, CompilerProvenance,
        Edges, Highlights, Note, Offset, Owner, Position, Stats, Tag, TreeNode,
    )

    tag = Tag(
        id="tag.a", label="A", type="concept", frequency=1, recencyScore=0.5,
        degree=0, elevation=10, offset=Offset(dx=0.0, dz=0.0), noteIds=["n-1"],
        regionWeights=tag_region_weights,
    )
    root = TreeNode(
        id="node_root", name="Root", level=0, summary="s",
        center=Position(x=0.0, z=0.0), radius=1.0, elevation=10,
        aggregateCounts=AggregateCounts(notes=1, sources=1, tags=1, subRegions=0),
        tags=[tag], children=[],
    )
    knowledge_map = KnowledgeMap(
        workspace="w", owner=Owner(name="n", role="r"), generatedAt="t",
        compiler=CompilerProvenance(version="1", extractor="e", clusterer="c"),
        bounds=Bounds(minX=0.0, maxX=1.0, minZ=0.0, maxZ=1.0),
        stats=Stats(regions=1, tagsTotal=1, notes=1, sources=1, edges=0),
        highlights=Highlights(), tree=[root], edges=Edges(),
    )
    notes = KnowledgeMapNotes(version=2, generatedAt="t", notes=[
        Note(id="n-1", title="t", source="obsidian", sourceUrl="u", author="a",
             createdAt="t", updatedAt="t", regionId="node_root",
             primaryTagId="tag.a", tagIds=["tag.a"], excerpt="e", wordCount=1),
    ])
    return knowledge_map, notes


def test_validate_bidirectional_region_weight_invariants():
    import pytest
    from src.terrain.utils.models import RegionWeight, validate_bidirectional

    # Valid: home points at the tag's own top-level region.
    knowledge_map, notes = _minimal_knowledge_map(
        [RegionWeight(regionId="node_root", weight=1.0, isHome=True)]
    )
    validate_bidirectional(knowledge_map, notes)  # no raise

    # home regionId doesn't match the tag's containing top-level region.
    knowledge_map, notes = _minimal_knowledge_map(
        [RegionWeight(regionId="node_other", weight=1.0, isHome=True)]
    )
    with pytest.raises(ValueError, match="home"):
        validate_bidirectional(knowledge_map, notes)

    # no isHome entry.
    knowledge_map, notes = _minimal_knowledge_map(
        [RegionWeight(regionId="node_root", weight=0.5, isHome=False)]
    )
    with pytest.raises(ValueError, match="exactly one"):
        validate_bidirectional(knowledge_map, notes)

    # references a non-top-level region id.
    knowledge_map, notes = _minimal_knowledge_map([
        RegionWeight(regionId="node_root", weight=1.0, isHome=True),
        RegionWeight(regionId="ghost", weight=0.6, isHome=False),
    ])
    with pytest.raises(ValueError, match="non-top-level"):
        validate_bidirectional(knowledge_map, notes)


def test_region_weight_rejects_out_of_range():
    import pytest
    from src.terrain.utils.models import RegionWeight

    with pytest.raises(Exception):
        RegionWeight(regionId="x", weight=1.5, isHome=False)


def test_region_weights_from_centroids_multi_region():
    """The weight math itself: home is forced to 1.0, other regions above the
    cosine threshold are included with their similarity, below are dropped, and
    output is home-first then strongest-first. (The local-mode seed corpus
    collapses to one top region, so the multi-region path is proven here.)"""
    import numpy as np
    from src.terrain.pipelines.compiler import _region_weights_from_centroids

    def unit(v):
        a = np.asarray(v, dtype=np.float32)
        return a / np.linalg.norm(a)

    home = unit([1.0, 0.0, 0.0])
    # ~0.6 cosine to home (above 0.45), ~0.0 cosine (below), and itself.
    near = unit([0.6, 0.8, 0.0])     # cos(home, near) = 0.6
    far = unit([0.0, 0.0, 1.0])      # cos(home, far)  = 0.0
    top_centroids = {"home": home, "near": near, "far": far}

    weights = _region_weights_from_centroids(home, top_centroids, "home")
    by_id = {w.regionId: w for w in weights}

    # Home present, weight 1.0, marked home, and FIRST.
    assert weights[0].regionId == "home"
    assert by_id["home"].weight == 1.0 and by_id["home"].isHome
    # 'near' included (≥0.45), 'far' excluded (<0.45).
    assert "near" in by_id and not by_id["near"].isHome
    assert by_id["near"].weight == round(float(home @ near), 3)
    assert "far" not in by_id
    # Sorted strongest-first overall.
    ws = [w.weight for w in weights]
    assert ws == sorted(ws, reverse=True)

    # No centroid → home-only (a tag with no embeddings still gets its home).
    only_home = _region_weights_from_centroids(None, top_centroids, "home")
    assert len(only_home) == 1 and only_home[0].isHome



def test_terrain_compiler_reuses_feature_and_embedding_cache(tmp_path):
    seed_manifest(tmp_path)
    store = TerrainStore(tmp_path / "terrain.db")
    compiler = TerrainCompiler(data_dir=tmp_path, store=store, ai_mode="local")

    try:
        compiler.build()
        feature_count_1 = store._conn.execute("SELECT COUNT(*) FROM chunk_features").fetchone()[0]
        embedding_count_1 = store._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        compiler.build()
        feature_count_2 = store._conn.execute("SELECT COUNT(*) FROM chunk_features").fetchone()[0]
        embedding_count_2 = store._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    finally:
        store.close()

    assert feature_count_2 == feature_count_1
    assert embedding_count_2 == embedding_count_1


class _FakeParallelNamer(ClusterNamer):
    """An OpenAI-shaped namer: exposes the store-free ``_call_*`` methods so the
    compiler takes its PARALLEL naming path (the local ``ClusterNamer`` has none
    and runs serially). Names are prefixed by KIND so a tag/region result
    collision would be directly visible. The small sleep forces thread overlap.
    """

    @staticmethod
    def _key(items) -> str:
        return items[0].chunk.id[:8] if items else "x"

    def _call_theme(self, items, fallback: str = "General"):
        time.sleep(0.005)
        return f"Theme {self._key(items)}", "theme summary"

    def _call_region(self, items, fallback: str = "Loose Notes"):
        time.sleep(0.005)
        return f"Region {self._key(items)}", "region summary"

    def _call_tag(self, items, fallback: str = "General", *, region_name=None, region_terms=None):
        time.sleep(0.005)
        return f"Tag {self._key(items)}", "tag blurb"


def test_fresh_recompile_ignores_caches(tmp_path):
    """A normal rebuild reuses the feature cache; ``fresh=True`` recomputes
    everything even when the cache is warm."""
    from src.terrain.preprocessing.extractor import FeatureExtractor

    class _CountingExtractor(FeatureExtractor):
        calls = 0

        def extract(self, chunk):
            type(self).calls += 1
            return super().extract(chunk)

    seed_manifest(tmp_path)
    store = TerrainStore(tmp_path / "terrain.db")
    ext = _CountingExtractor()
    compiler = TerrainCompiler(data_dir=tmp_path, store=store, ai_mode="local", extractor=ext)
    try:
        compiler.build()                       # cold cache → N extractions
        n_cold = _CountingExtractor.calls
        assert n_cold > 0

        compiler.build()                       # warm cache → no new extractions
        assert _CountingExtractor.calls == n_cold

        compiler.build(fresh=True)             # fresh → re-extract everything
        assert _CountingExtractor.calls == 2 * n_cold
    finally:
        store.close()


def _enriched_chunk(cid: str, doc_id: str):
    from src.terrain.utils.models import ChunkFeatures, EnrichedChunk, TerrainChunk

    chunk = TerrainChunk(
        id=cid, doc_id=doc_id, source_type="notion", source_id=doc_id,
        doc_title=f"Doc {doc_id}", content=f"content {cid}", content_hash=f"h-{cid}",
    )
    features = ChunkFeatures(
        summary=f"summary {cid}", tags=[f"topic-{cid}"], entities=[f"ent-{cid}"],
        tag_type_hint="concept",
    )
    return EnrichedChunk(chunk=chunk, features=features, embedding=[0.1, 0.2, 0.3])


def test_parallel_naming_keeps_tags_and_regions_separate(tmp_path, monkeypatch):
    """Regression: a depth>0 leaf is BOTH a tag job (named via name_tag) and a
    region node (named via name_region). Those two parallel results must not
    clobber each other — they're keyed by distinct namespaces. Built on a
    hand-made 2-level tree (root → leaf children) so a depth>0 tagged leaf is
    guaranteed, regardless of what the clusterer would emerge on real data.
    """
    from src.terrain.utils.models import ClusterTreeNode, SourceDocument

    monkeypatch.setenv("TERRAIN_LLM_CONCURRENCY", "4")
    store = TerrainStore(tmp_path / "terrain.db")
    compiler = TerrainCompiler(
        data_dir=tmp_path, store=store, ai_mode="local", namer=_FakeParallelNamer(store)
    )

    documents = [
        SourceDocument(id="doc1", source_type="notion", source_id="doc1", title="Doc 1"),
        SourceDocument(id="doc2", source_type="notion", source_id="doc2", title="Doc 2"),
    ]
    enriched = [_enriched_chunk("c1", "doc1"), _enriched_chunk("c2", "doc2")]
    leaf1 = ClusterTreeNode(id="L1", chunk_ids=["c1"])
    leaf2 = ClusterTreeNode(id="L2", chunk_ids=["c2"])
    root = ClusterTreeNode(id="R", chunk_ids=["c1", "c2"], children=[leaf1, leaf2])

    try:
        knowledge_map, _notes = compiler._derive_tree(
            documents, enriched, [root], progress=lambda _ev: None
        )
    finally:
        store.close()

    region_names: set[str] = set()
    tag_labels: set[str] = set()

    def _walk(nodes):
        for n in nodes:
            region_names.add(n.name)
            for t in n.tags:
                tag_labels.add(t.label)
            _walk(n.children)

    _walk(knowledge_map.tree)

    # Depth>0 leaves were both named (Region …) and tagged (Tag …) without
    # clobbering each other. A collision would make a leaf's region name equal
    # its tag label, surfacing as a cross-prefixed string in one of these sets.
    assert tag_labels, "expected tags on the leaves"
    assert all(lbl.startswith("Tag ") for lbl in tag_labels), tag_labels
    assert all(
        name.startswith(("Theme ", "Region ")) for name in region_names
    ), f"a region node carried a non-region name (collision): {region_names}"


class _RecordingNamer(_FakeParallelNamer):
    """Parallel-path namer that stamps every region note with a sentinel and
    records the ``child_tag_blurbs`` each region received — so a test can prove
    children compiled BEFORE their parents (the level-by-level barrier in
    ``_compile_summaries``). The sleep forces thread overlap; if a parent raced
    its child it would see ``child.summary`` instead of the ``COMPILED::`` note.
    """

    def compile_region_note(self, name, summary, members, *, child_tag_blurbs=None):
        time.sleep(0.005)
        self.region_inputs[name] = list(child_tag_blurbs or [])
        return f"COMPILED::{name}"


def test_compile_summaries_parallel_region_pass_sees_child_notes(tmp_path, monkeypatch):
    """A2 regression: region notes are compiled level-by-level (deepest first),
    so a parent region's note input reuses its children's *compiled* notes — not
    the summary fallback — even when the work fans out across threads. Also
    asserts every region/tag lands a compiled note + embedding.
    """
    from src.terrain.utils.models import ClusterTreeNode, SourceDocument

    monkeypatch.setenv("TERRAIN_LLM_CONCURRENCY", "4")
    store = TerrainStore(tmp_path / "terrain.db")
    namer = _RecordingNamer(store)
    namer.region_inputs = {}
    compiler = TerrainCompiler(data_dir=tmp_path, store=store, ai_mode="local", namer=namer)

    documents = [
        SourceDocument(id="doc1", source_type="notion", source_id="doc1", title="Doc 1"),
        SourceDocument(id="doc2", source_type="notion", source_id="doc2", title="Doc 2"),
    ]
    enriched = [_enriched_chunk("c1", "doc1"), _enriched_chunk("c2", "doc2")]
    leaf1 = ClusterTreeNode(id="L1", chunk_ids=["c1"])
    leaf2 = ClusterTreeNode(id="L2", chunk_ids=["c2"])
    root = ClusterTreeNode(id="R", chunk_ids=["c1", "c2"], children=[leaf1, leaf2])

    try:
        knowledge_map, _notes = compiler._derive_tree(
            documents, enriched, [root], progress=lambda _ev: None
        )
        compiler._compile_summaries(knowledge_map, enriched, progress=lambda _ev: None)
    finally:
        store.close()

    parents: list = []

    def _walk(nodes):
        for n in nodes:
            assert n.compiled_note, f"region {n.name!r} got no compiled note"
            assert n.embedding is not None, f"region {n.name!r} got no embedding"
            if n.children:
                parents.append(n)
            _walk(n.children)

    _walk(knowledge_map.tree)

    assert parents, "expected at least one parent region with children"
    # Every parent's note input must reference a child's COMPILED:: note, proving
    # the child compiled first. A broken (un-barriered) ordering would leave only
    # the child's summary in these blurbs.
    for parent in parents:
        blurbs = namer.region_inputs.get(parent.name, [])
        assert any("COMPILED::" in b for b in blurbs), (
            f"parent region {parent.name!r} did not see a child's compiled note "
            f"(race / missing barrier); saw: {blurbs}"
        )


def test_run_compile_units_actually_fans_out(tmp_path):
    """Speed mechanism: the shared compiled-notes helper runs `work` concurrently,
    so N sleepy items at concurrency C finish in ~N/C × sleep, not N × sleep. Tags,
    regions, and entities all route their cache-miss work through this helper — this
    is what turns the serial ~20-30 min compile-notes stage into minutes.
    """
    store = TerrainStore(tmp_path / "terrain.db")
    compiler = TerrainCompiler(data_dir=tmp_path, store=store, ai_mode="local")
    compiler._llm_concurrency = 8
    n, sleep_s = 24, 0.05
    results: list = []

    def work(u):
        time.sleep(sleep_s)  # stand in for an LLM + embed round-trip
        return u

    try:
        t0 = time.monotonic()
        compiler._run_compile_units(
            list(range(n)), work, lambda _u, r: results.append(r),
            cancel=None, parallel=True,
        )
        parallel_s = time.monotonic() - t0
    finally:
        store.close()

    assert sorted(results) == list(range(n))         # every unit written back
    serial_s = n * sleep_s                            # 1.2s if it had run serially
    assert parallel_s < serial_s / 3, (              # ~0.15s ideal; generous bound
        f"fan-out did not engage: {parallel_s:.2f}s vs serial {serial_s:.2f}s"
    )


def test_enrich_emits_two_phase_progress_during_extraction(tmp_path):
    """Regression for the 'stuck at 4%' freeze: on a fresh corpus the enrich
    stage must emit progress DURING the extraction phase (not just once the
    first embedding batch lands). It now reports two sub-phases — 'extract'
    then 'embed' — each starting at done=0 and ticking up to its total.
    """
    from src.terrain.utils.models import TerrainChunk

    compiler = TerrainCompiler(data_dir=tmp_path, ai_mode="local")
    compiler._fresh = True  # force real extract + embed, no cache short-circuit
    chunks = [
        TerrainChunk(
            id=f"c{i}", doc_id=f"d{i}", source_type="notion", source_id=f"d{i}",
            doc_title=f"Doc {i}", content=f"content number {i} " * 20,
            content_hash=f"h-{i}",
        )
        for i in range(12)
    ]

    events: list = []
    compiler._enrich(chunks, progress=events.append)

    frames = [
        e for e in events
        if e.get("stage") == "enrich" and e.get("type") in (None, "progress")
    ]
    extract = [e for e in frames if e.get("phase") == "extract"]
    embed = [e for e in frames if e.get("phase") == "embed"]

    # Leaves the pre-enrich % immediately (first frame is extract done=0).
    assert frames[0]["phase"] == "extract" and frames[0]["done"] == 0
    # Extraction shows motion and completes — this is the part that froze before.
    assert any(e["done"] > 0 for e in extract)
    assert max(e["done"] for e in extract) == len(chunks) == extract[0]["total"]
    # Embedding phase reports its own start + completion.
    assert embed and embed[0]["done"] == 0
    assert max(e["done"] for e in embed) == embed[-1]["total"]


def test_secondary_assignments_do_not_inflate_tag_frequency(tmp_path):
    from src.terrain.utils.models import ClusterTreeNode, SourceDocument

    store = TerrainStore(tmp_path / "terrain.db")
    compiler = TerrainCompiler(data_dir=tmp_path, store=store, ai_mode="local")
    documents = [
        SourceDocument(id="doc1", source_type="notion", source_id="doc1", title="Doc 1"),
        SourceDocument(id="doc2", source_type="notion", source_id="doc2", title="Doc 2"),
    ]
    c1 = _enriched_chunk("c1", "doc1")
    c2 = _enriched_chunk("c2", "doc2")
    c1.chunk.region_assignments = ["R1", "R2"]
    root1 = ClusterTreeNode(id="R1", chunk_ids=["c1"])
    root2 = ClusterTreeNode(id="R2", chunk_ids=["c2"])

    try:
        knowledge_map, _notes = compiler._derive_tree(
            documents,
            [c1, c2],
            [root1, root2],
            progress=lambda _ev: None,
        )
    finally:
        store.close()

    tags = [tag for root in knowledge_map.tree for tag in root.tags]
    assert sorted(tag.frequency for tag in tags) == [1, 1]
    assert sorted(len(tag.noteIds) for tag in tags) == [1, 1]


def test_effective_modified_prefers_authored_date_for_obsidian(tmp_path):
    from datetime import date

    from src.terrain.utils.models import SourceDocument

    compiler = TerrainCompiler(data_dir=tmp_path, ai_mode="local")

    bulk_mtime = "2026-06-20T00:00:00+00:00"  # uniform copy timestamp

    # 1. Frontmatter date wins over mtime (PyYAML yields a date object).
    fm = SourceDocument(
        id="d1", source_type="obsidian", source_id="s1", title="Board Update",
        source_modified=bulk_mtime, metadata={"Date": date(2026, 1, 15)},
    )
    assert compiler._effective_modified(fm) == "2026-01-15"

    # 2. No frontmatter → ISO date in the filename/title wins over mtime.
    titled = SourceDocument(
        id="d2", source_type="obsidian", source_id="s2",
        title="1on1 Nadia - 2026-05-19", source_modified=bulk_mtime, metadata={},
    )
    assert compiler._effective_modified(titled) == "2026-05-19"

    # 3. Neither → fall back to mtime.
    bare = SourceDocument(
        id="d3", source_type="obsidian", source_id="s3",
        title="Code Review Standards", source_modified=bulk_mtime, metadata={},
    )
    assert compiler._effective_modified(bare) == bulk_mtime

    # 4. Non-Obsidian sources are untouched (they carry real modified times).
    notion = SourceDocument(
        id="d4", source_type="notion", source_id="s4",
        title="Spec 2026-05-19", source_modified=bulk_mtime, metadata={},
    )
    assert compiler._effective_modified(notion) == bulk_mtime


def test_emitted_terrain_json_is_lean_and_vectors_persisted(tmp_path):
    """V0.9: terrain.json carries no inline vectors (they were ~98% of the
    file); raw graph-node embeddings land in the graph_node_vectors table."""
    import json

    seed_manifest(tmp_path)
    compiler = TerrainCompiler(data_dir=tmp_path, ai_mode="local")
    try:
        result = compiler.build()
        vectors = compiler.store.load_graph_node_vectors()
    finally:
        compiler.store.close()

    knowledge_map = json.loads(Path(result.terrain_path).read_text())

    def _has_vector_keys(obj) -> bool:
        if isinstance(obj, dict):
            if "embedding" in obj or "context_embedding" in obj:
                return True
            return any(_has_vector_keys(v) for v in obj.values())
        if isinstance(obj, list):
            return any(_has_vector_keys(v) for v in obj)
        return False

    assert not _has_vector_keys(knowledge_map), "terrain.json must not serialize vectors"
    assert vectors, "graph-node vectors must be persisted to terrain.db"
    graph_ids = {n["id"] for n in knowledge_map["graph"]["nodes"]}
    assert set(vectors) <= graph_ids


def test_iso_date_in_text_ignores_id_like_tokens():
    from src.terrain.pipelines.compiler import _iso_date_in_text

    # ID-like tokens must not half-match ("PROJ-2024-1234" once yielded a
    # bogus "2024-12-01" anchor before the digit lookarounds).
    assert _iso_date_in_text("PROJ-2024-1234 rollout") is None
    assert _iso_date_in_text("ticket 2024-8934") is None
    assert _iso_date_in_text("ref 12026-05-01") is None
    # Real dates still resolve, with a missing day defaulting to the 1st.
    assert _iso_date_in_text("1on1 Nadia - 2026-05-19") == "2026-05-19"
    assert _iso_date_in_text("Board Update 2026-05") == "2026-05-01"


def test_effective_modified_drives_recency_spread(tmp_path):
    from src.terrain.utils.models import SourceDocument

    compiler = TerrainCompiler(data_dir=tmp_path, ai_mode="local")
    bulk_mtime = "2026-06-20T00:00:00+00:00"

    recent = SourceDocument(
        id="a", source_type="obsidian", source_id="sa",
        title="1on1 - 2026-06-18", source_modified=bulk_mtime, metadata={},
    )
    old = SourceDocument(
        id="b", source_type="obsidian", source_id="sb",
        title="1on1 - 2024-01-01", source_modified=bulk_mtime, metadata={},
    )

    # Same bulk mtime would give identical recency; authored dates separate them.
    assert compiler._max_recency([recent]) > compiler._max_recency([old])


def test_container_clustering_yields_one_region_per_folder(tmp_path, monkeypatch):
    """End-to-end: Obsidian folders seed the regions and survive derive — one
    colored region per work-stream folder, instead of one embedding blob."""
    from src.terrain.utils import clusterer as clusterer_module
    from src.terrain.utils.clusterer import TerrainClusterer
    from src.terrain.utils.models import SourceDocument

    # Keep leaf folders intact (don't sub-split) so the count is the folder count.
    monkeypatch.setattr(clusterer_module, "MAX_LEAF_CHUNKS", 1000)
    store = TerrainStore(tmp_path / "terrain.db")
    compiler = TerrainCompiler(data_dir=tmp_path, store=store, ai_mode="local")

    folders = ["01-Architecture", "02-Hiring", "03-Strategy"]
    documents = []
    enriched = []
    container_by_doc: dict[str, list[str]] = {}
    for folder_index, folder in enumerate(folders):
        for note_index in range(2):
            doc_id = f"{folder}-{note_index}"
            documents.append(
                SourceDocument(
                    id=doc_id, source_type="obsidian", source_id=doc_id,
                    title=f"Note {doc_id}", metadata={"folder": folder},
                )
            )
            ec = _enriched_chunk(f"c-{doc_id}", doc_id)
            embedding = [0.0, 0.0, 0.0]
            embedding[folder_index] = 1.0  # distinct centroid per folder
            ec.embedding = embedding
            enriched.append(ec)
            container_by_doc[doc_id] = [folder]

    roots = TerrainClusterer().cluster_with_containers(enriched, container_by_doc)
    assert len(roots) == len(folders)

    try:
        knowledge_map, _notes = compiler._derive_tree(
            documents, enriched, roots, progress=lambda _ev: None,
        )
    finally:
        store.close()

    assert knowledge_map.stats.regions == len(folders)
    assert sorted(r.aggregateCounts.notes for r in knowledge_map.tree) == [2, 2, 2]


if __name__ == "__main__":
    test_terrain_compiler_builds_valid_json_and_state(r"c:\Users\ersho\Documents\projects\mnemify\data\mock-docs")


# ── compiled-note cache: overlap-tolerant reuse + calendar-free keys ───────


def test_lookup_compiled_note_reuses_on_membership_churn(tmp_path, monkeypatch):
    """One added chunk changes the cluster node id (→ a new exact cache key).
    The note must still be reused via member overlap, re-saved under the new
    key with drift+1, and NOT re-synthesized."""
    from src.terrain.pipelines.compiler import _compile_cache_key, _member_hashes

    monkeypatch.delenv("TERRAIN_NOTE_REUSE_OVERLAP", raising=False)
    monkeypatch.delenv("TERRAIN_NOTE_REUSE_MAX_DRIFT", raising=False)
    store = TerrainStore(tmp_path / "terrain.db")
    compiler = TerrainCompiler(data_dir=tmp_path, store=store, ai_mode="local")
    pv = compiler._compile_prompt_version
    try:
        old_members = [_enriched_chunk(f"c{i}", f"d{i}") for i in range(20)]
        old_key = _compile_cache_key(pv, "tag", "tag.node_old", old_members)
        store.save_compiled_note(
            old_key, "tag", "synth", [1.0, 0.0], pv, members=_member_hashes(old_members)
        )

        new_members = old_members[:19] + [_enriched_chunk("c_new", "d_new")]
        new_key = _compile_cache_key(pv, "tag", "tag.node_new", new_members)
        assert new_key != old_key
        assert store.get_compiled_note(new_key) is None

        got = compiler._lookup_compiled_note(new_key, "tag", new_members)
        assert got == ("synth", [1.0, 0.0])
        # Carried forward: exact hit next time, drift bumped, origin members kept.
        assert store.get_compiled_note(new_key) == ("synth", [1.0, 0.0])
        row = store._conn.execute(
            "SELECT drift, member_count FROM compiled_notes WHERE cache_key=?", (new_key,)
        ).fetchone()
        assert row["drift"] == 1 and row["member_count"] == 20

        # Extractive kinds never fuzzy-match (fuzzy=False).
        ext_key = _compile_cache_key(pv, "tag_extractive", "tag.node_new", new_members)
        assert compiler._lookup_compiled_note(
            ext_key, "tag_extractive", new_members, fuzzy=False
        ) is None

        # fresh=True bypasses the cache entirely.
        compiler._fresh = True
        assert compiler._lookup_compiled_note(new_key, "tag", new_members) is None
        compiler._fresh = False

        # Disabled via env → exact-only.
        monkeypatch.setenv("TERRAIN_NOTE_REUSE_OVERLAP", "0")
        other_key = _compile_cache_key(pv, "tag", "tag.node_other", new_members[:19] + [_enriched_chunk("c_x", "d_x")])
        assert compiler._lookup_compiled_note(other_key, "tag", new_members) is None
    finally:
        store.close()


def test_lookup_compiled_note_drift_cap_forces_resynthesis(tmp_path, monkeypatch):
    from src.terrain.pipelines.compiler import _compile_cache_key, _member_hashes

    monkeypatch.setenv("TERRAIN_NOTE_REUSE_MAX_DRIFT", "2")
    monkeypatch.setenv("TERRAIN_NOTE_REUSE_OVERLAP", "0.5")
    store = TerrainStore(tmp_path / "terrain.db")
    compiler = TerrainCompiler(data_dir=tmp_path, store=store, ai_mode="local")
    pv = compiler._compile_prompt_version
    try:
        base = [_enriched_chunk(f"c{i}", f"d{i}") for i in range(20)]
        key0 = _compile_cache_key(pv, "region", "n0", base)
        store.save_compiled_note(key0, "region", "r", [0.5], pv, members=_member_hashes(base))
        # Two successive one-chunk churns reuse (drift 1, then 2) …
        m1 = base[:19] + [_enriched_chunk("a1", "da1")]
        assert compiler._lookup_compiled_note(_compile_cache_key(pv, "region", "n1", m1), "region", m1)
        m2 = base[:19] + [_enriched_chunk("a2", "da2")]
        assert compiler._lookup_compiled_note(_compile_cache_key(pv, "region", "n2", m2), "region", m2)
        # … but the third churn hits the cap on every candidate row → miss.
        m3 = base[:19] + [_enriched_chunk("a3", "da3")]
        assert compiler._lookup_compiled_note(_compile_cache_key(pv, "region", "n3", m3), "region", m3) is None
    finally:
        store.close()


def test_signals_cache_lines_ignore_severity():
    from src.terrain.utils.attention import signals_cache_lines, signals_digest
    from src.terrain.utils.models import AttentionSignal

    def sig(sev: int) -> AttentionSignal:
        return AttentionSignal(
            id="s1", kind="todo", title="Ship it", summary="", severity=sev,
            status="open", owner="ana", due_date="2026-09-10",
        )

    # Same signal, deadline moved inside the 7-day window → severity boosted.
    assert signals_digest([sig(40)]) != signals_digest([sig(55)])
    assert signals_cache_lines([sig(40)]) == signals_cache_lines([sig(55)])
    assert signals_cache_lines([sig(40)]) == ["todo: Ship it (open owner=ana)"]
