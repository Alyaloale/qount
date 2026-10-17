"""Dated unit-NAV metrics, shared by offline studies."""
from __future__ import annotations

import math


def nav_metrics(points, *, sampling="hourly_close"):
    if len(points) < 2 or any(b["t"] <= a["t"] for a,b in zip(points,points[1:])):
        raise ValueError("ordered_nav_points_required")
    values = [float(p["nav"]) for p in points]
    if values[0] <= 0 or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("invalid_unit_nav")
    peak, drawdown = values[0], 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = max(drawdown, 1-value/peak)
    days = (points[-1]["t"]-points[0]["t"])/86400
    total = values[-1]/values[0]-1
    cagr = (values[-1]/values[0])**(365.25/days)-1 if days >= 365.25 else None
    return dict(total_return_pct=100*total, max_drawdown_pct=100*drawdown,
                current_drawdown_pct=100*(1-values[-1]/peak),
                cagr_pct=100*cagr if cagr is not None else None,
                calmar=cagr/drawdown if cagr is not None and drawdown > 0 else None,
                days=days, nav_sampling=sampling, annualization="calendar_365.25; suppressed_below_one_year")
