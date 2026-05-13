"""Small pure helpers (no I/O)."""

from __future__ import annotations

import hashlib
from typing import Final

_DEFAULT_PREFIX_LEN: Final[int] = 8


def short_id(value: str, *, prefix_len: int = _DEFAULT_PREFIX_LEN) -> str:
    """Return a short stable fingerprint for display (not cryptographic)."""
    if prefix_len < 4:
        msg = "prefix_len must be at least 4"
        raise ValueError(msg)
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return digest[:prefix_len]


def clamp(value: float, low: float, high: float) -> float:
    """Clamp `value` to the inclusive range `[low, high]`."""
    if low > high:
        msg = "low must be <= high"
        raise ValueError(msg)
    return max(low, min(high, value))
