"""On-device embedding model lifecycle — ``/api/embeddings/local``.

The consent step for users without an ``OPENAI_API_KEY``: the compile-start
route refuses with ``code="openai_key_missing"``, the UI explains the trade-off
(runs on this PC, English-only, results differ from OpenAI) and links to
Settings; only when the user agrees does the frontend call ``prepare`` here,
which downloads the ~67 MB model in the background. ``GET`` is polled until
``status == "ready"``, then the compile is retried with the local model.

``set_default`` persists ``embedding_model`` in the saved compile settings so
later compiles (schedules, auto-compile-after-harvest) and Ask queries use the
same embedding space without asking again.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from src.terrain.utils.local_embedder import (
    LOCAL_EMBEDDING_MODEL,
    local_model_status,
    prepare_local_model,
)

router = APIRouter()


class PrepareBody(BaseModel):
    #: Also save the local model as the compile default (Settings → AI & Models).
    set_default: bool = False
    #: With ``set_default``: also switch the saved compile engine (the dialog
    #: offers Claude when a keyless install is still on the OpenAI engine).
    ai_mode: Literal["claude", "anthropic"] | None = None


@router.get("/embeddings/local")
async def get_local_embeddings() -> dict:
    """Whether the on-device model is downloaded, plus any in-flight download."""
    return local_model_status()


@router.post("/embeddings/local/prepare")
async def prepare_local_embeddings(body: PrepareBody | None = None) -> dict:
    """Start (or report) the model download; optionally make it the default."""
    body = body or PrepareBody()
    if body.set_default:
        from src.api.routes_settings import _compile_settings_block
        from src.api.yaml_writer import upsert_compile

        settings = _compile_settings_block()
        changed = settings["embedding_model"] != LOCAL_EMBEDDING_MODEL
        settings["embedding_model"] = LOCAL_EMBEDDING_MODEL
        if body.ai_mode and settings["ai_mode"] != body.ai_mode:
            settings["ai_mode"] = body.ai_mode
            changed = True
        if changed:
            upsert_compile(settings)
    status = prepare_local_model()
    return {"ok": status["status"] != "failed", **status}
