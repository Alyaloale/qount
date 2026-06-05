from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .ai_client import AIDecisionClient
from .decision_schema import validate_decision
from .models import AccountSnapshot
from .models import MarketSnapshotBundle
from .models import PositionSnapshot
from .models import utc_now
from .research_slice_scan import _discover_backtest_dirs
from .review import _symbol_snapshot_from_snapshot_entry
from .settings import Settings


AI_HOLD_BASELINE_PROMPT_VARIANTS = (
    "v1",
    "v2_remove_default_wait",
    "v3_veto_only",
)


Requester = Callable[
    [MarketSnapshotBundle, str, str, str],
    tuple[dict[str, Any], str, str],
]


def _action_counts() -> Counter[str]:
    return Counter({action: 0 for action in ("buy", "sell", "hold", "close", "invalid")})


def _normalized_symbol_key(symbol: str) -> str:
    return str(symbol).split(":", 1)[0].strip().upper()


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _summarize_counter(counter: Counter[str]) -> dict[str, Any]:
    total = sum(counter.values())
    return {
        "total": total,
        "counts": {key: int(value) for key, value in sorted(counter.items())},
        "hold_rate": _rate(int(counter.get("hold", 0)), total),
        "buy_rate": _rate(int(counter.get("buy", 0)), total),
        "sell_rate": _rate(int(counter.get("sell", 0)), total),
        "close_rate": _rate(int(counter.get("close", 0)), total),
        "invalid_rate": _rate(int(counter.get("invalid", 0)), total),
    }


def _append_prompt_variant_instruction(text: str, prompt_version: str) -> str:
    return (
        f"{text.rstrip()}\n\n"
        f"Research prompt variant: {prompt_version}. "
        f"Set the output prompt_version field to {prompt_version}."
    )


def _remove_default_wait_language(text: str) -> str:
    replacements = {
        "default wait unless everything else is exceptional": "require concrete contrary evidence before holding",
        "default wait unless the rest of the setup is unusually strong": "require a concrete conflicting reason before holding",
        "prefer waiting for one more confirming bar or a cleaner break": "hold only when a concrete veto is present",
        "prefer waiting for a cleaner pullback or sturdier rebuild": "hold only when chase risk or weak rebuild is concrete",
        "Use hold when": "Use hold only when",
        "Use hold only when the evidence is genuinely conflicting": "Use hold only when the evidence is genuinely conflicting",
    }
    updated = text
    for old, new in replacements.items():
        updated = updated.replace(old, new)
    return updated


def build_ai_hold_prompt_variant(
    settings: Settings,
    prompt_variant: str,
) -> tuple[str, str, dict[str, Any]]:
    if prompt_variant not in AI_HOLD_BASELINE_PROMPT_VARIANTS:
        raise ValueError(f"unknown_ai_hold_prompt_variant:{prompt_variant}")

    system_prompt, decision_prompt = AIDecisionClient(settings).load_prompt_texts()
    hypothesis: dict[str, Any] = {
        "prompt_variant": prompt_variant,
        "scope": "research_only",
    }
    if prompt_variant == "v1":
        hypothesis["description"] = "current production prompt text; diagnostic replay only"
        return system_prompt, decision_prompt, hypothesis

    if prompt_variant == "v2_remove_default_wait":
        hypothesis["description"] = "remove broad default-wait language while keeping concrete risk veto language"
        return (
            _append_prompt_variant_instruction(
                _remove_default_wait_language(system_prompt),
                prompt_variant,
            ),
            _append_prompt_variant_instruction(
                _remove_default_wait_language(decision_prompt),
                prompt_variant,
            ),
            hypothesis,
        )

    veto_note = (
        "For fresh-entry candidates with candidate_context.setup_model_signal.quality=strong_favorable, "
        "choose hold only if the reason names a concrete veto such as terminal_risk, clear latest-bar reversal, "
        "negative expected_edge, exchange feasibility, or direct higher-timeframe conflict. "
        "Generic uncertainty, low RSI by itself, or a preference to wait is not enough."
    )
    hypothesis["description"] = "veto-only hold rule for strong_favorable fresh-entry candidates"
    return (
        _append_prompt_variant_instruction(f"{system_prompt.rstrip()}\n\n{veto_note}", prompt_variant),
        _append_prompt_variant_instruction(f"{decision_prompt.rstrip()}\n\n{veto_note}", prompt_variant),
        hypothesis,
    )


