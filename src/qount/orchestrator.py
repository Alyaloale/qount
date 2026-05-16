from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .ai_client import AIDecisionClient
from .analytics import LiveAnalyticsService
from .candidate_filter import CandidateFilter
from .decision_schema import validate_decision
from .exchange_utils import ExchangePool
from .executor import Executor
from .journal import Journal
from .market import build_paper_account_snapshot
from .market import MarketGateway
from .models import AIDecision, ValidatedDecision, to_jsonable, utc_now
from .notifier import Notifier
from .risk_engine import RiskEngine
from .risk_engine import build_day_start_equity_key
from .review import ReviewService
from .safety import LiveSafetyChecks
from .safety import extract_rate_limit_backoff_ms
from .settings import Settings


class Orchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_directories()
        self.journal = Journal(settings.db_path)
        self.journal.ensure_schema()
        self.exchange_pool = ExchangePool(settings)
        self.market = MarketGateway(settings, exchange_pool=self.exchange_pool)
        self.candidate_filter = CandidateFilter(settings, self.journal)
        self.ai_client = AIDecisionClient(settings)
        self.risk_engine = RiskEngine(settings, self.journal)
        self.executor = Executor(settings, self.journal, exchange_pool=self.exchange_pool)
        self.notifier = Notifier(settings)
        self.safety_checks = LiveSafetyChecks(settings, self.journal, exchange_pool=self.exchange_pool)
        self.review_service = ReviewService(settings, self.journal)
        self.live_analytics = LiveAnalyticsService(settings, self.journal, exchange_pool=self.exchange_pool)

    def _fallback_symbol(self, bundle) -> str:
        if bundle.symbols:
            return bundle.symbols[0].symbol
        return self.settings.symbols[0]

    def _latest_prices_from_bundle(self, bundle) -> dict[str, float]:
        return {snapshot.symbol: snapshot.last_price for snapshot in bundle.symbols}

    def _refresh_bundle_account(self, bundle):
        latest_prices = self._latest_prices_from_bundle(bundle)
        if self.settings.paper_mode:
            account = build_paper_account_snapshot(
                settings=self.settings,
                journal=self.journal,
                latest_prices=latest_prices,
            )
        else:
            account = self.market.refresh_live_account(latest_prices)
        return replace(bundle, account=account)

    def _apply_candidate_filter(self, bundle, *, exclude_symbols: set[str]):
        if not exclude_symbols:
            return self.candidate_filter.apply(bundle)
        return self.candidate_filter.apply(bundle, exclude_symbols=exclude_symbols)

    def run_once(self) -> dict:
        if self.settings.live_mode:
            active_backoff = self._active_exchange_backoff()
            if active_backoff is not None:
                run_id = self.journal.start_run(self.settings.mode)
                summary = {
                    "run_id": run_id,
                    "mode": self.settings.mode,
                    "status": "exchange_backoff_active",
                    "backoff": active_backoff,
                }
                self.journal.finish_run(run_id, "skipped", summary)
                return summary
            guard = self.safety_checks.live_guard_status()
            if not guard.get("ok"):
                run_id = self.journal.start_run(self.settings.mode)
                summary = {
                    "run_id": run_id,
                    "mode": self.settings.mode,
                    "status": "live_guard_failed",
                    "guard": guard,
                }
                self.journal.finish_run(run_id, "failed", summary)
                return summary
        try:
            bundle = self.market.fetch_bundle(self.journal)
        except Exception as exc:
            run_id = self.journal.start_run(self.settings.mode)
            self.safety_checks.invalidate_cached_preflight()
            self._sync_exchange_backoff({"error": str(exc)})
            summary = {
                "run_id": run_id,
                "mode": self.settings.mode,
                "status": "market_data_failed",
                "error": str(exc),
            }
            self.journal.finish_run(run_id, "failed", summary)
            return summary
        if self.settings.live_mode:
            preflight = self.safety_checks.validate_bundle(bundle, arm=False)
            if not (
                preflight.get("public_api", {}).get("ok")
                and preflight.get("symbols_ok", {}).get("ok")
                and preflight.get("credentials", {}).get("ok")
                and preflight.get("balance_guard", {}).get("ok")
                and preflight.get("position_mode", {}).get("ok")
            ):
                summary = {
                    "run_id": run_id,
                    "mode": self.settings.mode,
                    "status": "live_preflight_failed",
                    "preflight": preflight,
                }
                self.journal.finish_run(run_id, "failed", summary)
                return summary
            orphan_cleanup = self.executor.cleanup_orphan_managed_orders(bundle)
        else:
            orphan_cleanup = {"canceled": [], "errors": []}
        return self._process_cycle(bundle, orphan_cleanup=orphan_cleanup)

    def _process_cycle(self, bundle, *, orphan_cleanup: dict[str, Any]) -> dict:
        if self.settings.live_mode:
            bar_state_key = self._live_bar_state_key()
            bar_fingerprint = bundle.latest_closed_bar_fingerprint()
            last_bar_state = self.journal.get_runtime_state(bar_state_key, None)
            if last_bar_state and last_bar_state.get("fingerprint") == bar_fingerprint:
                run_id = self.journal.start_run(self.settings.mode)
                summary = {
                    "run_id": run_id,
                    "mode": self.settings.mode,
                    "status": "duplicate_bar_skipped",
                    "fingerprint": bar_fingerprint,
                    "previous": last_bar_state,
                }
                if orphan_cleanup.get("canceled") or orphan_cleanup.get("errors"):
                    summary["orphan_cleanup"] = orphan_cleanup
                self.journal.finish_run(run_id, "skipped", summary)
                return summary

        processed_symbols: set[str] = set()
        cycle_summaries: list[dict[str, Any]] = []
        current_bundle = bundle
        pending_orphan_cleanup = orphan_cleanup

        while True:
            candidate_result = self._apply_candidate_filter(
                current_bundle,
                exclude_symbols=processed_symbols,
            )
            if candidate_result.status == "filtered_hold" and cycle_summaries:
                break

            run_id = self.journal.start_run(self.settings.mode)
            summary = self._process_bundle(
                run_id,
                current_bundle,
                orphan_cleanup=pending_orphan_cleanup,
                candidate_result=candidate_result,
                skip_duplicate_guard=True,
            )
            cycle_summaries.append(summary)
            pending_orphan_cleanup = {"canceled": [], "errors": []}

            if summary.get("symbol"):
                processed_symbols.add(str(summary["symbol"]))

            if candidate_result.status == "filtered_hold":
                break

            if summary.get("status") not in {None, "completed", "skipped"}:
                break

            if len(processed_symbols) >= len({snapshot.symbol for snapshot in current_bundle.symbols}):
                break

            current_bundle = self._refresh_bundle_account(current_bundle)

        if len(cycle_summaries) == 1:
            return cycle_summaries[0]
        return {
            "mode": self.settings.mode,
            "status": "cycle_completed",
            "generated_at": bundle.generated_at.isoformat(),
            "processed_runs": len(cycle_summaries),
            "processed_symbols": [item.get("symbol") for item in cycle_summaries if item.get("symbol")],
            "sub_runs": cycle_summaries,
        }

    def _process_bundle(
        self,
        run_id: int,
        bundle,
        *,
        orphan_cleanup: dict[str, Any],
        candidate_result=None,
        skip_duplicate_guard: bool = False,
    ) -> dict:
        self.journal.record_snapshot(run_id, bundle)
        self._write_json_artifact(self.settings.snapshot_dir / f"run-{run_id}.json", to_jsonable(bundle))
        if self.settings.live_mode and not skip_duplicate_guard:
            bar_state_key = self._live_bar_state_key()
            bar_fingerprint = bundle.latest_closed_bar_fingerprint()
            last_bar_state = self.journal.get_runtime_state(bar_state_key, None)
            if last_bar_state and last_bar_state.get("fingerprint") == bar_fingerprint:
                summary = {
                    "run_id": run_id,
                    "mode": self.settings.mode,
                    "status": "duplicate_bar_skipped",
                    "fingerprint": bar_fingerprint,
                    "previous": last_bar_state,
                }
                if orphan_cleanup.get("canceled") or orphan_cleanup.get("errors"):
                    summary["orphan_cleanup"] = orphan_cleanup
                self.journal.finish_run(run_id, "skipped", summary)
                return summary

        if candidate_result is None:
            candidate_result = self.candidate_filter.apply(bundle)
        candidate_summary = candidate_result.summary
        ai_bundle = candidate_result.filtered_bundle or bundle
        ai_failure_streak = int(self.journal.get_runtime_state("ai_failure_streak", 0))
        try:
            if candidate_result.status == "filtered_hold":
                hold_payload = {
                    "timestamp": utc_now().isoformat(),
                    "symbol": self._fallback_symbol(bundle),
                    "action": "hold",
                    "size_pct": 0.0,
                    "take_profit_pct": 0.0,
                    "stop_loss_pct": 0.0,
                    "ttl_minutes": 0,
                    "confidence": 0.0,
                    "reason": "candidate_filter:no_eligible_symbols",
                    "prompt_version": "v1",
                    "scope": "portfolio",
                    "candidate_filter_generated": True,
                    "candidate_filter": candidate_summary,
                }
                validated = validate_decision(
                    hold_payload,
                    tuple(symbol.symbol for symbol in bundle.symbols),
                    utc_now(),
                    max_size_pct=self.settings.max_entry_size_pct,
                    contract_market=self.settings.contract_market,
                )
                self.journal.record_ai_raw(
                    run_id,
                    "candidate_filter",
                    "v1",
                    {"candidate_filter": candidate_summary},
                    json.dumps(hold_payload, ensure_ascii=False),
                )
            else:
                request_payload, raw_text, model_name = self.ai_client.request_decision(ai_bundle)
                request_payload["candidate_filter"] = candidate_summary
                self.journal.set_runtime_state("ai_failure_streak", 0)
                self.journal.record_ai_raw(run_id, model_name, "v1", request_payload, raw_text)
                validated = validate_decision(
                    raw_text,
                    tuple(symbol.symbol for symbol in ai_bundle.symbols),
                    utc_now(),
                    max_size_pct=self.settings.max_entry_size_pct,
                    contract_market=self.settings.contract_market,
                )
                if validated.raw_payload is not None:
                    validated.raw_payload["candidate_filter"] = candidate_summary
            if candidate_result.status == "filtered_hold":
                self.journal.set_runtime_state("ai_failure_streak", 0)
        except Exception as exc:
            ai_failure_streak += 1
            self.journal.set_runtime_state("ai_failure_streak", ai_failure_streak)
            if ai_failure_streak >= 3:
                self.journal.set_runtime_state("halted", True)
            fallback = AIDecision(
                timestamp=utc_now().isoformat(),
                symbol=self._fallback_symbol(ai_bundle),
                action="hold",
                size_pct=0.0,
                take_profit_pct=0.02,
                stop_loss_pct=0.01,
                ttl_minutes=60,
                confidence=0.0,
                reason=f"ai_failure:{exc}",
                prompt_version="v1",
            )
            validated = ValidatedDecision(
                decision=fallback,
                valid=False,
                errors=[f"ai_request_failed:{exc}"],
                raw_payload=None,
            )
            self.journal.record_ai_raw(run_id, self.settings.ai_model, "v1", {"error": True}, str(exc))

        self.journal.record_validated_decision(run_id, validated)
        verdict = self.risk_engine.evaluate(validated, bundle)
        self.journal.record_risk(run_id, verdict)
        try:
            result = self.executor.execute(verdict, bundle)
        except Exception as exc:
            self.safety_checks.invalidate_cached_preflight()
            self._sync_exchange_backoff({"error": str(exc)})
            self._write_json_artifact(
                self.settings.decision_dir / f"run-{run_id}.json",
                {
                    "validated": to_jsonable(validated),
                    "risk": to_jsonable(verdict),
                    "execution_error": str(exc),
                },
            )
            summary = {
                "run_id": run_id,
                "mode": self.settings.mode,
                "status": "execution_failed",
                "symbol": verdict.symbol,
                "action": verdict.final_action,
                "error": str(exc),
            }
            self.journal.finish_run(run_id, "failed", summary)
            return summary
        self.journal.record_order(run_id, result)
        self._record_successful_position_management(verdict, result)
        self._record_successful_protective_refresh(verdict, result)
        self._write_json_artifact(
            self.settings.decision_dir / f"run-{run_id}.json",
            {
                "validated": to_jsonable(validated),
                "risk": to_jsonable(verdict),
                "execution": to_jsonable(result),
            },
        )
        summary = {
            "run_id": run_id,
            "mode": self.settings.mode,
            "symbol": verdict.symbol,
            "action": verdict.final_action,
            "order_status": result.status,
            "equity_quote": bundle.account.equity_quote,
            "candidate_filter": candidate_summary,
            "generated_at": bundle.generated_at.isoformat(),
        }
        if verdict.risk_debug is not None:
            summary["risk_debug"] = verdict.risk_debug
        if orphan_cleanup.get("canceled") or orphan_cleanup.get("errors"):
            summary["orphan_cleanup"] = orphan_cleanup
        if verdict.close_fraction < 1.0:
            summary["close_fraction"] = verdict.close_fraction
            summary["management_open_run_id"] = verdict.management_open_run_id
        if verdict.protective_refresh_only:
            summary["protective_refresh_reason"] = verdict.protective_refresh_reason
        if self.settings.live_mode:
            self.journal.set_runtime_state(
                self._live_bar_state_key(),
                {
                    "fingerprint": bundle.latest_closed_bar_fingerprint(),
                    "recorded_at": utc_now().isoformat(),
                    "symbol": verdict.symbol,
                    "action": verdict.final_action,
                    "order_status": result.status,
                },
            )
            self._clear_exchange_backoff()
        self.journal.finish_run(run_id, "completed", summary)
        self.notifier.send({"event": "run_completed", **summary})
        return summary

    def _record_successful_position_management(self, verdict, result) -> None:
        if verdict.final_action != "close" or verdict.close_fraction >= 1.0:
            return
        if result.status in {"live_rejected", "paper_rejected"}:
            return
        raw = result.raw or {}
        if not raw.get("partial_close"):
            return
        if raw.get("emergency_flatten") is not None:
            return
        if float(raw.get("remaining_quantity") or 0.0) <= 0.0:
            return
        open_run_id = verdict.management_open_run_id
        if open_run_id is None:
            return

        done_key = self.risk_engine._partial_take_profit_done_key(verdict.symbol, int(open_run_id))
        current = self.journal.get_runtime_state(done_key, {})
        count = int((current or {}).get("count") or 0) if isinstance(current, dict) else int(current or 0)
        self.journal.set_runtime_state(
            done_key,
            {
                "count": count + 1,
                "fraction": verdict.close_fraction,
                "recorded_at": utc_now().isoformat(),
                "order_status": result.status,
                "remaining_quantity": raw.get("remaining_quantity"),
            },
        )
        breakeven_key = self.risk_engine._breakeven_stop_armed_key(verdict.symbol, int(open_run_id))
        self.journal.set_runtime_state(
            breakeven_key,
            {
                "armed": True,
                "recorded_at": utc_now().isoformat(),
                "stop_price": verdict.remaining_stop_price,
                "take_profit_price": verdict.remaining_take_profit_price,
                "remaining_quantity": raw.get("remaining_quantity"),
            },
        )

    def _record_successful_protective_refresh(self, verdict, result) -> None:
        if not verdict.protective_refresh_only:
            return
        if result.status != "protective_refreshed":
            return
        open_run_id = verdict.management_open_run_id
        if open_run_id is None:
            return
        breakeven_key = self.risk_engine._breakeven_stop_armed_key(verdict.symbol, int(open_run_id))
        previous = self.journal.get_runtime_state(breakeven_key, {})
        payload = dict(previous or {}) if isinstance(previous, dict) else {}
        payload.update(
            {
                "armed": True,
                "recorded_at": utc_now().isoformat(),
                "stop_price": verdict.remaining_stop_price,
                "take_profit_price": verdict.remaining_take_profit_price,
                "refresh_reason": verdict.protective_refresh_reason,
                "refresh_status": result.status,
            }
        )
        self.journal.set_runtime_state(breakeven_key, payload)

    def healthcheck(self) -> dict:
        relay_health = self._relay_health()
        active_backoff = self._active_exchange_backoff()
        if active_backoff is not None:
            return {
                "relay_ok": relay_health["relay_ok"],
                "relay_error": relay_health["relay_error"],
                "binance_ok": False,
                "binance_error": f"exchange_backoff_active until {active_backoff['until_ms']}",
                "exchange_id": self.settings.exchange_id,
                "mode": self.settings.mode,
                "market_type": self.settings.market_type,
                "cached": True,
            }
        cached_preflight = self.safety_checks.cached_preflight()
        if cached_preflight is not None:
            public_api = cached_preflight.get("public_api", {})
            symbols_ok = cached_preflight.get("symbols_ok", {})
            return {
                "relay_ok": relay_health["relay_ok"],
                "relay_error": relay_health["relay_error"],
                "binance_ok": bool(public_api.get("ok")) and bool(symbols_ok.get("ok")),
                "binance_error": public_api.get("error") or symbols_ok.get("error"),
                "exchange_id": self.settings.exchange_id,
                "mode": self.settings.mode,
                "market_type": self.settings.market_type,
                "cached": True,
            }
        public_checks = self.safety_checks.run_public()
        public_api = public_checks.get("public_api", {})
        symbols_ok = public_checks.get("symbols_ok", {})
        binance_ok = bool(public_api.get("ok")) and bool(symbols_ok.get("ok"))
        binance_error = public_api.get("error") or symbols_ok.get("error")

        return {
            "relay_ok": relay_health["relay_ok"],
            "relay_error": relay_health["relay_error"],
            "binance_ok": binance_ok,
            "binance_error": binance_error,
            "exchange_id": self.settings.exchange_id,
            "mode": self.settings.mode,
            "market_type": self.settings.market_type,
        }

    def preflight_live(self, arm: bool = False, *, allow_cached_ok: bool = False) -> dict:
        return self.safety_checks.run(arm=arm, allow_cached_ok=allow_cached_ok)

    def paper_status(self) -> dict:
        return {
            "mode": "paper",
            "exchange_id": self.settings.exchange_id,
            "market_type": self.settings.market_type,
            "paper_portfolio": self.journal.get_runtime_state("paper_portfolio", {"free_quote": self.settings.paper_starting_quote, "positions": {}}),
            "recent_runs": self.journal.get_recent_runs(limit=5, mode="paper"),
            "recent_orders": self.journal.get_recent_orders(limit=10, mode="paper"),
        }

    def live_guard_status(self) -> dict:
        return self.safety_checks.live_guard_status()

    def runtime_status(self) -> dict:
        date_key = utc_now().date().isoformat()
        day_start_key = build_day_start_equity_key(
            self.settings.mode,
            self.settings.exchange_id,
            self.settings.market_type,
            self.settings.quote_currency,
            date_key,
        )
        return {
            "mode": self.settings.mode,
            "exchange_id": self.settings.exchange_id,
            "market_type": self.settings.market_type,
            "quote_currency": self.settings.quote_currency,
            "halted": bool(self.journal.get_runtime_state("halted", False)),
            "ai_failure_streak": int(self.journal.get_runtime_state("ai_failure_streak", 0)),
            "day_start_equity_key": day_start_key,
            "day_start_equity": self.journal.get_runtime_state(day_start_key, None),
        }

    def clear_halt(self) -> dict:
        previous = self.runtime_status()
        self.journal.set_runtime_state("halted", False)
        self.journal.set_runtime_state("ai_failure_streak", 0)
        return {
            "ok": True,
            "previous": previous,
            "current": self.runtime_status(),
        }

    def _relay_health(self) -> dict[str, Any]:
        relay_ok = False
        relay_error = None
        request = Request(self.settings.relay_models_url, headers={"Authorization": f"Bearer {self.settings.openai_api_key}"})
        try:
            with urlopen(request, timeout=self.settings.ai_timeout_seconds) as response:
                relay_ok = response.status == 200
        except Exception as exc:
            relay_error = str(exc)
        return {
            "relay_ok": relay_ok,
            "relay_error": relay_error,
        }

    def _latest_live_preflight(self) -> dict[str, Any] | None:
        for run in self.journal.get_recent_runs(limit=10, mode="live"):
            summary = run.get("summary") or {}
            preflight = summary.get("preflight")
            if isinstance(preflight, dict):
                return preflight
        return None

    def _cached_preflight(self) -> dict[str, Any]:
        cached = self._latest_live_preflight()
        if cached is not None:
            payload = dict(cached)
            payload["cached"] = True
            payload["source"] = "recent_run"
            return payload

        account_overview = self.live_analytics.cached_live_overview()
        credentials = {"ok": None, "skipped": "dashboard_light"}
        if account_overview.get("equity_quote") is not None or account_overview.get("quote_free") is not None:
            credentials = {
                "ok": True,
                "quote_currency": account_overview.get("quote_currency", self.settings.quote_currency),
                "quote_total": account_overview.get("equity_quote"),
                "quote_free": account_overview.get("quote_free"),
                "cached": True,
            }
        return {
            "exchange_id": self.settings.exchange_id,
            "mode": self.settings.mode,
            "market_type": self.settings.market_type,
            "symbols": list(self.settings.symbols),
            "resolved_symbols": [],
            "public_api": {"ok": None, "skipped": "dashboard_light"},
            "symbols_ok": {"ok": None, "skipped": "dashboard_light"},
            "credentials": credentials,
            "market_rules": {},
            "position_mode": {"ok": None, "skipped": "dashboard_light"},
            "balance_guard": {"ok": None, "skipped": "dashboard_light"},
            "live_guard": self.live_guard_status(),
            "cached": True,
            "source": "journal_only",
        }

    def _lightweight_healthcheck(self, live_status: dict[str, Any]) -> dict[str, Any]:
        relay_health = self._relay_health()
        preflight = live_status.get("preflight") or {}
        public_api = preflight.get("public_api") or {}
        symbols_ok = preflight.get("symbols_ok") or {}
        binance_ok: bool | None = None
        binance_error = public_api.get("error") or symbols_ok.get("error")
        if public_api.get("ok") is True and symbols_ok.get("ok") is True:
            binance_ok = True
        elif public_api.get("ok") is False or symbols_ok.get("ok") is False:
            binance_ok = False

        if binance_ok is None:
            recent_runs = live_status.get("recent_runs") or []
            latest_run = recent_runs[0] if recent_runs else None
            if latest_run is not None:
                summary = latest_run.get("summary") or {}
                summary_status = summary.get("status")
                if latest_run.get("status") == "completed" or summary_status == "duplicate_bar_skipped":
                    binance_ok = True
                elif summary_status in {"live_preflight_failed", "market_data_failed"}:
                    binance_ok = False
                    binance_error = summary.get("error") or binance_error

        return {
            "relay_ok": relay_health["relay_ok"],
            "relay_error": relay_health["relay_error"],
            "binance_ok": binance_ok,
            "binance_error": binance_error,
            "exchange_id": self.settings.exchange_id,
            "mode": self.settings.mode,
            "market_type": self.settings.market_type,
            "cached": True,
        }

    def live_status(self, include_exchange: bool = True) -> dict:
        preflight = self._cached_preflight() if not include_exchange else self.preflight_live(arm=False, allow_cached_ok=True)
        account_overview = self.live_analytics.cached_live_overview()
        overview_error = None
        if include_exchange and self.settings.live_mode and self.settings.binance_api_key and self.settings.binance_api_secret:
            try:
                account_overview = self.live_analytics.fetch_live_overview()
            except Exception as exc:
                overview_error = str(exc)
        return {
            "mode": self.settings.mode,
            "exchange_id": self.settings.exchange_id,
            "market_type": self.settings.market_type,
            "preflight": preflight,
            "account_overview": account_overview,
            "account_overview_error": overview_error,
            "recent_runs": self.journal.get_recent_runs(limit=5, mode="live"),
            "recent_orders": self.journal.get_recent_orders(limit=10, mode="live"),
        }

    def signal_review(self, limit: int, horizon_bars: int, threshold_pct: float) -> dict:
        return self.review_service.signal_review(limit=limit, horizon_bars=horizon_bars, threshold_pct=threshold_pct)

    def paper_replay(self, include_noop: bool = False) -> dict:
        return self.review_service.paper_replay(include_noop=include_noop)

    def dashboard_snapshot(
        self,
        review_limit: int = 10,
        review_horizon_bars: int = 1,
        review_threshold_pct: float = 0.003,
        *,
        include_exchange: bool = False,
        include_review: bool = False,
    ) -> dict:
        live_status = self.live_status(include_exchange=include_exchange)
        healthcheck = self.healthcheck() if include_exchange else self._lightweight_healthcheck(live_status)
        signal_review = (
            self.signal_review(
                limit=review_limit,
                horizon_bars=review_horizon_bars,
                threshold_pct=review_threshold_pct,
            )
            if include_review
            else {"skipped": "dashboard_light"}
        )
        return {
            "healthcheck": healthcheck,
            "live_status": live_status,
            "paper_status": self.paper_status(),
            "paper_replay": self.paper_replay(include_noop=False),
            "signal_review": signal_review,
            "runtime_status": self.runtime_status(),
            "live_guard": self.live_guard_status(),
        }

    def _write_json_artifact(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _exchange_backoff_key(self) -> str:
        return f"exchange_backoff_until:{self.settings.exchange_id}:{self.settings.market_type}"

    def _active_exchange_backoff(self) -> dict[str, Any] | None:
        payload = self.journal.get_runtime_state(self._exchange_backoff_key(), None)
        if not isinstance(payload, dict):
            return None
        until_ms = int(payload.get("until_ms") or 0)
        now_ms = int(utc_now().timestamp() * 1000)
        if until_ms <= now_ms:
            return None
        return payload

    def _clear_exchange_backoff(self) -> None:
        self.journal.set_runtime_state(self._exchange_backoff_key(), {})

    def _sync_exchange_backoff(self, payload: dict[str, Any]) -> None:
        until_ms = extract_rate_limit_backoff_ms(payload)
        if until_ms is None:
            return
        self.journal.set_runtime_state(
            self._exchange_backoff_key(),
            {
                "until_ms": until_ms,
                "exchange_id": self.settings.exchange_id,
                "market_type": self.settings.market_type,
            },
        )

    def _live_bar_state_key(self) -> str:
        return f"last_live_bar:{self.settings.exchange_id}:{self.settings.market_type}:{self.settings.timeframe}"
