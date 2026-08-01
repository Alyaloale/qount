#!/usr/bin/env python3
"""Read-only repository governance inventory and consistency checks.

This is deliberately a small stdlib-only tool.  It uses Python's AST for
imports/environment calls, parses Markdown links relative to their source
document, and reads systemd ``ExecStart`` lines instead of guessing from file
names.  It never moves archives, deletes data, contacts hosts, or reads values
from environment files.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPOSITORY_ROOT / "docs"
MAP_PATH = DOCS_ROOT / "reference" / "repository-map.md"
MANIFEST_PATH = DOCS_ROOT / "archive" / "manifest.md"
CONTRACT_PATH = REPOSITORY_ROOT / "config" / "environment-contract.toml"

PRODUCTION_DOMAINS = frozenset(
    {
        "contracts",
        "execution",
        "governance",
        "ledger",
        "risk",
        "operations",
        "notifications",
        "persistence",
        "portfolio",
        "reporting",
        "venue",
    }
)
ACTIVE_RESEARCH_DOMAINS = frozenset(
    {"mini_trend", "dual_engine", "small_account", "alpha_agents", "research_data", "research"}
)
ENVIRONMENT_REFERENCE = re.compile(
    r"\b(?:QOUNT_[A-Z0-9_]+|BINANCE_API_KEY|BINANCE_SECRET(?:_KEY)?|OPENAI_API_KEY|"
    r"HTTP_PROXY|HTTPS_PROXY|NO_PROXY|ALL_PROXY|TIINGO_API_TOKEN|TUSHARE_TOKEN|LD_LIBRARY_PATH)\b"
)
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
SYSTEMD_EXEC_START = re.compile(r"^\s*ExecStart(?:Pre|Post)?=([^\n]+)$", re.MULTILINE)
SYSTEMD_ENV_FILE = re.compile(r"^\s*EnvironmentFile=-?([^\s]+)", re.MULTILINE)


def _relative(path: Path) -> str:
    return path.relative_to(REPOSITORY_ROOT).as_posix()


def _tracked_status() -> dict[str, int]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--ignored"],
        cwd=REPOSITORY_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    counts: Counter[str] = Counter()
    for line in result.stdout.splitlines():
        prefix = line[:2]
        if prefix == "??":
            counts["untracked"] += 1
        elif prefix == "!!":
            counts["ignored"] += 1
        elif "D" in prefix:
            counts["deleted"] += 1
        else:
            counts["modified"] += 1
    return dict(sorted(counts.items()))


def _classify_path(path: Path) -> str:
    relative = _relative(path)
    parts = path.relative_to(REPOSITORY_ROOT).parts
    if not parts:
        return "unclassified"
    if parts[0] == "src" and len(parts) >= 3 and parts[1] == "qount":
        if parts[2] in PRODUCTION_DOMAINS:
            return "production_control_plane"
        if parts[2] in ACTIVE_RESEARCH_DOMAINS:
            return "active_research"
        if parts[2] == "legacy":
            return "legacy_compatibility"
        return "production_control_plane"
    if parts[0] == "scripts":
        return "legacy_compatibility" if "archive" in parts else "active_research"
    if parts[0] == "deploy":
        return "deployment"
    if parts[0] in {"config", ".github"}:
        return "deployment"
    if parts[0] == "docs":
        return "documentation"
    if parts[0] == "archive":
        return "legacy_compatibility"
    if parts[0] in {"tests", "web", "prompts"}:
        return "production_control_plane"
    if parts[0] in {"data", "models", "state"} or path.name.startswith("mac_nohup_"):
        return "runtime_data"
    if relative.endswith((".md", ".rst")):
        return "documentation"
    return "unclassified"


def _iter_files(roots: Iterable[Path], suffixes: set[str] | None = None) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or ".git" in path.parts or any(
                ignored in path.parts
                for ignored in {"__pycache__", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", "build", "dist"}
            ):
                continue
            if suffixes is not None and path.suffix not in suffixes:
                continue
            yield path


def _module_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _module_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def scan_python_imports() -> list[dict[str, str]]:
    """Find prohibited production imports of research scripts via Python AST."""

    problems: list[dict[str, str]] = []
    for path in _iter_files([REPOSITORY_ROOT / "src"], {".py"}):
        parts = path.relative_to(REPOSITORY_ROOT / "src" / "qount").parts
        if parts[0] in ACTIVE_RESEARCH_DOMAINS or parts[0] == "legacy":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as error:
            problems.append({"file": _relative(path), "issue": f"syntax_error:{error.lineno}"})
            continue
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            if any(name == "scripts" or name.startswith("scripts.") for name in imported):
                problems.append({"file": _relative(path), "issue": "production_imports_scripts"})
    return problems


def scan_environment_references() -> set[str]:
    """Find declared environment names across code, shell, systemd and topology."""

    names: set[str] = set()
    roots = [REPOSITORY_ROOT / "src", REPOSITORY_ROOT / "scripts", REPOSITORY_ROOT / "deploy"]
    for path in _iter_files(roots, {".py", ".sh", ".service", ".timer", ".env", ".json", ".plist"}):
        names.update(ENVIRONMENT_REFERENCE.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return names


def scan_markdown_links() -> list[dict[str, str]]:
    """Validate Markdown relative links from the directory of the source file."""

    problems: list[dict[str, str]] = []
    sources = [REPOSITORY_ROOT / "README.md", REPOSITORY_ROOT / "CLAUDE.md", REPOSITORY_ROOT / "AGENTS.md"]
    sources.extend(path for path in _iter_files([DOCS_ROOT], {".md"}) if DOCS_ROOT / "archive" not in path.parents)
    for source in sources:
        if not source.exists():
            continue
        text = source.read_text(encoding="utf-8", errors="ignore")
        for target in MARKDOWN_LINK.findall(text):
            target = target.strip().strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            target = target.split("#", 1)[0].split("?", 1)[0]
            if not target:
                continue
            candidate = (source.parent / target).resolve()
            if not candidate.exists():
                problems.append({"file": _relative(source), "target": target})
    return problems


def scan_deployment_references() -> list[dict[str, str]]:
    """Check paths named by repo-owned systemd ExecStart/EnvironmentFile fields."""

    problems: list[dict[str, str]] = []
    for unit in _iter_files([REPOSITORY_ROOT / "deploy" / "systemd"], {".service", ".timer"}):
        text = unit.read_text(encoding="utf-8", errors="ignore")
        for command in SYSTEMD_EXEC_START.findall(text):
            for match in re.findall(r"/root/qount/[^\s\\]+", command):
                relative = match.removeprefix("/root/qount/")
                if relative.startswith(("src/", "scripts/", "deploy/")) and not (REPOSITORY_ROOT / relative).exists():
                    problems.append({"unit": _relative(unit), "path": relative, "kind": "ExecStart"})
        for env_file in SYSTEMD_ENV_FILE.findall(text):
            # /etc/qount is intentionally host-owned. Relative repository paths
            # are the only files this checker is allowed to judge.
            if not env_file.startswith(("/", "%")) and not (unit.parent / env_file).exists():
                problems.append({"unit": _relative(unit), "path": env_file, "kind": "EnvironmentFile"})
    return problems


def _contract_names() -> set[str]:
    sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
    from qount.config_contract import load_contract  # pylint: disable=import-outside-toplevel

    return set(load_contract(CONTRACT_PATH))


def inventory() -> dict[str, object]:
    files = list(_iter_files([REPOSITORY_ROOT]))
    categories = Counter(_classify_path(path) for path in files)
    top_level = sorted(
        path.name
        for path in REPOSITORY_ROOT.iterdir()
        if path.is_file() and path.name not in {".DS_Store"}
    )
    root_candidates = [
        name
        for name in top_level
        if name not in {"README.md", "CLAUDE.md", "AGENTS.md", "pyproject.toml", "uv.lock", ".env.example", ".gitignore"}
    ]
    return {
        "repository_root": str(REPOSITORY_ROOT),
        "git_status": _tracked_status(),
        "file_categories": dict(sorted(categories.items())),
        "root_review_candidates": root_candidates,
        "environment_reference_count": len(scan_environment_references()),
        "deployment_unit_count": len(list(_iter_files([REPOSITORY_ROOT / "deploy" / "systemd"], {".service", ".timer"}))),
    }


def render_repository_map(data: dict[str, object]) -> str:
    categories = data["file_categories"]
    assert isinstance(categories, dict)
    status = data["git_status"]
    assert isinstance(status, dict)
    category_lines = "\n".join(f"| `{name}` | {count} |" for name, count in categories.items())
    status_lines = ", ".join(f"{name}={count}" for name, count in status.items()) or "clean"
    return f"""# Repository map

