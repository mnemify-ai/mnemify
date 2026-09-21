"""On-device embeddings (no API key) — the fallback when ``OPENAI_API_KEY`` is
not configured.

Anthropic has no embeddings endpoint, so a Claude-only user used to need an
OpenAI key purely for the embed step. This module runs ``BAAI/bge-small-en-v1.5``
locally through `fastembed` (ONNX Runtime, CPU, ~67 MB model, 384 dims).
English-only and a notch below ``text-embedding-3-large`` on clustering, which
the UI says out loud before the user opts in.

Two things live here:

* :class:`LocalEmbeddingClient` — the ``EmbeddingClient`` implementation the
  compiler/ask paths use. Same ``embed`` / ``embed_batch`` / ``hash`` contract as
  the OpenAI client; ``model`` is the settings alias so cache rows, the Ask index
  dimension guard and the settings value all agree.
* The download lifecycle (:func:`local_model_status`, :func:`prepare_local_model`)
  behind ``/api/embeddings/local``. The model is fetched only after the user
  agrees in the UI — never silently on install or on first compile.

The model files live under ``<home>/.mnemify/models`` (``paths.data_dir()``),
not the user's global Hugging Face cache, so "Open data folder" shows them and
a reset removes them.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from src import paths
from src.terrain.utils.embedder import EmbeddingClient
from src.utils.hashing import sha256_hash

logger = logging.getLogger(__name__)

#: The value stored in compile settings / cache rows / the compile-start body.
LOCAL_EMBEDDING_MODEL = "bge-small-en-v1.5"
#: The fastembed / Hugging Face id behind it.
LOCAL_EMBEDDING_HF_MODEL = "BAAI/bge-small-en-v1.5"
LOCAL_EMBEDDING_DIM = 384
LOCAL_EMBEDDING_SIZE_MB = 67
#: bge-small truncates at 512 tokens; the compiler's embedding text is a short
#: summary + entity lines, so this is a guard, not a working limit.
LOCAL_EMBEDDING_MAX_TOKENS = 512

OPENAI_EMBEDDING_MODELS: tuple[str, ...] = ("text-embedding-3-small", "text-embedding-3-large")
EMBEDDING_MODEL_CHOICES: tuple[str, ...] = (*OPENAI_EMBEDDING_MODELS, LOCAL_EMBEDDING_MODEL)


def is_local_embedding_model(name: str | None) -> bool:
    return name == LOCAL_EMBEDDING_MODEL


def models_dir() -> Path:
    """Where downloaded embedding models live. Resolved at call time (see the
    "no module binds a data path at import" rule in AGENTS.md)."""
    return paths.data_dir() / "models"


def _threads() -> int:
    # ONNX Runtime defaults vary by build; physical-core-ish is the sweet spot
    # for indexing throughput and doesn't hurt single-query latency.
    return max(1, (os.cpu_count() or 2) // 2)


def _load_fastembed():
    try:
        from fastembed import TextEmbedding
    except ImportError as e:  # pragma: no cover - dependency is in pyproject
        raise RuntimeError(
            "The fastembed package is required for on-device embeddings. "
            "Re-run setup.sh (or `uv sync` in backend/) to install it."
        ) from e
    return TextEmbedding


def _make_model(*, local_files_only: bool):
    """Construct the fastembed model. ``local_files_only=True`` never touches the
    network and raises when the files are not in ``models_dir()``."""
    TextEmbedding = _load_fastembed()
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    cache = models_dir()
    cache.mkdir(parents=True, exist_ok=True)
    return TextEmbedding(
        model_name=LOCAL_EMBEDDING_HF_MODEL,
        cache_dir=str(cache),
        threads=_threads(),
        local_files_only=local_files_only,
    )


def is_model_downloaded() -> bool:
    """True when the model files are already in ``models_dir()``. Cheap enough
    to call per request: a cached model loads in well under a second."""
    if not models_dir().exists():
        return False
    # fastembed logs a loud ERROR (via loguru) when the offline probe misses.
    # That is the expected answer here, and the status endpoint is polled, so
    # mute its logger for the probe only.
    try:
        from loguru import logger as _loguru
    except ImportError:  # pragma: no cover
        _loguru = None
    if _loguru is not None:
        _loguru.disable("fastembed")
    try:
        _make_model(local_files_only=True)
        return True
    except Exception:  # noqa: BLE001 - any failure means "not usable offline"
        return False
    finally:
        if _loguru is not None:
            _loguru.enable("fastembed")


# ─── Download lifecycle (behind /api/embeddings/local) ───────────────

class _DownloadState:
    status: str = "idle"  # idle | downloading | ready | failed
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    _thread: threading.Thread | None = None
    _lock = threading.Lock()


_download = _DownloadState()


def local_model_status() -> dict[str, Any]:
    """Snapshot for the UI: whether the model is present, and any in-flight
    download. ``downloaded`` is re-checked from disk unless a download is
    running (a half-written cache would otherwise flicker to true)."""
    downloading = _download.status == "downloading"
    downloaded = False if downloading else is_model_downloaded()
    status = "downloading" if downloading else ("ready" if downloaded else _download.status)
    if status == "ready" and not downloaded:
        status = "idle"
    return {
        "model": LOCAL_EMBEDDING_MODEL,
        "hf_model": LOCAL_EMBEDDING_HF_MODEL,
        "dim": LOCAL_EMBEDDING_DIM,
        "size_mb": LOCAL_EMBEDDING_SIZE_MB,
        "languages": "English",
        "downloaded": downloaded,
        "status": status,
        "error": _download.error if status == "failed" else None,
        "path": str(models_dir()),
    }


def prepare_local_model() -> dict[str, Any]:
    """Start downloading the model in a background thread (idempotent: a
    running or finished download is reported, not restarted)."""
    with _DownloadState._lock:
        if _download.status == "downloading":
            return local_model_status()
        if is_model_downloaded():
            _download.status = "ready"
            _download.error = None
            return local_model_status()
        _download.status = "downloading"
        _download.started_at = time.time()
        _download.finished_at = None
        _download.error = None
        t = threading.Thread(target=_download_worker, name="embed-model-download", daemon=True)
        _download._thread = t
        t.start()
    return local_model_status()


def _download_worker() -> None:
    try:
        logger.info("embeddings: downloading %s to %s", LOCAL_EMBEDDING_HF_MODEL, models_dir())
        _make_model(local_files_only=False)
        # Loading once proves the files are complete and warms nothing we keep;
        # the compile builds its own client.
        _download.status = "ready"
        logger.info("embeddings: %s ready", LOCAL_EMBEDDING_HF_MODEL)
    except Exception as e:  # noqa: BLE001
        logger.exception("embeddings: model download failed")
        _download.status = "failed"
        _download.error = str(e)[:400]
    finally:
        _download.finished_at = time.time()


# ─── EmbeddingClient ─────────────────────────────────────────────────

class LocalEmbeddingClient(EmbeddingClient):
    """``EmbeddingClient`` backed by fastembed's ONNX bge-small.

    Symmetric use (no query/passage prefixes) on purpose: the same vectors
    drive HDBSCAN clustering and the Ask cosine search, exactly as the OpenAI
    client is used, so a query embedded here lands in the same space as the
    compiled chunks.
    """

    model = LOCAL_EMBEDDING_MODEL
    _lock = threading.Lock()

    def __init__(self, dimensions: int | None = None, batch_size: int = 64):
        # ``dimensions`` is accepted for signature parity; bge-small is fixed.
        self.dimensions = LOCAL_EMBEDDING_DIM
        self.batch_size = batch_size
        self._model = None

    def hash(self, text: str) -> str:
        return sha256_hash(f"{self.model}:{self.dimensions}:{text}")

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    # local_files_only: a compile must never trigger a silent
                    # 67 MB download — the UI's consent step does that.
                    try:
                        self._model = _make_model(local_files_only=True)
                    except Exception as e:  # noqa: BLE001
                        raise RuntimeError(
                            "The on-device embedding model is not downloaded yet. "
                            "Open Settings → AI & Models and download it, or add an "
                            "OPENAI_API_KEY."
                        ) from e
        return self._model

    def embed(self, text: str, dimensions: int | None = None) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str], dimensions: int | None = None) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        out = [vec.astype(float).tolist() for vec in model.embed(texts, batch_size=self.batch_size)]
        if len(out) != len(texts):  # pragma: no cover - fastembed is order-preserving
            raise RuntimeError("local embedder returned a different number of vectors than inputs")
        return out
