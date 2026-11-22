"""Loads the current model version (backend/models/registry.json) and caches it in memory."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.config import settings

_lock = threading.Lock()
_cache: dict[str, Any] = {"version": None, "model": None, "mtime": None}


def registry_path() -> Path:
    return settings.models_dir / "registry.json"


def read_registry() -> dict[str, Any]:
    p = registry_path()
    if not p.is_file():
        return {"current": None, "versions": []}
    return json.loads(p.read_text(encoding="utf-8"))


def write_registry(reg: dict[str, Any]) -> None:
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=2), encoding="utf-8")
    tmp.replace(p)


def current_model() -> tuple[str | None, Any]:
    """(version, HamiModel) for the current model, or (None, None) if none is trained yet."""
    p = registry_path()
    mtime = p.stat().st_mtime if p.is_file() else None
    with _lock:
        if _cache["mtime"] == mtime and _cache["model"] is not None:
            return _cache["version"], _cache["model"]
        reg = read_registry()
        version = reg.get("current")
        if not version:
            _cache.update(version=None, model=None, mtime=mtime)
            return None, None
        from ml.model import HamiModel

        model = HamiModel.load(settings.models_dir / version)
        _cache.update(version=version, model=model, mtime=mtime)
        return version, model


def invalidate() -> None:
    with _lock:
        _cache.update(version=None, model=None, mtime=None)
