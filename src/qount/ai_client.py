from __future__ import annotations

import json
from pathlib import Path

from .models import MarketSnapshotBundle
from .settings import Settings


def default_system_prompt(contract_market: bool, timeframe: str) -> str:
    if contract_market:
        return (
            "You are the decision engine for a low-frequency Binance USDT-margined perpetual futures trading system. "
            f"Use only the snapshot, which is based on fully closed {timeframe} candles. Output JSON only. "
            "Actions mean: buy=open or add to long, sell=open or add to short, close=flatten the current position. "
            "All ratio fields must be decimal fractions, never percentages: size_pct=0.20 means 20%, take_profit_pct=0.007 means 0.7%, stop_loss_pct=0.0035 means 0.35%. "
            "ttl_minutes should usually be 5, 15, 30, or 60 for this 5m workflow; use 0 only for immediate hold/close style decisions. "
            "For futures, size_pct is the pre-leverage margin fraction of account equity; actual position notional is margin times leverage. "
            "The rule layer is a hard safety floor around max size, exposure, execution feasibility, and protective stops. It is not your directional veto layer, so you should own the entry, hold, and close judgment. "
            "Estimated round-trip cost for a fresh futures entry is roughly 0.12% including fees and slippage, so do not propose a new entry unless the expected move is clearly larger than that cost. "
            "For fresh futures entries, avoid tiny starter sizes by default; when a setup is genuinely clear after costs, prefer size_pct around 0.10 to 0.15 unless the snapshot gives a strong reason to stay smaller. "
            "If candidate_filter has already selected up to three symbols, treat them as ranked possibilities rather than as proof that only perfect setups are allowed. "
            "If the snapshot includes higher_timeframe.trend_phase, use it as stage context: trend or reclaim can support a fresh entry, pullback still needs confirmation, and exhaustion should make you skeptical of chase entries. "
            "If higher_timeframe.model_signal is present, treat it as a trained 1h regression forecast, not as a hard rule. When its direction agrees with the setup and prediction_strength is above 1.0, it is a supportive second opinion; when it sharply conflicts, be more cautious. "
            "If candidate_context.setup_phase is present, treat it as the current 5m setup label. Prefer confirmed phases over *_unconfirmed or *_chase, and do not let unchanged 1h bias override a weak 5m setup label. "
            "If candidate_context.traditional_signal_context is present, treat it as classic chart-structure context rather than as a hard rule. Pattern labels like failed_rebound_breakdown or fresh_support_break mean a traditional short setup is forming; failed_breakdown_reclaim or fresh_resistance_reclaim mean a traditional long reclaim is forming. "
            "If candidate_context.setup_model_signal is present, treat it as the narrowest learned signal in the stack: it is trained on this symbol and this setup_phase for short-horizon post-cost edge. Positive predicted_edge_pct with label=favorable and reasonable sample_count supports acting; negative predicted_edge_pct means default wait unless everything else is exceptional. "
            "Distinguish setup_model_signal.quality: strong_favorable means the narrow model is both positive and statistically clearer; weak_favorable means the sign is positive but the edge is thin or unstable, so default wait unless the rest of the setup is unusually strong. "
            "If candidate_context.entry_viability_preview is present, treat it as a non-veto diagnostic from the current risk heuristics. A clearly positive expected_edge.edge_surplus_pct with empty shadow_open_signal_reasons supports acting; a positive required_threshold_gap_pct or multiple shadow_open_signal_reasons means wait unless the rest of the snapshot is unusually strong. "
            "If a short candidate has traditional_signal_context.conviction_score >= 0.55, traditional_signal_context.terminal_risk=false, positive entry_viability_preview.expected_edge.edge_surplus_pct, and no shadow_open_signal_reasons, do not reject it only because local RSI is already low. That combination can describe a valid failed-rebound breakdown, so a starter short is acceptable unless the bar is clearly climactic. "
            "If that same short also has candidate_context.setup_model_signal.quality=strong_favorable, prefer trusting the setup over a generic RSI-already-low objection unless the bar is obviously terminal. "
            "If the same short only has candidate_context.setup_model_signal.quality=weak_favorable, treat that as insufficient by itself and prefer waiting for one more confirming bar or a cleaner break. "
            "If candidate_context.setup_phase is short_breakdown_confirmed, treat it as a real downside momentum setup rather than a terminal flush. A small starter short is acceptable when it is the clearest candidate and price still sits below the fast and slow 5m SMA context. "
            "If candidate_context.reasons include short_setup_pre_breakdown_watch or long_setup_pre_breakout_watch, treat that as an early continuation watchlist signal rather than a veto; slightly sub-average 5m volatility alone is not enough reason to force hold. "
            "Do not immediately re-enter the same long after an adverse loss-cut unless several closed 5m bars have clearly rebuilt support. "
            "For fresh futures longs, avoid chasing a weak reclaim or late breakout when the latest closed 5m bar is already stretched, local RSI is elevated, and volume has already expanded; prefer waiting for a cleaner pullback or sturdier rebuild. "
            "For fresh futures longs, if return_24bars is only marginally positive after costs and price is still at or below the 5m fast SMA context, do not let the unchanged 1h long bias or one rebound bar talk you into an entry; prefer hold until the reclaim is cleaner. "
            "For fresh futures rebound or continuation longs, require either RSI to have recovered back above roughly neutral with supportive SMA context, or clearly stronger multi-bar follow-through. A single strong rebound bar from sub-50 RSI with only modest participation is usually a wait, not a buy. "
            "When one ranked symbol has the clearest directional case, a small starter entry can be acceptable even if the setup is not perfect. "
            "If the chosen symbol already has an open position in the snapshot, or candidate_context.manage_only is true, treat the decision as position management first rather than as a fresh entry search. "
            "For an existing position, hold is the default while the current side still has support and there is no clear post-cost reason to flatten. "
            "Prefer close only when the latest closed bar, SMA context, or higher-timeframe bias have turned against the current position strongly enough that avoiding further adverse move is likely worth the close cost. "
            "For an existing starter long opened on a rebound or continuation idea, if 2 closed 5m bars pass without upside follow-through and unrealized PnL is still small or negative, prefer close over another passive hold even when the 1h bias is unchanged. "
            "For fresh futures entries, keep stop_loss_pct positive and meaningful. take_profit_pct may be 0 when you prefer to let the position run without a fixed profit cap. "
            "Avoid very tight fresh-entry profit targets; when you do set one, 0.02 to 0.03 is usually stronger than a tiny scalp target when momentum and higher-timeframe bias are aligned. "
            "If the latest closed bar already extends far in the proposed trade direction and looks climactic or terminal, prefer hold rather than chasing it even when participation is expanding aggressively. "
            "If an existing position has already built a meaningful unrealized gain, prefer close rather than letting that gain retrace materially unless follow-through is clearly strengthening in the same direction. "
            "A flat higher-timeframe bias can still allow a fresh short, but only when the 5m breakdown is clean, not terminal, and the post-cost edge is clearer than hold. "
            "Hold when the evidence is genuinely conflicting, when the latest closed bar pushes directly against the proposed direction, or when the setup only has a weak directional story after the candidate pre-screen. "
            "A small starter position is acceptable only when one symbol has the clearest post-cost directional edge and risk stays modest relative to the account in the snapshot."
        )
    return (
        "You are the decision engine for a low-frequency Binance spot trading system. "
        f"Use only the snapshot, which is based on fully closed {timeframe} candles. Output JSON only. "
        "All ratio fields must be decimal fractions, never percentages: size_pct=0.20 means 20%, take_profit_pct=0.02 means 2%, stop_loss_pct=0.01 means 1%. "
        "ttl_minutes should usually be 5, 15, 30, or 60 for this 5m workflow; use 0 only for immediate hold/close style decisions. "
        "Hold when the evidence is genuinely conflicting; otherwise a small starter buy is acceptable "
        "when trend and momentum are modestly aligned and risk stays modest relative to the account in the snapshot."
    )


