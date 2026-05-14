"""
Build status storage using JSON file.
Stores build records with their status, metadata, and artifact paths.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List

STORE_FILE = Path(__file__).parent / "builds.json"


def _load_store() -> dict:
    """Load build store from JSON file."""
    if not STORE_FILE.exists():
        return {"builds": []}
    with open(STORE_FILE, "r") as f:
        return json.load(f)


def _save_store(store: dict) -> None:
    """Save build store to JSON file."""
    with open(STORE_FILE, "w") as f:
        json.dump(store, f, indent=2)


def create_build(project: str, mode: str, platform: str, target: str = "") -> dict:
    """Create a new build record with pending status."""
    now = datetime.now()
    build_id = now.strftime("%Y%m%d_%H%M%S")


    build = {
        "id": build_id,
        "project": project,
        "mode": mode,
        "platform": platform,
        "target": target,
        "status": "pending",
        "created_at": now.isoformat(),
        "finished_at": None,
        "artifact_path": None,
        "log": "",
        "error": None,
    }

    store = _load_store()
    store["builds"].insert(0, build)  # newest first
    _save_store(store)

    return build


def get_build(build_id: str) -> Optional[dict]:
    """Get a build by ID."""
    store = _load_store()
    for build in store["builds"]:
        if build["id"] == build_id:
            return build
    return None


def get_all_builds() -> List[dict]:
    """Get all builds, newest first."""
    store = _load_store()
    return store["builds"]


def update_build(build_id: str, **kwargs) -> Optional[dict]:
    """Update build fields (status, artifact_path, log, error, etc.)."""
    store = _load_store()
    for build in store["builds"]:
        if build["id"] == build_id:
            build.update(kwargs)
            if build["status"] in ("success", "failed"):
                build["finished_at"] = datetime.now().isoformat()
            _save_store(store)
            return build
    return None
