"""/api/settings + /api/reset."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Literal
from src.terrain.agents.anthropic_clients import CLAUDE_MODEL_PATTERN, is_claude_model_ref

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import compile_orchestrator as compile_orch
from . import orchestrator as orch
from .compile_bus import compile_bus
from .event_bus import bus
from .yaml_writer import read_config, upsert_compile, upsert_retention


router = APIRouter()
logger = logging.getLogger(__name__)


_DATA_DIR = Path(".mnemify")
RETENTION_POLICY_DEFAULT = "keep"
RETENTION_GRACE_DAYS_DEFAULT = 7


def _retention_block() -> dict:
    """Read the ``data_retention`` block from YAML, falling back to defaults."""
    cfg = read_config()
    block = cfg.get("data_retention") or {}
    policy = block.get("on_source_delete") or RETENTION_POLICY_DEFAULT
    if policy not in ("keep", "purge"):
        policy = RETENTION_POLICY_DEFAULT
    grace = block.get("purge_grace_days")
    if not isinstance(grace, int) or grace < 0:
        grace = RETENTION_GRACE_DAYS_DEFAULT
    return {"on_source_delete": policy, "purge_grace_days": grace}


class RetentionUpdate(BaseModel):
    on_source_delete: Literal["keep", "purge"]
    purge_grace_days: int = Field(ge=0, le=365)


@router.get("/settings/retention")
async def get_retention() -> dict:
    """Return the current deletion policy + count of currently-deleted docs.

    Counts are scoped to ``harvest_status = 'deleted_at_source'`` across all
    sources so the UI can show "X documents marked deleted at source" alongside
    the policy controls.
    """
    from src.harvester.manifest import HarvestManifest
    from src.harvester.retention import count_deleted

    block = _retention_block()
    db_path = _DATA_DIR / "harvest-manifest.db"
    deleted_count = 0
    if db_path.exists():
        manifest = HarvestManifest(db_path)
        try:
            deleted_count = count_deleted(manifest)
        finally:
            manifest.close()
    return {**block, "deleted_count": deleted_count}


@router.patch("/settings/retention")
async def patch_retention(body: RetentionUpdate) -> dict:
    """Persist the deletion policy + grace period to ``mnemify.yaml``."""
    upsert_retention(body.model_dump())
    return {"ok": True, **body.model_dump()}


# ─── compile settings (saved defaults that drive each compile) ───────

# Defaults mirror the Compiler / claude_cli / openai_clients code defaults so a
# fresh install with no ``compile:`` block behaves exactly as before.
# Per-step Claude model: an alias ("opus"/"sonnet"/"haiku") or a full Anthropic
# model id ("claude-opus-5"). The CLI resolves aliases itself; the API path maps
# them in anthropic_clients. Per-step selection replaced the old ``claude_preset``.

# Backward-compat: map a legacy ``claude_preset`` onto the two per-step models
# (extract_model, name_model) so saved configs / old payloads keep working.
_PRESET_TO_MODELS: dict[str, tuple[str, str]] = {
    "max": ("opus", "opus"),
    "balanced": ("sonnet", "opus"),
    "fast": ("sonnet", "sonnet"),
    "haiku": ("haiku", "haiku"),
}

# "" = provider default (no effort parameter sent).
EFFORT_CHOICES = ("", "low", "medium", "high")
EffortLevel = Literal["", "low", "medium", "high"]

COMPILE_DEFAULTS: dict = {
    "ai_mode": "openai",
    # Per-step Claude models (used by both the claude-CLI and anthropic-API
    # engines). Defaults reproduce the old "balanced" preset: Sonnet for chunk
    # feature-extraction, Opus for region/topic naming.
    "claude_extract_model": "sonnet",
    "claude_name_model": "opus",
    "openai_model": "gpt-5.6-luna",
    "embedding_model": "text-embedding-3-large",
    "llm_concurrency": 8,
    "extract_batch_size": 8,
    # Reasoning effort per step, for every LLM engine (OpenAI reasoning.effort,
    # Claude API output_config.effort, Claude CLI --effort). "" = provider
    # default. Extraction is high-volume + checkable → low; naming/notes are
    # what the user reads → medium.
    "extract_effort": "low",
    "name_effort": "medium",
    "claude_call_logging": False,
    "default_source": None,
    "auto_compile_after_harvest": False,
    "workspace": "Mnemify",
    "owner_name": "Mnemify User",
    "owner_role": "Knowledge Worker",
}


def _compile_settings_block() -> dict:
    """Read the ``compile`` block from YAML, filling/clamping each field from
    :data:`COMPILE_DEFAULTS`. Tolerant of partial or malformed blocks."""
    cfg = read_config()
    block = cfg.get("compile") or {}
    out = dict(COMPILE_DEFAULTS)

    ai_mode = block.get("ai_mode")
    if ai_mode in ("openai", "anthropic", "local", "claude"):
        out["ai_mode"] = ai_mode

    # Per-step Claude model selection (replaces the old ``claude_preset``).
    # A legacy preset seeds both models first; explicit per-step fields then
    # win if present, so a half-migrated config resolves sensibly.
    preset = block.get("claude_preset")
    if preset in _PRESET_TO_MODELS:
        out["claude_extract_model"], out["claude_name_model"] = _PRESET_TO_MODELS[preset]
    extract_model = block.get("claude_extract_model")
    if is_claude_model_ref(extract_model):
        out["claude_extract_model"] = extract_model
    name_model = block.get("claude_name_model")
    if is_claude_model_ref(name_model):
        out["claude_name_model"] = name_model

    embedding = block.get("embedding_model")
    if embedding in ("text-embedding-3-small", "text-embedding-3-large"):
        out["embedding_model"] = embedding

    openai_model = block.get("openai_model")
    if isinstance(openai_model, str) and openai_model.strip():
        out["openai_model"] = openai_model.strip()

    conc = block.get("llm_concurrency")
    if isinstance(conc, int) and 1 <= conc <= 32:
        out["llm_concurrency"] = conc

    batch = block.get("extract_batch_size")
    if isinstance(batch, int) and 1 <= batch <= 64:
        out["extract_batch_size"] = batch

    for key in ("extract_effort", "name_effort"):
        val = block.get(key)
        if val in EFFORT_CHOICES:
            out[key] = val

    if isinstance(block.get("claude_call_logging"), bool):
        out["claude_call_logging"] = block["claude_call_logging"]

    if isinstance(block.get("auto_compile_after_harvest"), bool):
        out["auto_compile_after_harvest"] = block["auto_compile_after_harvest"]

    src = block.get("default_source")
    out["default_source"] = src if (isinstance(src, str) and src.strip()) else None

    for key in ("workspace", "owner_name", "owner_role"):
        val = block.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()

    return out


class CompileSettingsUpdate(BaseModel):
    ai_mode: Literal["openai", "anthropic", "local", "claude"]
    # Per-step Claude model selection. Defaulted so payloads sent before the UI
    # exposes both fields still validate (they fall back to the "balanced" pair).
    claude_extract_model: str = Field(default="sonnet", pattern=CLAUDE_MODEL_PATTERN, max_length=100)
    claude_name_model: str = Field(default="opus", pattern=CLAUDE_MODEL_PATTERN, max_length=100)
    openai_model: str = Field(min_length=1, max_length=100)
    embedding_model: Literal["text-embedding-3-small", "text-embedding-3-large"]
    llm_concurrency: int = Field(ge=1, le=32)
    # Optional + defaulted so pre-existing settings payloads (sent before the UI
    # exposes this knob) still validate instead of 422-ing.
    extract_batch_size: int = Field(default=8, ge=1, le=64)
    # Defaulted so older payloads still validate.
    extract_effort: EffortLevel = "low"
    name_effort: EffortLevel = "medium"
    claude_call_logging: bool
    default_source: str | None = None
    # Defaulted so payloads sent before the UI exposes the toggle still validate.
    auto_compile_after_harvest: bool = False
    workspace: str = Field(min_length=1, max_length=100)
    owner_name: str = Field(min_length=1, max_length=100)
    owner_role: str = Field(min_length=1, max_length=100)


@router.get("/settings/compile")
async def get_compile_settings() -> dict:
    """Return the saved compile defaults (filled from code defaults)."""
    return _compile_settings_block()


@router.patch("/settings/compile")
async def patch_compile_settings(body: CompileSettingsUpdate) -> dict:
    """Persist the compile defaults to ``mnemify.yaml``."""
    upsert_compile(body.model_dump())
    return {"ok": True, **body.model_dump()}


@router.post("/settings/retention/purge-now")
async def purge_now(source: str | None = None) -> dict:
    """Immediately purge every doc marked ``deleted_at_source`` (grace_days=0).

    Independent of the auto-policy — this is the manual cleanup button users
    can fire any time. Refused while a harvest or compile is running so we
    don't race a writer.
    """
    if orch.state.status == "running":
        raise HTTPException(409, "a harvest is in progress; cancel it first")
    if compile_orch.state.status == "running":
        raise HTTPException(409, "a compile is in progress; cancel it first")

    from src.harvester.manifest import HarvestManifest
    from src.harvester.normalized_store import NormalizedStore
    from src.harvester.raw_store import RawStore
    from src.harvester.retention import purge_deleted

    db_path = _DATA_DIR / "harvest-manifest.db"
    if not db_path.exists():
        return {"ok": True, "purged": 0, "eligible": 0, "skipped": 0}

    manifest = HarvestManifest(db_path)
    try:
        raw_store = RawStore(_DATA_DIR / "raw", converter_version="0.1.0")
        normalized_store = NormalizedStore(_DATA_DIR / "normalized")
        result = purge_deleted(
            manifest,
            raw_store,
            normalized_store,
            source=source,
            grace_days=0,
        )
    finally:
        manifest.close()

    return {
        "ok": True,
        "purged": result.purged,
        "eligible": result.eligible,
        "skipped": result.skipped,
    }


# Files + directories under .mnemify/ that a full reset wipes.
_RESET_FILES = (
    "harvest-manifest.db",
    "harvest-manifest.db-shm",
    "harvest-manifest.db-wal",
    "harvest-log.jsonl",
    "compile-manifest.db",
    "terrain.json",
    "terrain.db",
    "terrain.db-shm",
    "terrain.db-wal",
    "render-data.json",
    "mocknotes.json",
    "debug_sample.md",
)
_RESET_DIRS = ("raw", "normalized")


@router.post("/reset")
async def reset():
    """Hard reset: clear harvested data + the compiled map, disable every
    source, and remove first-party credentials. Refused while a harvest or
    compile is running. (For "wipe data but keep my connections", use
    ``POST /api/harvest/reset``.)"""
    if orch.state.status == "running":
        raise HTTPException(409, "a harvest is in progress; cancel it first")
    if compile_orch.state.status == "running":
        raise HTTPException(409, "a compile is in progress; cancel it first")

    from .credential_store import delete_secrets
    from .yaml_writer import disable_source, read_config

    data_dir = Path(".mnemify")

    cfg = read_config()
    for name in list((cfg.get("sources") or {}).keys()):
        disable_source(name)

    # Best-effort credential wipe for the first-party sources.
    delete_secrets(
        [
            "NOTION_TOKEN",
            "CONFLUENCE_EMAIL",
            "CONFLUENCE_API_TOKEN",
            "JIRA_EMAIL",
            "JIRA_API_TOKEN",
        ]
    )

    if data_dir.exists():
        # Don't shutil.rmtree the whole directory — anything else the user
        # may have put there is left alone. Only remove harvester/compiler-
        # owned files.
        for name in _RESET_FILES:
            p = data_dir / name
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
        for sub in _RESET_DIRS:
            p = data_dir / sub
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)

    orch.reset_state()
    bus.reset_buffer()
    compile_orch.reset_state()
    compile_bus.reset_buffer()
    return {"ok": True}