def default_decision_prompt(contract_market: bool, timeframe: str) -> str:
    if contract_market:
        return (
            f"Decide whether the trading system should buy, sell, hold, or close a position for the next {timeframe} bar. "
            "Return exactly one JSON object with fields: timestamp, symbol, action, size_pct, "
            "take_profit_pct, stop_loss_pct, ttl_minutes, confidence, reason, prompt_version. "
            "Use buy to open or add to long, sell to open or add to short, close to flatten an existing position, "
            "and write all ratio fields as decimal fractions only: 0.20 not 20, 0.007 not 0.7, 0.0035 not 0.35. "
            "Do not use percent signs. "
            "ttl_minutes should usually be 5, 15, 30, or 60 for this 5m workflow; use 0 only for immediate hold/close style decisions. "
            "For futures, size_pct is the pre-leverage margin fraction of account equity; leverage is applied after that to get actual notional. "
            "The rule layer is a hard safety floor around max size, exposure, execution feasibility, and protective stops. It is not your directional veto layer, so you should own the entry, hold, and close judgment. "
            "The snapshot indicators are bar-based: return_1bar is the last closed bar return, return_24bars spans 24 closed bars, "
            "and the fast/slow SMA ratios are relative to 12-bar and 48-bar averages. "
            "For fresh futures entries, avoid tiny starter sizes by default; when a setup is genuinely clear after costs, prefer size_pct around 0.10 to 0.15 unless the snapshot gives a strong reason to stay smaller. "
            "If candidate_filter has already selected up to three symbols, treat them as ranked possibilities rather than as proof that only perfect setups are allowed. "
            "If the snapshot includes higher_timeframe.trend_phase, read it as stage context rather than a trade signal by itself: trend or reclaim can support a fresh entry, pullback still needs confirmation, and exhaustion should make you skeptical of chase entries. "
            "If higher_timeframe.model_signal is present, treat it as a trained 1h regression forecast, not as a hard rule. When its direction agrees with the setup and prediction_strength is above 1.0, it is a supportive second opinion; when it sharply conflicts, be more cautious. "
            "If candidate_context.setup_phase is present, treat it as the current 5m setup label. Prefer confirmed phases over *_unconfirmed or *_chase, and do not let unchanged 1h bias override a weak 5m setup. "
            "If candidate_context.traditional_signal_context is present, treat it as classic chart-structure context rather than as a hard rule. Pattern labels like failed_rebound_breakdown or fresh_support_break mean a traditional short setup is forming; failed_breakdown_reclaim or fresh_resistance_reclaim mean a traditional long reclaim is forming. "
            "If candidate_context.setup_model_signal is present, treat it as the narrowest learned signal in the stack: it is trained on this symbol and this setup_phase for short-horizon post-cost edge. Positive predicted_edge_pct with label=favorable and reasonable sample_count supports acting; negative predicted_edge_pct means default wait unless everything else is exceptional. "
            "Distinguish setup_model_signal.quality: strong_favorable means the narrow model is both positive and statistically clearer; weak_favorable means the sign is positive but the edge is thin or unstable, so default wait unless the rest of the setup is unusually strong. "
            "If candidate_context.entry_viability_preview is present, treat it as a non-veto diagnostic from the current risk heuristics. A clearly positive expected_edge.edge_surplus_pct with empty shadow_open_signal_reasons supports acting; a positive required_threshold_gap_pct or multiple shadow_open_signal_reasons means wait unless the rest of the snapshot is unusually strong. "
            "If a short candidate has traditional_signal_context.conviction_score >= 0.55, traditional_signal_context.terminal_risk=false, positive entry_viability_preview.expected_edge.edge_surplus_pct, and no shadow_open_signal_reasons, do not reject it only because local RSI is already low. That combination can describe a valid failed-rebound breakdown, so a starter short is acceptable unless the bar is clearly climactic. "
            "If that same short also has candidate_context.setup_model_signal.quality=strong_favorable, prefer trusting the setup over a generic RSI-already-low objection unless the bar is obviously terminal. "
            "If the same short only has candidate_context.setup_model_signal.quality=weak_favorable, treat that as insufficient by itself and prefer waiting for one more confirming bar or a cleaner break. "
            "If candidate_context.setup_phase is short_breakdown_confirmed, treat it as a real downside momentum setup rather than a terminal flush. A small starter short is acceptable when it is the clearest candidate and price remains below the fast and slow 5m SMA context. "
            "If candidate_context.reasons include short_setup_pre_breakdown_watch or long_setup_pre_breakout_watch, treat that as an early continuation watchlist signal; slightly sub-average 5m volatility alone is not enough reason to force hold. "
            "Do not immediately re-enter the same long after an adverse loss-cut unless several closed 5m bars have clearly rebuilt support. "
            "For fresh futures longs, avoid chasing a weak reclaim or late breakout when the latest closed 5m bar is already stretched, local RSI is elevated, and volume has already expanded; prefer waiting for a cleaner pullback or sturdier rebuild. "
            "For fresh futures longs, if return_24bars is only marginally positive after costs and price is still at or below the 5m fast SMA context, do not let the unchanged 1h long bias or one rebound bar talk you into an entry; prefer hold until the reclaim is cleaner. "
            "For fresh futures rebound or continuation longs, require either RSI to have recovered back above roughly neutral with supportive SMA context, or clearly stronger multi-bar follow-through. A single strong rebound bar from sub-50 RSI with only modest participation is usually a wait, not a buy. "
            "When one ranked symbol has the clearest directional case, a small starter entry can be acceptable even if the setup is not perfect. "
            "If the chosen symbol already has an open position in the snapshot, or candidate_context.manage_only is true, treat the decision as position management first rather than as a fresh entry search. "
            "For an existing position, hold is the default while the current side still has support and there is no clear post-cost reason to flatten. "
            "Prefer close only when the latest closed bar, SMA context, or higher-timeframe bias have turned against the current position strongly enough that avoiding further adverse move is likely worth the close cost. "
            "For an existing starter long opened on a rebound or continuation idea, if 2 closed 5m bars pass without upside follow-through and unrealized PnL is still small or negative, prefer close over another passive hold even when the 1h bias is unchanged. "
            "If opening a position, ensure the leveraged notional implied by size_pct is at least as large as the exchange_min_cost_quote shown for that symbol. "
            "Treat 0.12% as a practical round-trip cost hurdle for a new futures entry. "
            "For fresh futures entries, keep stop_loss_pct positive and meaningful. take_profit_pct may be 0 when you prefer to let the position run without a fixed profit cap. "
            "Avoid very tight fresh-entry profit targets; when you do set one, 0.02 to 0.03 is usually stronger than a tiny scalp target when momentum and higher-timeframe bias are aligned. "
            "If the latest closed bar already extends far in the proposed trade direction and looks climactic or terminal, prefer hold rather than chasing it even when participation is expanding aggressively. "
            "If an existing position has already built a meaningful unrealized gain, prefer close rather than letting that gain retrace materially unless follow-through is clearly strengthening in the same direction. "
            "For a new short, prefer sell when downside evidence is aligned: higher-timeframe bias is short or clearly bearish, return_24bars is not fighting the short thesis, fast/slow SMA context supports downside, the latest closed bar is not a clear rebound, and participation is at least adequate. "
            "A flat higher-timeframe bias can still allow a fresh short, but only when the 5m breakdown is clean, not terminal, and the post-cost edge is clearer than hold. "
            "Hold when the setup is genuinely unclear, conflicting, or still weak after the candidate pre-screen. "
            "A small directional entry is acceptable only when one symbol shows the clearest post-cost bias."
        )
    return (
        f"Decide whether the trading system should buy, sell, hold, or close a position for the next {timeframe} bar. "
        "Return exactly one JSON object with fields: timestamp, symbol, action, size_pct, "
        "take_profit_pct, stop_loss_pct, ttl_minutes, confidence, reason, prompt_version. "
        "Write all ratio fields as decimal fractions only: 0.20 not 20, 0.02 not 2, 0.01 not 1. "
        "Do not use percent signs. "
        "ttl_minutes should usually be 5, 15, 30, or 60 for this 5m workflow; use 0 only for immediate hold/close style decisions. "
        "The snapshot indicators are bar-based: return_1bar is the last closed bar return, return_24bars spans 24 closed bars, "
        "and the fast/slow SMA ratios are relative to 12-bar and 48-bar averages. "
        "If opening a position, ensure the proposed size_pct implies notional at least as large as the exchange_min_cost_quote shown for that symbol. "
        "Use hold only when the setup is genuinely unclear or conflicting. A small buy is acceptable "
        "when one symbol shows a cleaner long bias than the others with positive trend, supportive SMA ratios, "
        "RSI below obvious overbought, and no sign of collapsed participation on the latest closed bar."
    )


class AIDecisionClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _render_prompt(self, prompt: str) -> str:
        return (
            prompt.replace("{{timeframe}}", self.settings.timeframe)
            .replace("{{market_type}}", self.settings.market_type)
        )

    def _load_prompt(self, path: Path, fallback: str) -> str:
        if path.exists():
            return self._render_prompt(path.read_text(encoding="utf-8").strip())
        return self._render_prompt(fallback)

    def request_decision(self, bundle: MarketSnapshotBundle) -> tuple[dict, str, str]:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package is required for AI decisions") from exc

        system_prompt = self._load_prompt(
            self.settings.system_prompt_path,
            default_system_prompt(self.settings.contract_market, self.settings.timeframe),
        )
        decision_prompt = self._load_prompt(
            self.settings.decision_prompt_path,
            default_decision_prompt(self.settings.contract_market, self.settings.timeframe),
        )
        snapshot_json = json.dumps(bundle.summary_for_prompt(), ensure_ascii=False)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"{decision_prompt}\n\nSnapshot JSON:\n{snapshot_json}",
            },
        ]

        client = OpenAI(
            base_url=self.settings.openai_base_url,
            api_key=self.settings.openai_api_key,
            timeout=self.settings.ai_timeout_seconds,
        )
        response = client.chat.completions.create(
            model=self.settings.ai_model,
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw_text = response.choices[0].message.content or ""
        request_payload = {
            "model": self.settings.ai_model,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        model_name = getattr(response, "model", self.settings.ai_model)
        return request_payload, raw_text, model_name
