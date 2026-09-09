#!/usr/bin/env python3
"""Evaluation harness for the terrain's similarity thresholds.

Three constants in the compile pipeline are raw-cosine thresholds on
``text-embedding-3-*`` vectors, where even unrelated cluster centroids sit at
0.6–0.7 because every vector shares a large common component:

* ``region_merger.CANDIDATE_THRESHOLD`` (0.55) — on a real corpus 137 of 253
  region pairs qualified as merge candidates (only the top 40 are judged);
* ``clusterer.MULTI_REGION_SIMILARITY_THRESHOLD`` (0.45) — chunks pick up
  7–15 secondary regions;
* the layout MDS runs on raw centroid distances.

Whether an alternative metric (mean-centered cosine, chunk-to-chunk cosine)
is *better* is an empirical question. This script produces the data to answer
it against hand labels instead of assuming. It changes nothing in the pipeline.

Usage (from ``backend/``; reads ``.mnemify/terrain.json`` + ``terrain.db``):

    python scripts/threshold_eval.py pairs  --out pairs.csv
        every top-level region pair with raw / centered / cross-chunk cosine,
        names, 3 sample summaries each, and the latest merger verdict as a
        weak label. Fill the ``label`` column with same | related | distinct.

    python scripts/threshold_eval.py score  --labels pairs.csv
        per metric: AUC (same+related vs distinct) and the accuracy-maximising
        threshold, plus how many pairs each threshold would admit as
        merge candidates (compare with today's 0.55).

    python scripts/threshold_eval.py multi  --out chunks.csv [--sample 150]
        chunks with their primary region and the secondary regions they get
        under the current rule vs. two alternatives; label each secondary as
        y/n in ``label`` (semicolon-separated, same order as ``candidates``).
        ``score --labels chunks.csv --kind multi`` then reports per-rule precision.

    python scripts/threshold_eval.py layout
        raw vs mean-centered MDS: how often each region's nearest rendered
        neighbour is among its top-3 semantic neighbours, and Spearman rank
        correlation between layout distance and each semantic metric.

Labels are cheap for regions (≤ 253 pairs; 30–40 labelled pairs already give
a usable signal) — re-set a threshold only after that set exists.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.terrain.utils.clusterer import MULTI_REGION_SIMILARITY_THRESHOLD  # noqa: E402
from src.terrain.utils.region_merger import CANDIDATE_THRESHOLD  # noqa: E402

LABELS_POSITIVE = {"same", "related"}
LABELS_ALL = {"same", "related", "distinct"}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _norm(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n else v


def _gather(node: dict) -> list[str]:
    ids = list(node.get("chunk_ids") or [])
    for child in node.get("children") or []:
        ids.extend(_gather(child))
    return list(dict.fromkeys(ids))


class Corpus:
    def __init__(self, data_dir: Path):
        self.terrain = json.loads((data_dir / "terrain.json").read_text(encoding="utf-8"))
        self.con = sqlite3.connect(str(data_dir / "terrain.db"))
        self.con.row_factory = sqlite3.Row
        rows = self.con.execute(
            "SELECT c.id, c.doc_title, e.model, e.vector FROM chunks c "
            "JOIN embeddings e ON e.embedding_hash = c.embedding_hash"
        ).fetchall()
        models = defaultdict(int)
        for r in rows:
            models[r["model"]] += 1
        # Only the dominant embedding model is comparable within itself.
        self.model = max(models, key=models.get)
        self.emb: dict[str, np.ndarray] = {
            r["id"]: _norm(np.asarray(json.loads(r["vector"]), dtype=np.float32))
            for r in rows if r["model"] == self.model
        }
        self.title = {r["id"]: r["doc_title"] for r in rows}
        feats = self.con.execute(
            "SELECT c.id, f.features FROM chunks c "
            "JOIN chunk_features f ON f.content_hash = c.content_hash"
        ).fetchall()
        self.summary: dict[str, str] = {}
        for r in feats:
            try:
                self.summary[r["id"]] = (json.loads(r["features"]).get("summary") or "").strip()
            except Exception:  # noqa: BLE001
                pass
        self.roots = self.terrain["tree"]
        self.members = {r["id"]: [c for c in _gather(r) if c in self.emb] for r in self.roots}
        self.roots = [r for r in self.roots if self.members[r["id"]]]
        all_vecs = np.stack([self.emb[c] for r in self.roots for c in self.members[r["id"]]])
        self.global_mean = all_vecs.mean(axis=0)
        self.raw_centroid = {
            r["id"]: _norm(np.stack([self.emb[c] for c in self.members[r["id"]]]).mean(0))
            for r in self.roots
        }
        self.centered_centroid = {
            r["id"]: _norm((np.stack([self.emb[c] for c in self.members[r["id"]]]) - self.global_mean).mean(0))
            for r in self.roots
        }
        self.name = {r["id"]: r["name"] for r in self.roots}

    def cross_chunk_cos(self, a: str, b: str) -> float:
        va = np.stack([self.emb[c] for c in self.members[a]])
        vb = np.stack([self.emb[c] for c in self.members[b]])
        return float((va @ vb.T).mean())

    def sample_summaries(self, rid: str, k: int = 3) -> list[str]:
        out = []
        for c in self.members[rid]:
            s = self.summary.get(c)
            if s:
                out.append(s[:160])
            if len(out) >= k:
                break
        return out

    def latest_verdicts(self) -> dict[tuple[str, str], dict]:
        try:
            rows = self.con.execute(
                "SELECT * FROM merger_verdicts WHERE run_id = "
                "(SELECT run_id FROM merger_verdicts ORDER BY created_at DESC LIMIT 1)"
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        return {tuple(sorted((r["a_id"], r["b_id"]))): dict(r) for r in rows}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def auc(scores: list[float], positives: list[bool]) -> float:
    pos = [s for s, p in zip(scores, positives) if p]
    neg = [s for s, p in zip(scores, positives) if not p]
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def best_threshold(scores: list[float], positives: list[bool]) -> tuple[float, float]:
    """Threshold on `score >= t` that maximises accuracy; returns (t, accuracy)."""
    best = (float("nan"), 0.0)
    for t in sorted(set(scores)):
        acc = sum((s >= t) == p for s, p in zip(scores, positives)) / len(scores)
        if acc > best[1]:
            best = (t, acc)
    return best


def spearman(a: list[float], b: list[float]) -> float:
    def rank(x):
        order = np.argsort(x)
        r = np.empty(len(x))
        r[order] = np.arange(len(x))
        return r
    return float(np.corrcoef(rank(np.asarray(a)), rank(np.asarray(b)))[0, 1])


def classical_mds(distance: np.ndarray) -> np.ndarray:
    n = len(distance)
    j = np.eye(n) - np.ones((n, n)) / n
    b = -0.5 * j @ (distance ** 2) @ j
    vals, vecs = np.linalg.eigh(b)
    idx = np.argsort(vals)[::-1][:2]
    return vecs[:, idx] * np.sqrt(np.maximum(vals[idx], 0))


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_pairs(corpus: Corpus, out: Path) -> None:
    verdicts = corpus.latest_verdicts()
    rows = []
    for a, b in combinations(corpus.roots, 2):
        ia, ib = a["id"], b["id"]
        v = verdicts.get(tuple(sorted((ia, ib))), {})
        rows.append({
            "a_id": ia, "b_id": ib,
            "a_name": corpus.name[ia], "b_name": corpus.name[ib],
            "a_chunks": len(corpus.members[ia]), "b_chunks": len(corpus.members[ib]),
            "raw_centroid_cos": round(float(corpus.raw_centroid[ia] @ corpus.raw_centroid[ib]), 4),
            "centered_centroid_cos": round(float(corpus.centered_centroid[ia] @ corpus.centered_centroid[ib]), 4),
            "cross_chunk_cos": round(corpus.cross_chunk_cos(ia, ib), 4),
            "merger_verdict": v.get("decision", ""),
            "merger_reason": (v.get("reason") or "")[:200],
            "a_summaries": " || ".join(corpus.sample_summaries(ia)),
            "b_summaries": " || ".join(corpus.sample_summaries(ib)),
            "label": "",
        })
    rows.sort(key=lambda r: -r["raw_centroid_cos"])
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    n_cand = sum(r["raw_centroid_cos"] >= CANDIDATE_THRESHOLD for r in rows)
    print(f"wrote {len(rows)} pairs → {out}")
    print(f"current merger threshold {CANDIDATE_THRESHOLD}: {n_cand}/{len(rows)} pairs are candidates")
    print("fill the `label` column with same | related | distinct, then run: score --labels", out)


def cmd_score_pairs(labels_path: Path) -> None:
    with labels_path.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh)]
    labelled = [r for r in rows if r.get("label", "").strip().lower() in LABELS_ALL]
    if len(labelled) < 10:
        print(f"only {len(labelled)} labelled pairs — need ≥10 (ideally ≥30) for a meaningful score")
        return
    positives = [r["label"].strip().lower() in LABELS_POSITIVE for r in labelled]
    print(f"{len(labelled)} labelled pairs ({sum(positives)} same/related, {len(positives) - sum(positives)} distinct)\n")
    print(f"{'metric':24s} {'AUC':>6s} {'best_t':>7s} {'acc@t':>6s}  candidates admitted @best_t / total")
    for metric in ("raw_centroid_cos", "centered_centroid_cos", "cross_chunk_cos"):
        scores = [float(r[metric]) for r in labelled]
        a = auc(scores, positives)
        t, acc = best_threshold(scores, positives)
        admitted = sum(float(r[metric]) >= t for r in rows)
        print(f"{metric:24s} {a:6.3f} {t:7.3f} {acc:6.3f}  {admitted}/{len(rows)}")
    weak = [r for r in rows if r.get("merger_verdict")]
    if weak:
        agree = sum(
            (r["merger_verdict"] in ("merge", "nest")) == (r["label"].strip().lower() in LABELS_POSITIVE)
            for r in labelled if r.get("merger_verdict")
        )
        n = sum(1 for r in labelled if r.get("merger_verdict"))
        if n:
            print(f"\nmerger LLM verdict agrees with your label on {agree}/{n} judged pairs")


def cmd_multi(corpus: Corpus, out: Path, sample: int) -> None:
    rng = np.random.default_rng(7)
    primary: dict[str, str] = {}
    for r in corpus.roots:
        for c in corpus.members[r["id"]]:
            primary.setdefault(c, r["id"])
    chunk_ids = list(primary)
    pick = rng.choice(len(chunk_ids), size=min(sample, len(chunk_ids)), replace=False)
    ids = [r["id"] for r in corpus.roots]
    raw_c = np.stack([corpus.raw_centroid[i] for i in ids])
    cen_c = np.stack([corpus.centered_centroid[i] for i in ids])
    rows = []
    for k in pick:
        cid = chunk_ids[k]
        v = corpus.emb[cid]
        raw_scores = raw_c @ v
        cen_scores = cen_c @ _norm(v - corpus.global_mean)
        p = ids.index(primary[cid])
        rule_current = [ids[i] for i in np.argsort(-raw_scores) if i != p and raw_scores[i] >= MULTI_REGION_SIMILARITY_THRESHOLD]
        rule_margin = [ids[i] for i in np.argsort(-raw_scores) if i != p and raw_scores[i] >= raw_scores[p] - 0.05]
        rule_centered = [ids[i] for i in np.argsort(-cen_scores) if i != p and cen_scores[i] >= 0.30]
        candidates = list(dict.fromkeys(rule_current + rule_margin + rule_centered))
        rows.append({
            "chunk_id": cid, "doc_title": corpus.title.get(cid, ""),
            "summary": corpus.summary.get(cid, "")[:200],
            "primary_region": corpus.name[primary[cid]],
            "candidates": "; ".join(corpus.name[i] for i in candidates),
            "rule_current_0.45": "; ".join(corpus.name[i] for i in rule_current),
            "rule_margin_0.05": "; ".join(corpus.name[i] for i in rule_margin),
            "rule_centered_0.30": "; ".join(corpus.name[i] for i in rule_centered),
            "label": "",
        })
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    avg = np.mean([len(r["rule_current_0.45"].split("; ")) if r["rule_current_0.45"] else 0 for r in rows])
    print(f"wrote {len(rows)} chunks → {out}; current rule gives {avg:.1f} secondary regions per chunk on average")
    print("label: for each name in `candidates` (same order) write y or n, separated by ';'")


def cmd_score_multi(labels_path: Path) -> None:
    with labels_path.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("label", "").strip()]
    if not rows:
        print("no labelled rows")
        return
    stats = {k: [0, 0] for k in ("rule_current_0.45", "rule_margin_0.05", "rule_centered_0.30")}
    for r in rows:
        cands = [c.strip() for c in r["candidates"].split(";") if c.strip()]
        labs = [x.strip().lower() for x in r["label"].split(";")]
        good = {c for c, l in zip(cands, labs) if l == "y"}
        for rule in stats:
            chosen = {c.strip() for c in r[rule].split(";") if c.strip()}
            stats[rule][0] += len(chosen & good)
            stats[rule][1] += len(chosen)
    print(f"{len(rows)} labelled chunks")
    for rule, (hit, n) in stats.items():
        prec = hit / n if n else float("nan")
        print(f"  {rule:20s} precision={prec:.2f}  ({hit}/{n} secondary assignments judged correct)")


def cmd_layout(corpus: Corpus) -> None:
    ids = [r["id"] for r in corpus.roots]
    n = len(ids)
    raw = np.stack([corpus.raw_centroid[i] for i in ids])
    cen = np.stack([corpus.centered_centroid[i] for i in ids])
    d_raw = 1 - raw @ raw.T
    d_cen = 1 - cen @ cen.T
    d_xc = np.zeros((n, n))
    for a in range(n):
        for b in range(a + 1, n):
            d_xc[a, b] = d_xc[b, a] = 1 - corpus.cross_chunk_cos(ids[a], ids[b])
    for label, dm in (("raw centroid (current)", d_raw), ("mean-centered centroid", d_cen)):
        xy = classical_mds(dm)
        layout = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1])
        iu = np.triu_indices(n, 1)
        print(f"\n=== MDS on {label} ===")
        for sem_label, sem in (("raw", d_raw), ("centered", d_cen), ("cross-chunk", d_xc)):
            print(f"  Spearman(layout dist, {sem_label} dist) = {spearman(layout[iu].tolist(), sem[iu].tolist()):.3f}")
        agree = 0
        for a in range(n):
            nearest_layout = int(np.argsort(np.where(np.arange(n) == a, np.inf, layout[a]))[0])
            top3 = set(np.argsort(np.where(np.arange(n) == a, np.inf, d_xc[a]))[:3].tolist())
            agree += nearest_layout in top3
        print(f"  nearest rendered neighbour ∈ top-3 cross-chunk neighbours: {agree}/{n}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=".mnemify")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pairs"); p.add_argument("--out", default="pairs.csv")
    p = sub.add_parser("score"); p.add_argument("--labels", required=True); p.add_argument("--kind", choices=["pairs", "multi"], default="pairs")
    p = sub.add_parser("multi"); p.add_argument("--out", default="chunks.csv"); p.add_argument("--sample", type=int, default=150)
    sub.add_parser("layout")
    args = ap.parse_args()
    if args.cmd == "score":
        (cmd_score_multi if args.kind == "multi" else cmd_score_pairs)(Path(args.labels))
        return
    corpus = Corpus(Path(args.data_dir))
    print(f"corpus: {len(corpus.roots)} top-level regions, {len(corpus.emb)} chunks ({corpus.model})")
    if args.cmd == "pairs":
        cmd_pairs(corpus, Path(args.out))
    elif args.cmd == "multi":
        cmd_multi(corpus, Path(args.out), args.sample)
    elif args.cmd == "layout":
        cmd_layout(corpus)


if __name__ == "__main__":
    main()