def _position_snapshot(raw: dict[str, Any]) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=str(raw.get("symbol") or ""),
        quantity=float(raw.get("quantity") or 0.0),
        mark_price=float(raw.get("mark_price") or 0.0),
        market_value_quote=float(raw.get("market_value_quote") or 0.0),
        side=None if raw.get("side") is None else str(raw.get("side")),
        average_entry_price=(
            None if raw.get("average_entry_price") is None else float(raw.get("average_entry_price"))
        ),
        notional_quote=None if raw.get("notional_quote") is None else float(raw.get("notional_quote")),
        unrealized_pnl_quote=(
            None if raw.get("unrealized_pnl_quote") is None else float(raw.get("unrealized_pnl_quote"))
        ),
        leverage=None if raw.get("leverage") is None else float(raw.get("leverage")),
        margin_mode=None if raw.get("margin_mode") is None else str(raw.get("margin_mode")),
        liquidation_price=None if raw.get("liquidation_price") is None else float(raw.get("liquidation_price")),
    )


def _account_snapshot(raw: dict[str, Any]) -> AccountSnapshot:
    positions = [
        _position_snapshot(item)
        for item in raw.get("open_positions") or []
        if isinstance(item, dict)
    ]
    return AccountSnapshot(
        quote_currency=str(raw.get("quote_currency") or "USDT"),
        equity_quote=float(raw.get("equity_quote") or 0.0),
        free_quote=float(raw.get("free_quote") or 0.0),
        open_positions=positions,
        mode=str(raw.get("mode") or "paper"),
        market_type=str(raw.get("market_type") or "future"),
    )


def _parse_timestamp(raw: Any) -> datetime:
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return utc_now()
    return utc_now()


def _selected_candidate_items(candidate_filter: dict[str, Any]) -> list[dict[str, Any]]:
    selected_symbols = {
        str(symbol)
        for symbol in candidate_filter.get("selected_symbols") or []
        if str(symbol).strip()
    }
    if not selected_symbols:
        return []
    items: list[dict[str, Any]] = []
    for item in candidate_filter.get("symbols") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("symbol") or "") not in selected_symbols:
            continue
        if bool(item.get("manage_only")):
            continue
        items.append(item)
    return items


def _bundle_from_snapshot_and_candidates(
    snapshot: dict[str, Any],
    candidate_items: list[dict[str, Any]],
) -> MarketSnapshotBundle | None:
    candidate_context_by_symbol = {
        str(item.get("symbol") or ""): {key: value for key, value in item.items() if key != "symbol"}
        for item in candidate_items
    }
    selected_symbols = set(candidate_context_by_symbol)
    symbols = []
    for entry in snapshot.get("symbols") or []:
        symbol = _symbol_snapshot_from_snapshot_entry(entry)
        if symbol is None or symbol.symbol not in selected_symbols:
            continue
        symbols.append(replace(symbol, candidate_context=candidate_context_by_symbol[symbol.symbol]))
    if not symbols:
        return None
    account_raw = snapshot.get("account") if isinstance(snapshot.get("account"), dict) else {}
    return MarketSnapshotBundle(
        generated_at=_parse_timestamp(snapshot.get("generated_at")),
        timeframe=str(snapshot.get("timeframe") or "5m"),
        symbols=symbols,
        account=_account_snapshot(account_raw),
    )


def _candidate_tags(candidate_items: list[dict[str, Any]]) -> list[str]:
    tags: set[str] = set()
    for item in candidate_items:
        for tag in item.get("research_slice_tags") or []:
            if str(tag).strip():
                tags.add(str(tag))
    return sorted(tags)


def _candidate_field_values(candidate_items: list[dict[str, Any]], field: str) -> list[str]:
    values = {
        str(item.get(field))
        for item in candidate_items
        if item.get(field) is not None and str(item.get(field)).strip()
    }
    return sorted(values)


def _candidate_setup_model_qualities(candidate_items: list[dict[str, Any]]) -> list[str]:
    values: set[str] = set()
    for item in candidate_items:
        signal = item.get("setup_model_signal")
        if isinstance(signal, dict) and signal.get("quality") is not None:
            values.add(str(signal["quality"]))
    return sorted(values)


