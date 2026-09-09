from __future__ import annotations

from src.terrain.utils.models import SourceDocument


def container_path(doc: SourceDocument) -> list[str]:
    """Source-native container path for a document, outermost segment first.

    The "container" is the structure the *source* already imposes on a
    document — for Obsidian that is the vault-relative parent folder, carried
    on ``doc.metadata['folder']`` by the harvester. Nested folders become
    nested path segments (``"Projects/Alpha"`` -> ``["Projects", "Alpha"]``),
    which the clusterer turns into nested regions.

    Segments are returned RAW (ordering prefixes like ``01-`` are preserved):
    they seed grouping and node-id hashing only, never display — region names
    come from the LLM namer — so stripping them would risk collapsing two
    distinct folders (``01-Foo`` and ``02-Foo``) into one region.

    Returns ``[]`` for vault-root notes and for sources that expose no
    container (Notion/Jira/etc. today), which the clusterer reads as "no
    container -> fall back to embedding clustering".
    """
    metadata = getattr(doc, "metadata", None) or {}
    folder = metadata.get("folder")
    if not isinstance(folder, str):
        return []
    return [segment for segment in folder.replace("\\", "/").split("/") if segment.strip()]
