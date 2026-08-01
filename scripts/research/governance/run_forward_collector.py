#!/usr/bin/env python3
"""Run one unified, research-only forward evidence collection cycle."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research.forward_collector import (  # noqa: E402
    DEFAULT_SYMBOLS,
    ForwardCollectorConfigurationError,
    PluginRegistry,
    default_registry,
    load_source_config,
    read_status,
    run_once,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, default=Path("/var/lib/qount/research/forward"))
    parser.add_argument("--liquidation-state-root", type=Path, default=Path("/var/lib/qount/research/liquidation-cascade-v1"))
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--source-config", type=Path, default=REPO / "deploy/research/forward-sources.json")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--plugins", default="research_lines")
    parser.add_argument("--min-free-disk-gb", type=float, default=8.0)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--use-proxy-env", action="store_true")
    parser.add_argument("--plugin", action="append", default=[], metavar="MODULE:FACTORY")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def _load_external_plugins(registry: PluginRegistry, specs: list[str]) -> None:
    for spec in specs:
        module_name, separator, factory_name = spec.partition(":")
        if not separator or not module_name or not factory_name:
            raise ForwardCollectorConfigurationError("external_plugin_spec_invalid")
        factory = getattr(importlib.import_module(module_name), factory_name)
        plugin = factory()
        registry.register(plugin)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    state_root = args.state_root.expanduser()
    if args.status:
        try:
            payload = read_status(state_root)
        except (OSError, json.JSONDecodeError) as error:
            print(f"status_error={type(error).__name__}", file=sys.stderr)
            return 64
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2))
        return 0
    try:
        source_config = load_source_config(args.source_config.expanduser(), repo_root=args.repo_root.expanduser())
        registry = default_registry(
            liquidation_state_root=args.liquidation_state_root.expanduser(),
            source_config=source_config,
            repo_root=args.repo_root.expanduser(),
        )
    except ForwardCollectorConfigurationError as error:
        print(f"collector_error={error}", file=sys.stderr)
        return 64
    _load_external_plugins(registry, args.plugin)
    try:
        record = run_once(
            state_root=state_root,
            symbols=tuple(item.strip().upper() for item in args.symbols.split(",") if item.strip()),
            plugin_names=tuple(item.strip() for item in args.plugins.split(",") if item.strip()),
            registry=registry,
            min_free_disk_bytes=int(args.min_free_disk_gb * 1024**3),
            timeout_seconds=args.timeout_seconds,
            use_proxy_env=args.use_proxy_env,
            source_config_hash=source_config["source_config_hash"],
        )
    except (ForwardCollectorConfigurationError, OSError) as error:
        print(f"collector_error={error}", file=sys.stderr)
        return 64
    if args.print_json:
        print(json.dumps(record, ensure_ascii=True, sort_keys=True, indent=2))
    else:
        statuses = ",".join(
            f"{name}:{value['status']}" for name, value in record["plugins"].items()
        )
        print(f"record_hash={record['record_hash']}")
        print(f"observed_at_utc={record['observed_at_utc']}")
        print(f"plugins={statuses}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