class AIHoldBaselineService:
    def __init__(
        self,
        settings: Settings,
        *,
        requester: Requester | None = None,
    ) -> None:
        self.settings = settings
        self._client = AIDecisionClient(settings)
        self._requester = requester or self._request_decision

    def _request_decision(
        self,
        bundle: MarketSnapshotBundle,
        system_prompt: str,
        decision_prompt: str,
        prompt_version: str,
    ) -> tuple[dict[str, Any], str, str]:
        return self._client.request_decision(
            bundle,
            system_prompt_override=system_prompt,
            decision_prompt_override=decision_prompt,
            prompt_version=prompt_version,
        )

    def _iter_candidate_rows(
        self,
        backtest_dir: Path,
    ) -> list[dict[str, Any]]:
        db_path = backtest_dir / "qount.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT
                    runs.id AS run_id,
                    snapshots.snapshot_json AS snapshot_json,
                    validated.valid AS valid,
                    validated.errors_json AS errors_json,
                    validated.payload_json AS payload_json,
                    raw.model AS raw_model,
                    raw.response_text AS raw_response_text
                FROM runs
                JOIN snapshots ON snapshots.run_id = runs.id
                JOIN ai_decisions_validated AS validated ON validated.run_id = runs.id
                LEFT JOIN ai_decisions_raw AS raw ON raw.run_id = runs.id
                ORDER BY runs.id
                """
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    def _collect_samples(
        self,
        artifact_dir: Path,
        *,
        limit: int | None,
        run_ids: set[int] | None,
        target_tags: set[str] | None,
        symbols_filter: set[str] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        samples: list[dict[str, Any]] = []
        windows: list[dict[str, Any]] = []
        for label, backtest_dir in _discover_backtest_dirs(artifact_dir):
            window_scanned = 0
            window_selected = 0
            for row in self._iter_candidate_rows(backtest_dir):
                run_id = int(row["run_id"])
                if run_ids is not None and run_id not in run_ids:
                    continue
                payload = json.loads(row["payload_json"])
                raw_payload = payload.get("raw_payload") if isinstance(payload, dict) else None
                raw_payload = raw_payload if isinstance(raw_payload, dict) else {}
                candidate_filter = raw_payload.get("candidate_filter")
                if not isinstance(candidate_filter, dict):
                    continue
                candidate_items = _selected_candidate_items(candidate_filter)
                if symbols_filter is not None:
                    candidate_items = [
                        item
                        for item in candidate_items
                        if _normalized_symbol_key(str(item.get("symbol") or "")) in symbols_filter
                    ]
                if not candidate_items:
                    continue
                tags = _candidate_tags(candidate_items)
                if target_tags is not None and target_tags.isdisjoint(tags):
                    continue
                snapshot = json.loads(row["snapshot_json"])
                bundle = _bundle_from_snapshot_and_candidates(snapshot, candidate_items)
                if bundle is None:
                    continue
                decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
                sample = {
                    "window_label": label,
                    "backtest_artifact_dir": str(backtest_dir),
                    "run_id": run_id,
                    "generated_at": snapshot.get("generated_at"),
                    "selected_symbols": [symbol.symbol for symbol in bundle.symbols],
                    "candidate_count": len(bundle.symbols),
                    "research_slice_tags": tags,
                    "setup_phases": _candidate_field_values(candidate_items, "setup_phase"),
                    "higher_timeframe_phases": _candidate_field_values(candidate_items, "higher_timeframe_phase"),
                    "setup_model_qualities": _candidate_setup_model_qualities(candidate_items),
                    "stored_decision": {
                        "valid": bool(row["valid"]),
                        "action": str(decision.get("action") or "hold"),
                        "symbol": str(decision.get("symbol") or ""),
                        "confidence": decision.get("confidence"),
                        "reason": decision.get("reason"),
                        "model": row.get("raw_model"),
                    },
                    "bundle": bundle,
                }
                samples.append(sample)
                window_selected += 1
                if limit is not None and len(samples) >= limit:
                    break
            window_scanned += len(self._iter_candidate_rows(backtest_dir))
            windows.append(
                {
                    "label": label,
                    "backtest_artifact_dir": str(backtest_dir),
                    "rows_scanned": window_scanned,
                    "samples_selected": window_selected,
                }
            )
            if limit is not None and len(samples) >= limit:
                break
        return samples, windows

    def run(
        self,
        *,
        artifact_dir: Path,
        prompt_variant: str = "v1",
        repeat: int = 1,
        limit: int | None = 20,
        run_ids: list[int] | tuple[int, ...] | None = None,
        target_tags: list[str] | tuple[str, ...] | None = None,
        symbols_filter: list[str] | tuple[str, ...] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if repeat < 1 and not dry_run:
            raise ValueError("ai_hold_baseline_repeat_must_be_positive")
        system_prompt, decision_prompt, prompt_hypothesis = build_ai_hold_prompt_variant(
            self.settings,
            prompt_variant,
        )
        samples, windows = self._collect_samples(
            artifact_dir,
            limit=limit,
            run_ids=None if run_ids is None else {int(item) for item in run_ids},
            target_tags=None if target_tags is None else {str(tag) for tag in target_tags},
            symbols_filter=(
                None
                if symbols_filter is None
                else {_normalized_symbol_key(symbol) for symbol in symbols_filter}
            ),
        )

        stored_action_counts = _action_counts()
        replay_action_counts = _action_counts()
        by_setup_phase: dict[str, Counter[str]] = defaultdict(_action_counts)
        by_setup_model_quality: dict[str, Counter[str]] = defaultdict(_action_counts)
        by_tag: dict[str, Counter[str]] = defaultdict(_action_counts)
        result_samples: list[dict[str, Any]] = []
        request_count = 0

        for sample in samples:
            stored_action_counts.update([sample["stored_decision"]["action"]])
            sample_payload = {
                key: value
                for key, value in sample.items()
                if key != "bundle"
            }
            sample_payload["replays"] = []
            if not dry_run:
                for repeat_index in range(repeat):
                    request_count += 1
                    request_payload, raw_text, model_name = self._requester(
                        sample["bundle"],
                        system_prompt,
                        decision_prompt,
                        prompt_variant,
                    )
                    validated = validate_decision(
                        raw_text,
                        tuple(symbol.symbol for symbol in sample["bundle"].symbols),
                        utc_now(),
                        max_size_pct=self.settings.max_entry_size_pct,
                        contract_market=self.settings.contract_market,
                    )
                    action = validated.decision.action if validated.valid else "invalid"
                    replay_action_counts.update([action])
                    for setup_phase in sample["setup_phases"] or ["unknown"]:
                        by_setup_phase[setup_phase].update([action])
                    for quality in sample["setup_model_qualities"] or ["unknown"]:
                        by_setup_model_quality[quality].update([action])
                    for tag in sample["research_slice_tags"] or ["untagged"]:
                        by_tag[tag].update([action])
                    sample_payload["replays"].append(
                        {
                            "repeat_index": repeat_index,
                            "valid": validated.valid,
                            "errors": validated.errors,
                            "action": validated.decision.action,
                            "symbol": validated.decision.symbol,
                            "confidence": validated.decision.confidence,
                            "reason": validated.decision.reason,
                            "prompt_version": validated.decision.prompt_version,
                            "model": model_name,
                            "request_prompt_version": request_payload.get("prompt_version"),
                        }
                    )
            result_samples.append(sample_payload)

        return {
            "version": "ai_hold_baseline_v1",
            "generated_at": utc_now().isoformat(),
            "artifact_dir": str(artifact_dir.expanduser()),
            "backtest_count": len(windows),
            "prompt_variant": prompt_variant,
            "prompt_hypothesis": prompt_hypothesis,
            "repeat": repeat,
            "dry_run": dry_run,
            "limit": limit,
            "target_tags": list(target_tags or []),
            "symbols_filter": list(symbols_filter or []),
            "run_ids": list(run_ids or []),
            "sample_count": len(samples),
            "planned_request_count": 0 if dry_run else len(samples) * repeat,
            "request_count": request_count,
            "aggregate": {
                "stored_actions": _summarize_counter(stored_action_counts),
                "replayed_actions": _summarize_counter(replay_action_counts),
                "by_setup_phase": {
                    key: _summarize_counter(value)
                    for key, value in sorted(by_setup_phase.items())
                },
                "by_setup_model_quality": {
                    key: _summarize_counter(value)
                    for key, value in sorted(by_setup_model_quality.items())
                },
                "by_research_slice_tag": {
                    key: _summarize_counter(value)
                    for key, value in sorted(by_tag.items())
                },
            },
            "windows": windows,
            "samples": result_samples,
            "promotion_note": "research_prompt_diagnostic_only_not_promotion_evidence",
        }
