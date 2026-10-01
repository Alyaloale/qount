"""Account universes, peer groups and market-rule parameters (design §2.3, §5, §9).

Cash (BIL / money-market fund) is deliberately *not* part of ``symbols``: it never enters
cross-sectional ranking and only absorbs ``1 - g_t`` plus weight removed by constraints.
Parameters marked "P0" in the design doc are defaults pending the P0 data audit and
owner confirmation (§12).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Asset classes drive the Value definition (§2.2) and T+0/T+1 rules (§5.5).
EQUITY = "equity"
BOND = "bond"
GOLD = "gold"
COMMODITY = "commodity"
CROSS_BORDER = "cross_border"  # QDII equity ETF: equity valuation, T+0 in A-shares

VALUE_KINDS = {EQUITY: "valuation", CROSS_BORDER: "valuation", BOND: "yield", GOLD: "neutral", COMMODITY: "neutral"}


@dataclass(frozen=True)
class Account:
    name: str
    currency: str
    symbols: tuple[str, ...]
    cash_symbol: str
    asset_class: dict[str, str]
    groups: tuple[tuple[str, ...], ...]
    turnover_budget: float  # U, one-way turnover per rolling 252 trading days (§12.1)
    single_cap: float = 0.35
    group_cap: float = 0.50
    price_limit: float | None = None  # ±limit on *unadjusted* previous close
    lot_size: int = 1
    tick: float = 0.01
    t_plus_one: frozenset[str] = field(default_factory=frozenset)
    fractional_shares: bool = False  # §12.5, US only

    def __post_init__(self) -> None:
        if self.cash_symbol in self.symbols:
            raise ValueError("cash must not participate in ranking")
        missing = set(self.symbols).difference(self.asset_class)
        if missing:
            raise ValueError(f"asset_class missing for {sorted(missing)}")
        seen: set[str] = set()
        for group in self.groups:
            unknown = set(group).difference(self.symbols)
            if unknown or seen.intersection(group):
                raise ValueError(f"invalid peer group {group}")
            seen.update(group)

    @property
    def n_assets(self) -> int:
        return len(self.symbols)

    def index(self, symbol: str) -> int:
        return self.symbols.index(symbol)

    def group_indices(self) -> tuple[tuple[int, ...], ...]:
        return tuple(tuple(self.index(s) for s in group) for group in self.groups)

    def value_kinds(self) -> tuple[str, ...]:
        return tuple(VALUE_KINDS[self.asset_class[s]] for s in self.symbols)

    def t_plus_one_mask(self) -> tuple[bool, ...]:
        return tuple(s in self.t_plus_one for s in self.symbols)


US_ACCOUNT = Account(
    name="us",
    currency="USD",
    symbols=("SPY", "QQQ", "IWM", "EFA", "EEM", "IEF", "TLT", "GLD", "DBC"),
    cash_symbol="BIL",
    asset_class={
        "SPY": EQUITY, "QQQ": EQUITY, "IWM": EQUITY, "EFA": EQUITY, "EEM": EQUITY,
        "IEF": BOND, "TLT": BOND, "GLD": GOLD, "DBC": COMMODITY,
    },
    groups=(("SPY", "QQQ", "IWM"), ("IEF", "TLT")),
    turnover_budget=4.0,
)

# T+1 list is the §5.5 default (domestic equity ETFs); P0 verifies each symbol.
CN_ACCOUNT = Account(
    name="cn",
    currency="CNY",
    symbols=("510300", "510500", "159915", "510050", "518880", "511010", "513100", "513500"),
    cash_symbol="MMF",
    asset_class={
        "510300": EQUITY, "510500": EQUITY, "159915": EQUITY, "510050": EQUITY,
        "518880": GOLD, "511010": BOND, "513100": CROSS_BORDER, "513500": CROSS_BORDER,
    },
    groups=(("510300", "510050"), ("513100", "513500")),
    turnover_budget=3.0,
    price_limit=0.10,
    lot_size=100,
    tick=0.001,
    t_plus_one=frozenset({"510300", "510500", "159915", "510050"}),
)

ACCOUNTS = {US_ACCOUNT.name: US_ACCOUNT, CN_ACCOUNT.name: CN_ACCOUNT}

# 60/40 reference used by gate G1 (§9).
SIXTY_FORTY = {"us": {"SPY": 0.6, "IEF": 0.4}, "cn": {"510300": 0.6, "511010": 0.4}}
