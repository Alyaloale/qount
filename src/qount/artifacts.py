from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from .models import utc_now
from .settings import Settings


def _sanitize_artifact_label(raw: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw.strip())
    return value.strip("-") or "artifact"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _state_root(settings: Settings) -> Path:
    return Path(getattr(settings, "state_dir", settings.project_root / "state"))


def persistent_research_dir(settings: Settings, kind: str, label: str | None = None) -> Path:
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    parts = [_sanitize_artifact_label(kind)]
    if label:
        parts.append(_sanitize_artifact_label(label))
    root = _state_root(settings) / "research_runs"
    root.mkdir(parents=True, exist_ok=True)
    stem = f"{stamp}-{'-'.join(parts)}"
    for collision_index in range(1000):
        suffix = "" if collision_index == 0 else f"-{collision_index:02d}"
        candidate = root / f"{stem}{suffix}"
        try:
            candidate.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        return candidate
    raise RuntimeError(f"unable to allocate unique research artifact directory for {stem}")


def should_mirror_to_research_runs(settings: Settings, path: Path) -> bool:
    state_root = _resolved(_state_root(settings))
    return not _is_relative_to(_resolved(path), state_root)


def write_research_json_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    kind: str,
    path_key: str,
    default_filename: str,
    explicit_path: str | None,
) -> dict[str, Any]:
    result = dict(payload)
    if explicit_path is None:
        run_dir = persistent_research_dir(settings, kind)
        target_path = run_dir / default_filename
        result[path_key] = str(target_path)
        result["persistent_artifact_path"] = str(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    target_path = Path(explicit_path).expanduser()
    if not target_path.is_absolute():
        target_path = settings.project_root / target_path
    result[path_key] = str(target_path)

    mirror_path: Path | None = None
    if should_mirror_to_research_runs(settings, target_path):
        mirror_dir = persistent_research_dir(settings, kind, target_path.stem)
        mirror_path = mirror_dir / target_path.name
        result["persistent_artifact_path"] = str(mirror_path)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if mirror_path is not None:
        mirror_path.parent.mkdir(parents=True, exist_ok=True)
        mirror_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def mirror_artifact_tree_if_external(settings: Settings, artifact_dir: Path, *, kind: str) -> Path | None:
    if not should_mirror_to_research_runs(settings, artifact_dir):
        return None
    mirror_dir = persistent_research_dir(settings, kind, artifact_dir.name)
    shutil.copytree(artifact_dir, mirror_dir, dirs_exist_ok=True)
    return mirror_dir
