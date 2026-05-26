from __future__ import annotations

from dataclasses import replace

from .settings import Settings


ETH_ONLY_PROFILE = "eth-only"
ETH_ONLY_SETUP_MODEL = "setup_edge_model_short_rebound_phase6.json"
ETH_ONLY_SETUP_MODEL_HORIZON_BARS = 6
ETH_ONLY_SETUP_MODEL_SPLIT_HIGHER_PHASE = True
ETH_ONLY_TRAILING_PROFIT_ARM_PCT = 0.0018
ETH_ONLY_TRAILING_PROFIT_RETRACE_PCT = 0.003
DEFAULT_SETUP_MODEL_HORIZON_BARS = 3
DEFAULT_SETUP_MODEL_SPLIT_HIGHER_PHASE = False


def normalize_research_profile(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip().lower().replace("_", "-")
    if value in {"eth", "eth-only", "eth-only-short", "eth-structural"}:
        return ETH_ONLY_PROFILE
    raise ValueError(f"unknown_research_profile:{raw}")


def apply_research_profile(settings: Settings, raw_profile: str | None) -> Settings:
    profile = normalize_research_profile(raw_profile)
    if profile is None:
        return settings
    if profile != ETH_ONLY_PROFILE:
        raise ValueError(f"unsupported_research_profile:{raw_profile}")

    return replace(
        settings,
        market_type="future",
        live_enable=False,
        rule_mode="bottom_line",
        symbols=("ETH/USDT",),
        max_open_positions=1,
        hourly_model_enable=False,
        setup_model_enable=True,
        setup_model_path=settings.project_root / "state" / "models" / ETH_ONLY_SETUP_MODEL,
        trailing_profit_arm_pct=ETH_ONLY_TRAILING_PROFIT_ARM_PCT,
        trailing_profit_retrace_pct=ETH_ONLY_TRAILING_PROFIT_RETRACE_PCT,
    )


def setup_model_horizon_bars_for_profile(raw_profile: str | None, explicit_value: int | None) -> int:
    if explicit_value is not None:
        return explicit_value
    profile = normalize_research_profile(raw_profile)
    if profile == ETH_ONLY_PROFILE:
        return ETH_ONLY_SETUP_MODEL_HORIZON_BARS
    return DEFAULT_SETUP_MODEL_HORIZON_BARS


def setup_model_split_higher_phase_for_profile(raw_profile: str | None, explicit_value: bool | None) -> bool:
    if explicit_value is not None:
        return explicit_value
    profile = normalize_research_profile(raw_profile)
    if profile == ETH_ONLY_PROFILE:
        return ETH_ONLY_SETUP_MODEL_SPLIT_HIGHER_PHASE
    return DEFAULT_SETUP_MODEL_SPLIT_HIGHER_PHASE
