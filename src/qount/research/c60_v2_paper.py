"""C60 contract v2 research-paper sidecar (month-end candidates). research_only / no orders.

Owner-authorized 2026-09-29 as an isolated comparison line next to the frozen four-account
Dual-Engine paper; it never writes Dual-Engine state, StrategyIntent, targets or orders.
Rule = Trial 150 ``research_monthly`` (docs/c60-cost-expectancy-preregistration-2026-09.md).
Points up to ``forward_start_date`` are in-sample replay (the rule was chosen on data to
2026-09-28); only later returns are forward evidence. Each builder run replays from public
Binance closes and must reproduce every previously ledgered equity, or the sidecar is marked
``forward_replay_mismatch``.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.dual_engine.contracts import C60_SYMBOLS
from qount.research.c60_cost_study import (
    WARMUP_BARS, Panel, SimResult, build_panel, max_drawdown, simulate, target_path,
)

SCHEMA = "c60_v2_research_paper_v1"
MAX_AGE_DAYS = 2
REPLAY_TOLERANCE = 1e-9
FETCH_START_MS = int(dt.datetime(2025, 6, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)

CONTRACT = {
    "contract_id": "dual-engine-c60-v2-research",
    "version": "2.0.0",
    "rule": "c60_month_end_candidates_daily_gates",
    "source_trial": "150",
    "preregistration": "docs/c60-cost-expectancy-preregistration-2026-09.md",
    "universe": list(C60_SYMBOLS),
    "candidate_rebalance": "last_utc_close_of_month_top2_positive_90d_momentum",
    "daily_rules": "frozen_v1_own_sma20_btc_sma50_paxg_exempt_vol_cap_60_20d",
    "cost_bps_per_side": 25.0,
    "stress_cost_bps_per_side": 50.0,
    "execution": "decision_close_t0",
    "initial_equity": 10_000.0,
    "display_start_date": "2026-01-01",
    "forward_start_date": "2026-09-30",
    "research_only": True,
    "orders_authorized": False,
    "replaces_frozen_v1": False,
}
CONTRACT_HASH = canonical_hash(CONTRACT)


class C60V2PaperError(ValueError):
    pass


def _equity_curve(result: SimResult, *, first_date: str, initial: float) -> list[dict[str, Any]]:
    """End-of-day equity; the first point is the all-cash account at ``first_date``."""

    equity = initial
    points = [{"date": first_date, "equity": equity}]
    for day, r in zip(result.dates, result.returns):
        equity *= 1.0 + r
        points.append({"date": day, "equity": equity})
    peak = points[0]["equity"]
    for point in points:
        peak = max(peak, point["equity"])
        point["drawdown"] = point["equity"] / peak - 1.0
    return points


def _segment_return(points: Sequence[Mapping[str, Any]], start: str) -> tuple[float | None, int]:
    base = [p for p in points if p["date"] <= start]
    after = [p for p in points if p["date"] > start]
    if not base or not after:
        return None, 0
    return after[-1]["equity"] / base[-1]["equity"] - 1.0, len(after)


def _replay(panel: Panel, mode: str, records: list | None = None) -> tuple[SimResult, str]:
    first = next(d for i, d in enumerate(panel.dates)
                 if i >= WARMUP_BARS - 1 and d >= CONTRACT["display_start_date"])
    result = simulate(panel, target_path(panel, mode=mode), cost_bps=CONTRACT["cost_bps_per_side"],
                      start_date=CONTRACT["display_start_date"], records=records)
    return result, first


def build_snapshot(
    series: Mapping[str, Mapping[str, float]],
    *,
    observed_at: dt.datetime,
    ledger: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if observed_at.tzinfo is None:
        raise C60V2PaperError("observed_at_timezone_required")
    panel, audit = build_panel(series)
    initial = CONTRACT["initial_equity"]
    records: list[dict[str, Any]] = []
    v2, first = _replay(panel, "research_monthly", records)
    v1_records: list[dict[str, Any]] = []
    v1, _ = _replay(panel, "frozen_daily", v1_records)
    points = _equity_curve(v2, first_date=first, initial=initial)
    v1_points = _equity_curve(v1, first_date=first, initial=initial)
    by_date = {p["date"]: p["equity"] for p in points}
    for record in records:  # NAV at the decision close, before that day's trade
        record["cost"] = record["cost_fraction"] * by_date[record["date"]]

    reasons: list[str] = []
    for entry in ledger:
        replayed = by_date.get(str(entry.get("date")))
        recorded = float(entry.get("equity", "nan"))
        if replayed is None or not abs(replayed - recorded) <= REPLAY_TOLERANCE * max(1.0, abs(recorded)):
            reasons.append(f"forward_replay_mismatch:{entry.get('date')}")
    age = (observed_at.astimezone(dt.timezone.utc).date() - dt.date.fromisoformat(panel.dates[-1])).days
    if age > MAX_AGE_DAYS:
        reasons.append("series_stale")

    forward_start = CONTRACT["forward_start_date"]
    forward_return, forward_bars = _segment_return(points, forward_start)
    v1_forward, _ = _segment_return(v1_points, forward_start)
    btc = panel.closes["BTCUSDT"]
    btc_start = panel.dates.index(first)
    last = points[-1]
    return {
        "schema": SCHEMA,
        "strategy_id": "c60-v2",
        "strategy_label": "C60 v2 月度候选（研究侧车）",
        "status": "valid" if not reasons else "insufficient",
        "reason_codes": reasons,
        "research_only": True,
        "orders_authorized": False,
        "pnl_evaluated": False,
        "promotion_evidence": False,
        "source": "binance_spot_public_klines",
        "data_hash": audit["data_hash"],
        "data_cutoff": f"{panel.dates[-1]}T00:00:00Z",
        "observed_at": observed_at.astimezone(dt.timezone.utc).isoformat(),
        "freshness": {"age_calendar_days": age, "max_age_calendar_days": MAX_AGE_DAYS},
        "contract": CONTRACT,
        "contract_hash": CONTRACT_HASH,
        "universe": list(C60_SYMBOLS),
        "initial_equity": initial,
        "final_equity": round(last["equity"], 6),
        "total_return": round(last["equity"] / initial - 1.0, 10),
        "max_drawdown": round(max_drawdown(v2.returns), 10),
        "cumulative_cost": round(sum(r["cost"] for r in records), 6),
        "rebalance_count": len(records),
        "current_weights": {k: round(v, 8) for k, v in (records[-1]["weights"] if records else {}).items()},
        "forward": {"start_date": forward_start, "bars": forward_bars,
                    "return": None if forward_return is None else round(forward_return, 10),
                    "v1_same_engine_return": None if v1_forward is None else round(v1_forward, 10),
                    "in_sample_through": forward_start},
        "comparison": {
            "v1_same_engine_total_return": round(v1_points[-1]["equity"] / initial - 1.0, 10),
            "v1_same_engine_max_drawdown": round(max_drawdown(v1.returns), 10),
            "v1_same_engine_rebalance_count": len(v1_records),
            "btc_buy_and_hold_return": round(btc[-1] / btc[btc_start] - 1.0, 10),
            "note": "same-engine replay of frozen v1 rule; not the Dual-Engine paper account",
        },
        "points": [{"date": p["date"], "equity": round(p["equity"], 6), "drawdown": round(p["drawdown"], 8)}
                   for p in points],
        "rebalances": [{"date": r["date"], "turnover": round(r["turnover"], 8),
                        "cost": round(r["cost"], 6),
                        "weights": {k: round(v, 8) for k, v in r["weights"].items()}} for r in records[-24:]],
    }


def read_ledger(path: Path) -> list[dict[str, Any]]:
    """Append-only hash-chained forward ledger; any break is an error, never silently skipped."""

    if not path.exists():
        return []
    entries, previous = [], None
    for line in path.read_text().splitlines():
        entry = json.loads(line)
        core = {k: v for k, v in entry.items() if k != "record_hash"}
        if entry.get("previous_hash") != previous or canonical_hash(core) != entry.get("record_hash"):
            raise C60V2PaperError("forward_ledger_chain_invalid")
        entries.append(entry)
        previous = entry["record_hash"]
    return entries


def append_ledger(path: Path, snapshot: Mapping[str, Any], ledger: Sequence[Mapping[str, Any]]) -> int:
    """Record each not-yet-ledgered point from the forward start on; only for valid snapshots."""

    if snapshot["status"] != "valid" or snapshot["contract_hash"] != CONTRACT_HASH:
        return 0
    seen = {entry["date"] for entry in ledger}
    previous = ledger[-1]["record_hash"] if ledger else None
    lines = []
    for point in snapshot["points"]:
        if point["date"] < CONTRACT["forward_start_date"] or point["date"] in seen:
            continue
        core = {"date": point["date"], "equity": point["equity"], "contract_hash": CONTRACT_HASH,
                "data_hash": snapshot["data_hash"], "previous_hash": previous}
        entry = core | {"record_hash": canonical_hash(core)}
        lines.append(json.dumps(entry, sort_keys=True))
        previous = entry["record_hash"]
    if lines:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write("\n".join(lines) + "\n")
        os.chmod(path, 0o600)
    return len(lines)


def write_snapshot(snapshot: Mapping[str, Any], path: Path, *, mode: int = 0o644) -> Path:
    """Atomic canonical JSON write for the static dashboard directory."""

    if snapshot.get("schema") != SCHEMA or snapshot.get("orders_authorized") is not False:
        raise C60V2PaperError("snapshot_guard_invalid")
    if mode not in {0o600, 0o644}:
        raise C60V2PaperError("snapshot_mode_invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(raw)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def fetch_series(observed_at: dt.datetime) -> dict[str, dict[str, float]]:
    from qount.research.c60_cost_study import fetch_daily_closes

    observed_ms = int(observed_at.timestamp() * 1000)
    return {s: fetch_daily_closes(s, observed_ms=observed_ms, start_ms=FETCH_START_MS) for s in C60_SYMBOLS}

