"""Four fixed setup-specific exit controls, chosen before earlier-window payoffs."""


def setup_policies(trend_days, mean_reversion_days):
    if trend_days not in (7, 21) or mean_reversion_days not in (7, 21):
        raise ValueError("fixed_setup_horizons_only")
    return {setup: dict(max_hold_hours=24*days, hold_feature="hold_tactical" if days == 7 else "hold_structural")
            for setup, days in (("breakout", trend_days), ("pullback", trend_days), ("mean_reversion", mean_reversion_days))}


ARMS = {"attack7": (7, 7), "structural21": (21, 21), "trend7_mr21": (7, 21), "trend21_mr7": (21, 7)}
