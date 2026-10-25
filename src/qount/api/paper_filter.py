"""Small server-side boundary for the forward Binance paper view."""

from __future__ import annotations

from qount.api.schemas import PaperLine, PositionItem
from qount.binance_assets import (
    BinanceAsset,
    asset_by_execution_symbol,
    asset_by_signal_symbol,
    load_binance_assets,
)


def _asset_for_symbol(symbol: str, assets: tuple[BinanceAsset, ...]) -> BinanceAsset | None:
    return asset_by_execution_symbol(symbol, assets=assets) or asset_by_signal_symbol(symbol, assets=assets)


def normalize_paper_line(line: PaperLine) -> PaperLine:
    """Annotate native execution symbols; never turn proxy returns into USD-M returns."""
    if line.source.venue != "binance_usdm" and is_forward_paper_line(line):
        return line
    assets = load_binance_assets()
    normalized: list[PositionItem] = []
    for position in line.positions:
        asset = _asset_for_symbol(position.symbol, assets)
        if asset is None or asset.status != "active":
            raise ValueError(f"unknown_binance_asset:{position.symbol}")
        if position.venue not in (None, "binance_usdm"):
            raise ValueError(f"paper_venue_invalid:{position.symbol}")
        normalized.append(position.model_copy(update={
            "symbol": asset.execution_symbol,
            "asset_id": asset.asset_id,
            "signal_symbol": asset.signal_symbol,
            "execution_symbol": asset.execution_symbol,
            "venue": asset.venue,
        }))
    return line.model_copy(update={"positions": normalized})


def is_forward_binance_line(line: PaperLine) -> bool:
    """Only fresh, active, source-backed forward lines with known mapped positions."""
    if not line.paper_enabled or line.status != "ACTIVE_PAPER" or line.data_status != "AVAILABLE":
        return False
    if line.freshness != "FRESH" or line.error or line.position_status != "KNOWN":
        return False
    source = line.source
    if source.venue != "binance_usdm" or source.instrument_type != "USD-M":
        return False
    if source.price_source not in {"binance_um_klines", "binance_um_trades"}:
        return False
    # A source may be stored under any filename.  Provenance belongs in the
    # structured source fields; reject explicit proxy/spot labels even if a
    # caller tried to relabel the file as Binance.
    if (source.observation_kind or "").strip().lower() in {
        "proxy", "spot", "1x_spot", "etf_nav", "generic_forward_nav",
    }:
        return False
    try:
        assets = load_binance_assets()
        symbols = source.execution_symbols or [
            position.execution_symbol or position.symbol for position in line.positions
        ]
        if not symbols:
            return False
        for symbol in symbols:
            asset = asset_by_execution_symbol(symbol, assets=assets)
            if asset is None or asset.status != "active":
                return False
            if asset.price_source != source.price_source:
                return False
        normalized = normalize_paper_line(line)
    except (OSError, ValueError):
        return False
    return (
        (not source.execution_symbols or all(position.symbol in source.execution_symbols for position in normalized.positions))
        and normalized.safety.research_only and not normalized.safety.orders_authorized
    )


def is_forward_paper_line(line: PaperLine) -> bool:
    """Personal paper accounts may use their actual market, without Binance relabeling."""
    if line.source.venue == "binance_usdm":
        return is_forward_binance_line(line)
    allowed = {
        ("multi_market", "ETF+SPOT", "yahoo_public_binance_spot"),
        ("multi_market", "ETF+SPOT", "tiingo_public_binance_spot"),
        ("sse_szse", "ETF_ADJUSTED_PROXY", "tencent_public_qfq"),
        ("sse_szse", "ETF", "tencent_public_raw_and_qfq"),
        ("us_etf", "ETF", "yahoo_public"),
        ("us_etf", "ETF", "yahoo_public_raw+issuer_cash_distributions"),
    }
    source=line.source
    qualified_sample=(line.sample_kind=="forward" and source.observation_kind=="forward_paper") or (
        line.sample_kind=="mixed" and source.observation_kind=="continuous_paper" and source.segments)
    return bool(line.paper_enabled and qualified_sample and
        line.status=="ACTIVE_PAPER" and line.data_status=="AVAILABLE" and
        line.freshness=="FRESH" and not line.error and line.position_status=="KNOWN" and
        source.sha256 and source.execution_symbols and
        (source.venue,source.instrument_type,source.price_source) in allowed and
        all(p.symbol in source.execution_symbols or (
            p.symbol=="DIVIDEND_RECEIVABLE" and source.venue=="us_etf" and
            source.price_source=="yahoo_public_raw+issuer_cash_distributions") for p in line.positions) and
        line.safety.research_only and not line.safety.orders_authorized)

