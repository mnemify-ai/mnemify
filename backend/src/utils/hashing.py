"""Hashing utilities for content deduplication."""

import hashlib


def sha256_hash(content: bytes | str) -> str:
    """Compute SHA-256 hash of content.

    Args:
        content: Bytes or string to hash.

    Returns:
        Hex digest string prefixed with 'sha256:'.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def short_hash(content: bytes | str, length: int = 16) -> str:
    """Compute a short hash for filenames and IDs.

    Args:
        content: Bytes or string to hash.
        length: Number of hex chars to return.

    Returns:
        Truncated hex digest (no prefix).
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()[:length]
