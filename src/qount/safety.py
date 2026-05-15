from __future__ import annotations

import json
import re
from typing import Any

from .exchange_utils import ExchangePool
from .exchange_utils import build_exchange
from .exchange_utils import extract_quote_balance
from .exchange_utils import market_amount_step
from .exchange_utils import resolve_market_symbols
from .journal import Journal
from .models import MarketSnapshotBundle
from .models import utc_now
from .settings import Settings

LIVE_CONFIRMATION_PHRASE = "I_UNDERSTAND_LIVE_TRADING"
_RATE_LIMIT_BAN_RE = re.compile(r"banned until (\d+)")


def extract_rate_limit_backoff_ms(payload: Any) -> int | None:
    pending = [payload]
    latest: int | None = None
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            pending.extend(current.values())
            continue
        if isinstance(current, list):
            pending.extend(current)
            continue
        if not isinstance(current, str):
            continue
        match = _RATE_LIMIT_BAN_RE.search(current)
        if match is None:
            continue
        candidate = int(match.group(1))
        latest = max(latest or 0, candidate)
    return latest


class LiveSafetyChecks:
    def __init__(self, settings: Settings, journal: Journal, exchange_pool: ExchangePool | None = None) -> None:
        self.settings = settings
        self.journal = journal
        self.exchange_pool = exchange_pool or ExchangePool(settings)

    def run_public(self) -> dict[str, Any]:
        checks: dict[str, Any] = {
            "exchange_id": self.settings.exchange_id,
            "mode": self.settings.mode,
            "market_type": self.settings.market_type,
            "symbols": list(self.settings.symbols),
            "resolved_symbols": [],
            "public_api": {"ok": False},
            "symbols_ok": {"ok": False},
            "market_rules": {},
        }

        public_exchange = self.exchange_pool.public()
        try:
            server_time = public_exchange.fetch_time()
            checks["public_api"] = {"ok": True, "server_time": server_time}
        except Exception as exc:
            checks["public_api"] = {"ok": False, "error": str(exc)}

        try:
            markets = public_exchange.load_markets()
            resolved_symbols = resolve_market_symbols(markets, self.settings.symbols, self.settings)
            checks["resolved_symbols"] = list(resolved_symbols)
            checks["symbols_ok"] = {"ok": True, "missing": []}
            rules: dict[str, Any] = {}
            for symbol in resolved_symbols:
                market = markets[symbol]
                limits = market.get("limits", {})
                cost_limit = (limits.get("cost") or {}).get("min")
                amount_limit = (limits.get("amount") or {}).get("min")
                rules[symbol] = {
                    "cost_min": cost_limit,
                    "amount_min": amount_limit,
                    "amount_step": market_amount_step(market),
                    "precision_amount": (market.get("precision") or {}).get("amount"),
                    "quote": market.get("quote"),
                    "base": market.get("base"),
                }
            checks["market_rules"] = rules
        except Exception as exc:
            checks["symbols_ok"] = {"ok": False, "error": str(exc)}
        return checks

    def invalidate_cached_preflight(self) -> None:
        self.journal.set_runtime_state(self._preflight_cache_key(), {})

    def cached_preflight(self) -> dict[str, Any] | None:
        return self._cached_preflight()

    def run(self, arm: bool = False, *, allow_cached_ok: bool = False) -> dict[str, Any]:
        if allow_cached_ok:
            cached = self._cached_preflight()
            if cached is not None:
                return cached

        public_checks = self.run_public()
        checks: dict[str, Any] = {
            **public_checks,
            "credentials": {"ok": False},
            "position_mode": {"ok": True, "skipped": "spot_market"},
            "balance_guard": {"ok": False, "skipped": "no_account_context"},
            "live_guard": {
                "ok": False,
                "arm_requested": arm,
                "live_enable": self.settings.live_enable,
                "confirmation_ok": self.settings.live_confirmation == LIVE_CONFIRMATION_PHRASE,
            },
        }
        resolved_symbols = tuple(str(symbol) for symbol in public_checks.get("resolved_symbols") or [])

        if self.settings.mode != "live":
            checks["credentials"] = {"ok": True, "skipped": "paper_mode"}
            checks["balance_guard"] = {"ok": True, "skipped": "paper_mode"}
            return self._finalize_checks(checks, arm)

        if not self.settings.binance_api_key or not self.settings.binance_api_secret:
            checks["credentials"] = {"ok": False, "error": "missing_api_credentials"}
            return self._finalize_checks(checks, arm)

        try:
            private_exchange = self.exchange_pool.private()
            sync_clock = getattr(private_exchange, "load_time_difference", None)
            if callable(sync_clock):
                sync_clock()
            balance = private_exchange.fetch_balance()
            quote_balance = extract_quote_balance(balance, self.settings)
            quote_total = quote_balance["quote_total"]
            quote_free = quote_balance["quote_free"]
            checks["credentials"] = {
                "ok": True,
                "quote_currency": self.settings.quote_currency,
                "quote_total": quote_total,
                "quote_free": quote_free,
            }
            if self.settings.contract_market:
                if resolved_symbols:
                    position_mode = private_exchange.fetch_position_mode(params={"subType": "linear"})
                    checks["position_mode"] = {
                        "ok": not bool(position_mode.get("hedged")),
                        "hedged": bool(position_mode.get("hedged")),
                        "required": "oneway",
                    }
                leverage = float(self.settings.contract_leverage)
                min_required_margin = max(self.settings.min_notional_quote, quote_total * self.settings.max_entry_size_pct)
                available_notional = quote_free * leverage
                max_risk_capped_margin_quote = quote_total * self.settings.max_entry_size_pct
                max_risk_capped_entry_quote = max_risk_capped_margin_quote * leverage
                reachable_symbols = [
                    symbol
                    for symbol, rules in checks["market_rules"].items()
                    if max_risk_capped_entry_quote >= max(
                        float(rules.get("cost_min") or 0.0),
                        self.settings.min_notional_quote * leverage,
                    )
                ]
                checks["balance_guard"] = {
                    "ok": available_notional >= self.settings.min_notional_quote * leverage and bool(reachable_symbols),
                    "quote_free": quote_free,
                    "quote_total": quote_total,
                    "available_notional_quote": available_notional,
                    "max_risk_capped_entry_quote": max_risk_capped_entry_quote,
                    "max_risk_capped_margin_quote": max_risk_capped_margin_quote,
                    "planned_entry_quote": min_required_margin,
                    "min_notional_quote": self.settings.min_notional_quote,
                    "contract_leverage": self.settings.contract_leverage,
                    "reachable_symbols": reachable_symbols,
                    "reason": None if reachable_symbols else "all_symbols_below_exchange_min_cost_at_current_risk_cap",
                }
            else:
                min_required = max(self.settings.min_notional_quote, quote_total * self.settings.max_entry_size_pct)
                reachable_symbols = [
                    symbol
                    for symbol, rules in checks["market_rules"].items()
                    if quote_total * self.settings.max_entry_size_pct >= float(rules.get("cost_min") or self.settings.min_notional_quote)
                ]
                checks["balance_guard"] = {
                    "ok": quote_free >= self.settings.min_notional_quote and bool(reachable_symbols),
                    "quote_free": quote_free,
                    "quote_total": quote_total,
                    "max_risk_capped_entry_quote": quote_total * self.settings.max_entry_size_pct,
                    "planned_entry_quote": min_required,
                    "min_notional_quote": self.settings.min_notional_quote,
                    "reachable_symbols": reachable_symbols,
                    "reason": None if reachable_symbols else "all_symbols_below_exchange_min_cost_at_current_risk_cap",
                }
        except Exception as exc:
            if not checks["credentials"].get("ok"):
                checks["credentials"] = {"ok": False, "error": str(exc)}
            if self.settings.contract_market:
                checks["position_mode"] = {"ok": False, "error": str(exc)}
            return self._finalize_checks(checks, arm)

        return self._finalize_checks(checks, arm)

    def _guard_reason(
        self,
        *,
        mode_match: bool,
        live_enable: bool,
        confirmation_ok: bool,
        preconditions_ok: bool | None = None,
    ) -> str | None:
        if not mode_match:
            return "paper_mode"
        if not live_enable:
            return "live_disabled"
        if not confirmation_ok:
            return "confirmation_missing"
        if preconditions_ok is False:
            return "preflight_failed"
        return None

    def _build_live_guard(self, arm: bool, checks: dict[str, Any]) -> dict[str, Any]:
        confirmation_ok = self.settings.live_confirmation == LIVE_CONFIRMATION_PHRASE
        mode_match = self.settings.live_mode
        preconditions_ok = (
            bool(checks["public_api"].get("ok"))
            and bool(checks["symbols_ok"].get("ok"))
            and bool(checks["credentials"].get("ok"))
            and bool(checks["balance_guard"].get("ok"))
            and bool(checks["position_mode"].get("ok"))
        )
        legacy_state = self.journal.get_runtime_state("live_guard", None)
        enabled = mode_match and self.settings.live_enable and confirmation_ok
        payload = {
            "ok": enabled and preconditions_ok,
            "armed": enabled,
            "arm_requested": arm,
            "live_enable": self.settings.live_enable,
            "confirmation_ok": confirmation_ok,
            "persistent": True,
            "market_type": self.settings.market_type,
            "mode_match": mode_match,
            "exchange_match": True,
            "market_type_match": True,
            "timeframe_match": True,
            "symbols_match": True,
        }
        reason = self._guard_reason(
            mode_match=mode_match,
            live_enable=self.settings.live_enable,
            confirmation_ok=confirmation_ok,
            preconditions_ok=preconditions_ok,
        )
        if reason:
            payload["reason"] = reason
        if arm:
            payload["note"] = "arm_flag_ignored_persistent_live_guard"
        if isinstance(legacy_state, dict):
            payload["legacy_state"] = legacy_state
        return payload

    def live_guard_status(self) -> dict[str, Any]:
        confirmation_ok = self.settings.live_confirmation == LIVE_CONFIRMATION_PHRASE
        mode_match = self.settings.live_mode
        legacy_state = self.journal.get_runtime_state("live_guard", None)
        enabled = mode_match and self.settings.live_enable and confirmation_ok
        payload = {
            "ok": enabled,
            "armed": enabled,
            "persistent": True,
            "mode_match": mode_match,
            "exchange_match": True,
            "market_type_match": True,
            "timeframe_match": True,
            "symbols_match": True,
            "live_enable": self.settings.live_enable,
            "confirmation_ok": confirmation_ok,
            "state": {
                "exchange_id": self.settings.exchange_id,
                "market_type": self.settings.market_type,
                "symbols": list(self.settings.symbols),
                "timeframe": self.settings.timeframe,
                "persistent": True,
            },
        }
        reason = self._guard_reason(
            mode_match=mode_match,
            live_enable=self.settings.live_enable,
            confirmation_ok=confirmation_ok,
        )
        if reason:
            payload["reason"] = reason
        if isinstance(legacy_state, dict):
            payload["legacy_state"] = legacy_state
        return payload

    def validate_bundle(self, bundle: MarketSnapshotBundle, *, arm: bool = False) -> dict[str, Any]:
        checks: dict[str, Any] = {
            "exchange_id": self.settings.exchange_id,
            "mode": self.settings.mode,
            "market_type": self.settings.market_type,
            "symbols": list(self.settings.symbols),
            "resolved_symbols": [snapshot.symbol for snapshot in bundle.symbols],
            "public_api": {"ok": True, "skipped": "bundle_fetch_succeeded"},
            "symbols_ok": {"ok": True, "missing": []},
            "market_rules": {
                snapshot.symbol: {
                    "cost_min": snapshot.exchange_min_cost_quote,
                    "amount_min": snapshot.exchange_min_amount,
                    "amount_step": snapshot.exchange_amount_step,
                    "precision_amount": None,
                    "quote": self.settings.quote_currency,
                    "base": snapshot.symbol.split("/")[0],
                }
                for snapshot in bundle.symbols
            },
            "credentials": {
                "ok": True,
                "quote_currency": bundle.account.quote_currency,
                "quote_total": bundle.account.equity_quote,
                "quote_free": bundle.account.free_quote,
                "source": "bundle_fetch_succeeded",
            },
            "position_mode": {"ok": True, "skipped": "run_once_hot_path"},
            "balance_guard": {"ok": False, "skipped": "no_account_context"},
            "live_guard": {
                "ok": False,
                "arm_requested": arm,
                "live_enable": self.settings.live_enable,
                "confirmation_ok": self.settings.live_confirmation == LIVE_CONFIRMATION_PHRASE,
            },
        }

        cached = self._cached_preflight()
        if isinstance(cached, dict):
            cached_position_mode = cached.get("position_mode")
            if isinstance(cached_position_mode, dict):
                checks["position_mode"] = cached_position_mode

        quote_total = float(bundle.account.equity_quote)
        quote_free = float(bundle.account.free_quote)
        if self.settings.contract_market:
            leverage = float(self.settings.contract_leverage)
            available_notional = quote_free * leverage
            max_risk_capped_margin_quote = quote_total * self.settings.max_entry_size_pct
            max_risk_capped_entry_quote = max_risk_capped_margin_quote * leverage
            reachable_symbols = [
                snapshot.symbol
                for snapshot in bundle.symbols
                if max_risk_capped_entry_quote >= max(
                    float(snapshot.exchange_min_cost_quote or 0.0),
                    self.settings.min_notional_quote * leverage,
                )
            ]
            checks["balance_guard"] = {
                "ok": available_notional >= self.settings.min_notional_quote * leverage and bool(reachable_symbols),
                "quote_free": quote_free,
                "quote_total": quote_total,
                "available_notional_quote": available_notional,
                "max_risk_capped_entry_quote": max_risk_capped_entry_quote,
                "max_risk_capped_margin_quote": max_risk_capped_margin_quote,
                "planned_entry_quote": max(self.settings.min_notional_quote, quote_total * self.settings.max_entry_size_pct),
                "min_notional_quote": self.settings.min_notional_quote,
                "contract_leverage": self.settings.contract_leverage,
                "reachable_symbols": reachable_symbols,
                "reason": None if reachable_symbols else "all_symbols_below_exchange_min_cost_at_current_risk_cap",
                "source": "bundle_fetch_succeeded",
            }
        else:
            reachable_symbols = [
                snapshot.symbol
                for snapshot in bundle.symbols
                if quote_total * self.settings.max_entry_size_pct >= float(snapshot.exchange_min_cost_quote or self.settings.min_notional_quote)
            ]
            checks["balance_guard"] = {
                "ok": quote_free >= self.settings.min_notional_quote and bool(reachable_symbols),
                "quote_free": quote_free,
                "quote_total": quote_total,
                "max_risk_capped_entry_quote": quote_total * self.settings.max_entry_size_pct,
                "planned_entry_quote": max(self.settings.min_notional_quote, quote_total * self.settings.max_entry_size_pct),
                "min_notional_quote": self.settings.min_notional_quote,
                "reachable_symbols": reachable_symbols,
                "reason": None if reachable_symbols else "all_symbols_below_exchange_min_cost_at_current_risk_cap",
                "source": "bundle_fetch_succeeded",
            }

        return self._finalize_checks(checks, arm)

    def _preflight_cache_key(self) -> str:
        return f"preflight_cache:{self.settings.exchange_id}:{self.settings.market_type}"

    def _preflight_cache_config(self) -> dict[str, Any]:
        return {
            "mode": self.settings.mode,
            "exchange_id": self.settings.exchange_id,
            "market_type": self.settings.market_type,
            "symbols": list(self.settings.symbols),
            "timeframe": self.settings.timeframe,
            "quote_currency": self.settings.quote_currency,
            "contract_leverage": self.settings.contract_leverage,
            "contract_margin_mode": self.settings.contract_margin_mode,
            "live_enable": self.settings.live_enable,
            "confirmation_ok": self.settings.live_confirmation == LIVE_CONFIRMATION_PHRASE,
            "has_credentials": bool(self.settings.binance_api_key and self.settings.binance_api_secret),
        }

    def _full_preflight_ok(self, checks: dict[str, Any]) -> bool:
        return (
            bool((checks.get("public_api") or {}).get("ok"))
            and bool((checks.get("symbols_ok") or {}).get("ok"))
            and bool((checks.get("credentials") or {}).get("ok"))
            and bool((checks.get("balance_guard") or {}).get("ok"))
            and bool((checks.get("position_mode") or {}).get("ok"))
            and bool((checks.get("live_guard") or {}).get("ok"))
        )

    def _cached_preflight(self) -> dict[str, Any] | None:
        payload = self.journal.get_runtime_state(self._preflight_cache_key(), None)
        if not isinstance(payload, dict) or not payload:
            return None
        if payload.get("config") != self._preflight_cache_config():
            return None
        checked_at_ms = int(payload.get("checked_at_ms") or 0)
        now_ms = int(utc_now().timestamp() * 1000)
        if checked_at_ms <= 0 or now_ms - checked_at_ms > self.settings.preflight_cache_seconds * 1000:
            return None
        checks = payload.get("checks")
        if not isinstance(checks, dict) or not self._full_preflight_ok(checks):
            return None
        cached = json.loads(json.dumps(checks))
        cached["cached"] = True
        cached["source"] = "runtime_state"
        return cached

    def _store_preflight_cache(self, checks: dict[str, Any]) -> None:
        if not self._full_preflight_ok(checks):
            self.invalidate_cached_preflight()
            return
        self.journal.set_runtime_state(
            self._preflight_cache_key(),
            {
                "checked_at_ms": int(utc_now().timestamp() * 1000),
                "config": self._preflight_cache_config(),
                "checks": checks,
            },
        )

    def _finalize_checks(self, checks: dict[str, Any], arm: bool) -> dict[str, Any]:
        checks["live_guard"] = self._build_live_guard(arm, checks)
        backoff_until_ms = extract_rate_limit_backoff_ms(checks)
        if backoff_until_ms:
            checks["rate_limit_backoff"] = {
                "active": True,
                "until_ms": backoff_until_ms,
            }
        self._store_preflight_cache(checks)
        return checks
