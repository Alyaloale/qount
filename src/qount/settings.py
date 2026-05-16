from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "live"}


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    return float(raw) if raw is not None else default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw is not None else default


def _env_list(name: str, default: list[str]) -> tuple[str, ...]:
    raw = _env(name)
    if raw is None:
        return tuple(default)
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return tuple(values or default)


def _normalize_market_type(raw: str | None) -> str:
    value = (raw or "spot").strip().lower()
    if value in {"future", "futures", "swap", "contract", "perp", "perpetual"}:
        return "future"
    return "spot"


def _normalize_margin_mode(raw: str | None) -> str:
    value = (raw or "isolated").strip().lower()
    if value in {"cross", "crossed"}:
        return "cross"
    return "isolated"


@dataclass(frozen=True)
class Settings:
    project_root: Path
    state_dir: Path
    snapshot_dir: Path
    decision_dir: Path
    log_dir: Path
    db_path: Path
    system_prompt_path: Path
    decision_prompt_path: Path
    mode: str
    exchange_id: str
    market_type: str
    live_enable: bool
    live_confirmation: str | None
    openai_base_url: str
    openai_api_key: str
    ai_model: str
    ai_timeout_seconds: int
    symbols: tuple[str, ...]
    timeframe: str
    lookback_bars: int
    quote_currency: str
    paper_starting_quote: float
    max_open_positions: int
    max_entry_size_pct: float
    max_risk_per_trade_pct: float
    min_open_size_pct: float
    min_take_profit_pct: float
    daily_loss_limit_pct: float
    min_notional_quote: float
    cooldown_bars_after_losses: int
    estimated_fee_pct: float
    estimated_slippage_pct: float
    risk_sizing_enable: bool
    risk_sizing_include_cost: bool
    min_effective_stop_loss_pct: float
    max_effective_stop_loss_pct: float
    candidate_trend_timeframe: str | None
    min_expected_edge_pct: float
    max_net_directional_exposure_pct: float
    max_correlated_directional_exposure_pct: float
    third_same_direction_edge_buffer_pct: float
    alt_short_edge_penalty_pct: float
    flip_cooldown_bars: int
    min_hold_bars: int
    same_symbol_reentry_cooldown_bars: int
    trailing_profit_arm_pct: float
    trailing_profit_retrace_pct: float
    partial_take_profit_enable: bool
    partial_take_profit_trigger_pct: float
    partial_take_profit_step_pct: float
    partial_take_profit_fraction: float
    partial_take_profit_max_times: int
    breakeven_stop_buffer_pct: float
    dynamic_protective_refresh_enable: bool
    run_delay_seconds: int
    preflight_cache_seconds: int
    http_proxy: str | None
    https_proxy: str | None
    binance_api_key: str | None
    binance_api_secret: str | None
    contract_leverage: int
    contract_margin_mode: str
    notify_webhook_url: str | None

    @property
    def paper_mode(self) -> bool:
        return self.mode == "paper"

    @property
    def live_mode(self) -> bool:
        return self.mode == "live"

    @property
    def contract_market(self) -> bool:
        return self.market_type == "future"

    @property
    def ccxt_default_type(self) -> str:
        return "future" if self.contract_market else "spot"

    @property
    def relay_models_url(self) -> str:
        base = self.openai_base_url.rstrip("/")
        return f"{base}/models"

    @classmethod
    def from_env(cls) -> "Settings":
        project_root = Path(_env("QOUNT_PROJECT_ROOT", str(PROJECT_ROOT)) or str(PROJECT_ROOT)).expanduser()
        state_dir = project_root / "state"
        return cls(
            project_root=project_root,
            state_dir=state_dir,
            snapshot_dir=state_dir / "snapshots",
            decision_dir=state_dir / "decisions",
            log_dir=state_dir / "logs",
            db_path=state_dir / "qount.db",
            system_prompt_path=project_root / "prompts" / "system_prompt_v1.txt",
            decision_prompt_path=project_root / "prompts" / "decision_prompt_v1.txt",
            mode=(_env("QOUNT_MODE", "paper") or "paper").strip().lower(),
            exchange_id=_env("QOUNT_EXCHANGE_ID", "binance") or "binance",
            market_type=_normalize_market_type(_env("QOUNT_MARKET_TYPE", "spot")),
            live_enable=_env_bool("QOUNT_LIVE_ENABLE", False),
            live_confirmation=_env("QOUNT_LIVE_CONFIRMATION"),
            openai_base_url=_env("QOUNT_OPENAI_BASE_URL", "http://192.168.128.1:8318/v1") or "http://192.168.128.1:8318/v1",
            openai_api_key=_env("QOUNT_OPENAI_API_KEY", "my-local-key") or "my-local-key",
            ai_model=_env("QOUNT_AI_MODEL", "gpt-5.4") or "gpt-5.4",
            ai_timeout_seconds=_env_int("QOUNT_AI_TIMEOUT_SECONDS", 40),
            symbols=_env_list("QOUNT_SYMBOLS", ["BTC/USDT", "ETH/USDT"]),
            timeframe=_env("QOUNT_TIMEFRAME", "1h") or "1h",
            lookback_bars=_env_int("QOUNT_LOOKBACK_BARS", 200),
            quote_currency=_env("QOUNT_QUOTE_CURRENCY", "USDT") or "USDT",
            paper_starting_quote=_env_float("QOUNT_PAPER_STARTING_QUOTE", 200.0),
            max_open_positions=_env_int("QOUNT_MAX_OPEN_POSITIONS", 1),
            max_entry_size_pct=_env_float("QOUNT_MAX_ENTRY_SIZE_PCT", 0.30),
            max_risk_per_trade_pct=_env_float("QOUNT_MAX_RISK_PER_TRADE_PCT", 0.01),
            min_open_size_pct=_env_float("QOUNT_MIN_OPEN_SIZE_PCT", 0.10),
            min_take_profit_pct=_env_float("QOUNT_MIN_TAKE_PROFIT_PCT", 0.015),
            daily_loss_limit_pct=_env_float("QOUNT_DAILY_LOSS_LIMIT_PCT", 0.03),
            min_notional_quote=_env_float("QOUNT_MIN_NOTIONAL_QUOTE", 25.0),
            cooldown_bars_after_losses=_env_int("QOUNT_COOLDOWN_BARS_AFTER_LOSSES", 3),
            estimated_fee_pct=_env_float("QOUNT_ESTIMATED_FEE_PCT", 0.0004),
            estimated_slippage_pct=_env_float("QOUNT_ESTIMATED_SLIPPAGE_PCT", 0.0002),
            risk_sizing_enable=_env_bool("QOUNT_RISK_SIZING_ENABLE", True),
            risk_sizing_include_cost=_env_bool("QOUNT_RISK_SIZING_INCLUDE_COST", True),
            min_effective_stop_loss_pct=_env_float("QOUNT_MIN_EFFECTIVE_STOP_LOSS_PCT", 0.005),
            max_effective_stop_loss_pct=_env_float("QOUNT_MAX_EFFECTIVE_STOP_LOSS_PCT", 0.03),
            candidate_trend_timeframe=_env("QOUNT_CANDIDATE_TREND_TIMEFRAME", "1h"),
            min_expected_edge_pct=_env_float("QOUNT_MIN_EXPECTED_EDGE_PCT", 0.0025),
            max_net_directional_exposure_pct=_env_float("QOUNT_MAX_NET_DIRECTIONAL_EXPOSURE_PCT", 0.40),
            max_correlated_directional_exposure_pct=_env_float("QOUNT_MAX_CORRELATED_DIRECTIONAL_EXPOSURE_PCT", 0.30),
            third_same_direction_edge_buffer_pct=_env_float("QOUNT_THIRD_SAME_DIRECTION_EDGE_BUFFER_PCT", 0.00075),
            alt_short_edge_penalty_pct=_env_float("QOUNT_ALT_SHORT_EDGE_PENALTY_PCT", 0.00075),
            flip_cooldown_bars=_env_int("QOUNT_FLIP_COOLDOWN_BARS", 2),
            min_hold_bars=_env_int("QOUNT_MIN_HOLD_BARS", 2),
            same_symbol_reentry_cooldown_bars=_env_int("QOUNT_SAME_SYMBOL_REENTRY_COOLDOWN_BARS", 3),
            trailing_profit_arm_pct=_env_float("QOUNT_TRAILING_PROFIT_ARM_PCT", 0.01),
            trailing_profit_retrace_pct=_env_float("QOUNT_TRAILING_PROFIT_RETRACE_PCT", 0.005),
            partial_take_profit_enable=_env_bool("QOUNT_PARTIAL_TAKE_PROFIT_ENABLE", True),
            partial_take_profit_trigger_pct=_env_float("QOUNT_PARTIAL_TAKE_PROFIT_TRIGGER_PCT", 0.012),
            partial_take_profit_step_pct=_env_float("QOUNT_PARTIAL_TAKE_PROFIT_STEP_PCT", 0.012),
            partial_take_profit_fraction=_env_float("QOUNT_PARTIAL_TAKE_PROFIT_FRACTION", 0.50),
            partial_take_profit_max_times=max(0, _env_int("QOUNT_PARTIAL_TAKE_PROFIT_MAX_TIMES", 1)),
            breakeven_stop_buffer_pct=_env_float("QOUNT_BREAKEVEN_STOP_BUFFER_PCT", 0.0012),
            dynamic_protective_refresh_enable=_env_bool("QOUNT_DYNAMIC_PROTECTIVE_REFRESH_ENABLE", True),
            run_delay_seconds=_env_int("QOUNT_RUN_DELAY_SECONDS", 60),
            preflight_cache_seconds=max(0, _env_int("QOUNT_PREFLIGHT_CACHE_SECONDS", 900)),
            http_proxy=_env("QOUNT_HTTP_PROXY", _env("HTTP_PROXY")),
            https_proxy=_env("QOUNT_HTTPS_PROXY", _env("HTTPS_PROXY")),
            binance_api_key=_env("QOUNT_BINANCE_API_KEY"),
            binance_api_secret=_env("QOUNT_BINANCE_API_SECRET"),
            contract_leverage=max(1, _env_int("QOUNT_CONTRACT_LEVERAGE", 3)),
            contract_margin_mode=_normalize_margin_mode(_env("QOUNT_CONTRACT_MARGIN_MODE", "isolated")),
            notify_webhook_url=_env("QOUNT_NOTIFY_WEBHOOK_URL"),
        )

    def ensure_directories(self) -> None:
        for path in (self.state_dir, self.snapshot_dir, self.decision_dir, self.log_dir):
            path.mkdir(parents=True, exist_ok=True)