> **状态**：active｜**权威**：L3 generated reference｜**最后更新**：2026-08-02
> **适用范围**：目录职责、公开入口、部署引用与治理检查。
> **TL;DR**：生产控制面、活跃研究、冻结兼容、部署、文档和运行数据分层；本文件由 `repository_hygiene.py inventory --write` 生成，不记录密钥或运行时值。

## Stable public entry points

- CLI: `qount-run` → `qount.main:main`; monitor: `qount-monitor` → `qount.mac_monitor:main`.
- Current fact source: [`../current.md`](../current.md). Operational navigation: [`../operations/host-runbooks.md`](../operations/host-runbooks.md).
- Main verification: `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'` (full suite); focused governance verification is documented in [`cli-and-scripts.md`](cli-and-scripts.md).

## Domain ownership

| Domain | Responsibility | Host / entry |
| --- | --- | --- |
| `src/qount/contracts`, `execution`, `governance`, `ledger`, `risk`, `operations`, `notifications`, `persistence`, `portfolio`, `reporting`, `venue` | Production control plane and shared contracts | VPS is runtime truth; Mac performs lightweight checks. |
| `src/qount/mini_trend`, `dual_engine`, `small_account`, `alpha_agents`, `research_data`, `research/sleeves` | Active research or no-order simulations | Mac/WSL research; external disk holds large artifacts. |
| `src/qount/legacy` and `scripts/archive` | Frozen compatibility and historical evidence | No new business logic or timer restoration. |
| `deploy/systemd`, `deploy/wsl`, `deploy/dual_engine`, `deploy/research` | Deployment templates and host topology | Static validation only without explicit VPS authorization. |
| `docs` | Current fact, rules, operations, reference and archive navigation | `docs/current.md` is the sole current fact source. |

