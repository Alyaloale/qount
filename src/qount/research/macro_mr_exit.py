"""Fixed causal alternatives for MR trend invalidation, research only."""
from qount.research_data.regime import compute_ema


PROFILES = ("control", "two_closes", "price200")
COMMODITIES = {"XAUUSDT", "COPPERUSDT", "CLUSDT"}


class RejectionLowHolding:
    """The entry rejection candle supplies the frozen MR invalidation level.

    Compare completed closes, never the current candle's low or close. Equity
    holdings can additionally retain the SPY rejection-day low as a market
    failure level; this is a separately evaluated component.
    """
    def __init__(self, proxy_bars, *, systemic=False):
        self.bars = {s: {b.t: b for b in stream} for s, stream in proxy_bars.items()}
        self.systemic = systemic

    def __call__(self, position, feature, now, original):
        symbol = position.get("source_symbol", position["symbol"])
        anchor = position.get("feature_available", position.get("signal_time"))
        available = feature["available"]
        if anchor is None or not anchor < position["entry_time"] <= now or not anchor <= available < now:
            raise ValueError("noncausal_rejection_low_context")
        allowed = self.bars[symbol][available].c >= self.bars[symbol][anchor].l
        if self.systemic and symbol not in COMMODITIES:
            allowed = allowed and self.bars["SPYUSDT"][available].c >= self.bars["SPYUSDT"][anchor].l
        return allowed


def holding_profiles(proxy_bars, features):
    """Keep entry fields unchanged; replace the predicate used by MR holdings only.

    two_closes requires two distinct completed proxy sessions to lose the old
    trend qualification. price200 retains qualification while own close (and,
    for equities, SPY close) is above EMA200, relaxing the slower EMA50/return63
    components. Stops and funding-cash/risk caps are outside this function.
    """
    prices = {}
    for symbol, bars in proxy_bars.items():
        if [b.t for b in bars] != sorted({b.t for b in bars}):
            raise ValueError("ordered_proxy_sessions_required")
        ema = compute_ema([b.c for b in bars], 200)
        prices[symbol] = {b.t: (b.c, avg) for b, avg in zip(bars, ema)}
    if "SPYUSDT" not in prices or set(features) != set(proxy_bars):
        raise ValueError("complete_proxy_universe_required")
    result = {name: {} for name in PROFILES}
    diagnostics = []
    for symbol, rows in features.items():
        if [f["available"] for f in rows] != sorted({f["available"] for f in rows}):
            raise ValueError("ordered_feature_sessions_required")
        previous = False
        for name in result:
            result[name][symbol] = []
        for f in rows:
            now, original = f["available"], f["hold_structural"]
            close, ema = prices[symbol][now]
            spy, spy_ema = prices["SPYUSDT"][now]
            price = close > ema and (symbol in COMMODITIES or spy > spy_ema)
            flags = dict(control=original, two_closes=original or previous,
                         price200=original or price)
            for name, allowed in flags.items():
                updated = dict(f, hold_structural=allowed)
                assert {k: v for k, v in updated.items() if k != "hold_structural"} == {
                    k: v for k, v in f.items() if k != "hold_structural"}
                result[name][symbol].append(updated)
            diagnostics.append(dict(symbol=symbol, available=now, date=f["date"],
                own_close=close, own_ema200=ema, spy_close=spy, spy_ema200=spy_ema,
                original=original, previous_original=previous, **{k: flags[k] for k in PROFILES[1:]}))
            previous = original
    assert result["control"] == features
    return result, diagnostics
