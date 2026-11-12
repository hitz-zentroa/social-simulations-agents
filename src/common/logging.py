"""Shared Loguru configuration helpers."""

from __future__ import annotations

from pathlib import Path

from loguru import logger


def add_jsonl_sink(path: str | Path) -> int:
    """Add a JSON-serialized Loguru sink, creating its parent directory."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    return logger.add(destination, serialize=True, encoding="utf-8", level="INFO")