## Inventory snapshot

Git status at generation time: `{status_lines}`.

| Category | Files scanned |
| --- | ---: |
{category_lines}

Root-level review candidates are recorded in [`../archive/manifest.md`](../archive/manifest.md); candidates are not approved for movement or deletion merely by appearing there.

## Generated checks

`scripts/maintenance/repository_hygiene.py check` verifies relative Markdown links, environment-contract coverage, repository-owned deployment references, production-to-script import boundaries, required document metadata, manifest shape, and unclassified root files. It never accesses a remote host or reads secret values.
"""


def _has_metadata(path: Path) -> bool:
    head = path.read_text(encoding="utf-8", errors="ignore").splitlines()[:12]
    joined = "\n".join(head)
    return all(token in joined for token in ("状态", "权威", "最后更新", "TL;DR"))


def check() -> dict[str, object]:
    contract_names = _contract_names()
    referenced_names = scan_environment_references()
    coverage_missing = sorted(referenced_names.difference(contract_names))
    docs_with_required_metadata = [
        DOCS_ROOT / "README.md",
        DOCS_ROOT / "current.md",
        DOCS_ROOT / "project-rules.md",
        DOCS_ROOT / "quick-handoff.md",
        DOCS_ROOT / "reference" / "configuration.md",
        DOCS_ROOT / "reference" / "cli-and-scripts.md",
        DOCS_ROOT / "reference" / "repository-map.md",
        DOCS_ROOT / "operations" / "local-development.md",
        DOCS_ROOT / "operations" / "host-runbooks.md",
    ]
    missing_metadata = [_relative(path) for path in docs_with_required_metadata if not path.exists() or not _has_metadata(path)]
    manifest_ok = MANIFEST_PATH.exists() and all(
        token in MANIFEST_PATH.read_text(encoding="utf-8", errors="ignore")
        for token in ("原路径", "类别", "状态", "目标位置", "处理结论")
    )
    allowed_root_files = {"README.md", "CLAUDE.md", "AGENTS.md", "pyproject.toml", "uv.lock", ".env.example", ".gitignore"}
    unclassified_root = sorted(
        path.name
        for path in REPOSITORY_ROOT.iterdir()
        if path.is_file() and path.name not in allowed_root_files and path.name != ".DS_Store"
    )
    result = {
        "environment_contract_missing": coverage_missing,
        "markdown_link_errors": scan_markdown_links(),
        "deployment_reference_errors": scan_deployment_references(),
        "production_import_boundary_errors": scan_python_imports(),
        "document_metadata_errors": missing_metadata,
        "archive_manifest_valid": manifest_ok,
        "unclassified_root_files": unclassified_root,
    }
    result["ok"] = not any(
        (
            result["environment_contract_missing"],
            result["markdown_link_errors"],
            result["deployment_reference_errors"],
            result["production_import_boundary_errors"],
            result["document_metadata_errors"],
            not result["archive_manifest_valid"],
        )
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inventory_parser = commands.add_parser("inventory", help="Create a value-free repository inventory.")
    inventory_parser.add_argument("--write", action="store_true", help="Update only the generated repository map.")
    commands.add_parser("check", help="Run read-only repository governance checks.")
    args = parser.parse_args(argv)
    if args.command == "inventory":
        result = inventory()
        if args.write:
            MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
            MAP_PATH.write_text(render_repository_map(result), encoding="utf-8")
            result["written"] = _relative(MAP_PATH)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
