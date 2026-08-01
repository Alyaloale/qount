"""Qount Dual-Engine order-free paper program."""

from qount.dual_engine.contracts import C60_STRATEGY_ID
from qount.dual_engine.contracts import C60_STRATEGY_VERSION
from qount.dual_engine.contracts import C60_SYMBOLS
from qount.dual_engine.contracts import DUAL_ENGINE_PROGRAM_ID
from qount.dual_engine.contracts import DUAL_ENGINE_PROGRAM_VERSION
from qount.dual_engine.contracts import DualEngineContractError
from qount.dual_engine.contracts import DualEnginePaperContract
from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY
from qount.dual_engine.contracts import G20_STRATEGY_ID
from qount.dual_engine.contracts import G20_STRATEGY_VERSION
from qount.dual_engine.contracts import PAPER_PORTFOLIO_IDS
from qount.dual_engine.contracts import PaperCycleInput
from qount.dual_engine.contracts import PaperProgramSnapshot
from qount.dual_engine.strategy import C60Decision
from qount.dual_engine.strategy import G20Decision
from qount.dual_engine.strategy import build_c60_decision
from qount.dual_engine.strategy import build_g20_decision
from qount.dual_engine.strategy import build_strategy_intents
from qount.dual_engine.strategy import d15_c60_budget
from qount.dual_engine.paper import DualEnginePaperRuntimeError
from qount.dual_engine.paper import read_paper_snapshot
from qount.dual_engine.paper import run_paper_cycle
from qount.dual_engine.market_data import DualEngineMarketConfig
from qount.dual_engine.market_data import DualEngineMarketDataError
from qount.dual_engine.market_data import NoScheduledPaperEvent
from qount.dual_engine.market_data import collect_market_cycle
from qount.dual_engine.backfill import YTD_REPLAY_START
from qount.dual_engine.backfill import YtdReplay
from qount.dual_engine.backfill import collect_ytd_replay

__all__ = [
    "C60Decision",
    "C60_STRATEGY_ID",
    "C60_STRATEGY_VERSION",
    "C60_SYMBOLS",
    "DUAL_ENGINE_PROGRAM_ID",
    "DUAL_ENGINE_PROGRAM_VERSION",
    "DualEngineContractError",
    "DualEnginePaperContract",
    "DualEnginePaperRuntimeError",
    "DualEngineMarketConfig",
    "DualEngineMarketDataError",
    "G20Decision",
    "G20_EXECUTION_TO_PROXY",
    "G20_STRATEGY_ID",
    "G20_STRATEGY_VERSION",
    "PAPER_PORTFOLIO_IDS",
    "PaperCycleInput",
    "PaperProgramSnapshot",
    "YTD_REPLAY_START",
    "YtdReplay",
    "NoScheduledPaperEvent",
    "build_c60_decision",
    "build_g20_decision",
    "build_strategy_intents",
    "collect_market_cycle",
    "collect_ytd_replay",
    "d15_c60_budget",
    "read_paper_snapshot",
    "run_paper_cycle",
]
