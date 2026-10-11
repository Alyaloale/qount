"""Point-in-Time Universe and Shenwan Level 1 Industry Classifier.

Constructs strict date-valid eligible stocks and dated SW1 industry memberships
without future lookahead bias, surviving company name changes, delistings,
and the transition from SW2014 to SW2021 on 2021-12-13.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
import copy
import datetime as dt
from typing import Dict, Iterable, List, Optional, Set, Tuple

SW2021_EFFECTIVE_DATE = "20211213"
ST_PREFIXES = ("ST", "*ST", "SST", "S*ST")


class PointInTimeUniverse:
    """Historical universe eligibility and industry assignment as-of trade dates."""

    def __init__(
        self,
        *,
        masters: Iterable[dict],
        calendar_days: Iterable[str],
        members: Iterable[dict],
        namechanges: Iterable[dict] = (),
        st_records: Iterable[dict] = (),
    ):
        self.masters: Dict[str, dict] = {
            r["ts_code"]: copy.deepcopy(r)
            for r in masters
            if r.get("ts_code")
        }
        sessions = sorted({str(d) for d in calendar_days if d})
        self.calendar: Tuple[str, ...] = tuple(sessions)
        self._session_index: Dict[str, int] = {d: i for i, d in enumerate(self.calendar)}

        # Industry memberships by symbol: symbol -> list of dicts
        self.members: Dict[str, List[dict]] = defaultdict(list)
        for m in members:
            sym = m.get("ts_code")
            if sym:
                self.members[sym].append(copy.deepcopy(m))

        # Historical names by symbol: symbol -> list of (start_date, end_date, name)
        self.names: Dict[str, List[Tuple[str, Optional[str], str]]] = defaultdict(list)
        for nc in namechanges:
            sym = nc.get("ts_code")
            name = nc.get("name")
            start = nc.get("start_date")
            end = nc.get("end_date")
            if sym and name and start:
                self.names[sym].append((start, end, name))
        for sym in self.names:
            self.names[sym].sort(key=lambda x: x[0])

        # Daily ST records: set of (symbol, trade_date)
        self.st_set: Set[Tuple[str, str]] = set()
        for r in st_records:
            sym, day = r.get("ts_code"), r.get("trade_date")
            if sym and day:
                self.st_set.add((sym, day))

    @classmethod
    def from_sources(cls, sources) -> "PointInTimeUniverse":
        """Build PointInTimeUniverse directly from PublicHistorySources reader."""
        masters: List[dict] = []
        for page in sources.pages("stock_basic"):
            fields = page["fields"]
            for row in page["items"]:
                masters.append(dict(zip(fields, row, strict=True)))

        calendar_days: Set[str] = set()
        for page in sources.pages("trade_cal", exchange="SSE"):
            fields = page["fields"]
            i_date = fields.index("cal_date")
            i_open = fields.index("is_open")
            for row in page["items"]:
                if str(row[i_open]) == "1":
                    calendar_days.add(row[i_date])

        members: List[dict] = []
        for page in sources.pages("index_member_all"):
            fields = page["fields"]
            for row in page["items"]:
                members.append(dict(zip(fields, row, strict=True)))

        namechanges: List[dict] = []
        try:
            for page in sources.pages("namechange"):
                fields = page["fields"]
                for row in page["items"]:
                    namechanges.append(dict(zip(fields, row, strict=True)))
        except (KeyError, ValueError):
            pass

        st_records: List[dict] = []
        try:
            for page in sources.pages("stock_st"):
                fields = page["fields"]
                for row in page["items"]:
                    st_records.append(dict(zip(fields, row, strict=True)))
        except (KeyError, ValueError):
            pass

        return cls(
            masters=masters,
            calendar_days=calendar_days,
            members=members,
            namechanges=namechanges,
            st_records=st_records,
        )

    def is_trading_day(self, day: str) -> bool:
        return day in self._session_index

    def trading_days(self, start: str, end: str) -> List[str]:
        i_start = bisect_left(self.calendar, start)
        i_end = bisect_right(self.calendar, end)
        return list(self.calendar[i_start:i_end])

    def prior_trading_days(self, day: str, count: int) -> List[str]:
        if day not in self._session_index:
            i_end = bisect_right(self.calendar, day)
        else:
            i_end = self._session_index[day] + 1
        i_start = max(0, i_end - count)
        return list(self.calendar[i_start:i_end])

    def is_month_end(self, day: str) -> bool:
        if day not in self._session_index:
            return False
        idx = self._session_index[day]
        if idx == len(self.calendar) - 1:
            return True
        next_day = self.calendar[idx + 1]
        return next_day[:6] != day[:6]

    def month_ends(self, start: str, end: str) -> List[str]:
        days = self.trading_days(start, end)
        return [d for d in days if self.is_month_end(d)]

    def is_listed_and_mature(self, symbol: str, day: str, min_sessions: int = 252) -> bool:
        master = self.masters.get(symbol)
        if not master:
            return False
        list_date = master.get("list_date")
        if not list_date or list_date > day:
            return False
        delist_date = master.get("delist_date")
        if delist_date and delist_date <= day:
            return False
        if not self.calendar:
            return False

        cal_start = self.calendar[0]
        i_day = bisect_right(self.calendar, day)
        if list_date < cal_start:
            d_cal = dt.date(int(cal_start[:4]), int(cal_start[4:6]), int(cal_start[6:]))
            d_list = dt.date(int(list_date[:4]), int(list_date[4:6]), int(list_date[6:]))
            pre_sessions = int((d_cal - d_list).days * 242 / 365.25)
            sessions_since_listing = pre_sessions + i_day
        else:
            i_list = bisect_left(self.calendar, list_date)
            sessions_since_listing = i_day - i_list
        return sessions_since_listing >= min_sessions

    def is_st(self, symbol: str, day: str) -> bool:
        if (symbol, day) in self.st_set:
            return True
        entries = self.names.get(symbol, [])
        for start, end, name in entries:
            if start <= day and (end is None or end >= day):
                upper_name = name.upper()
                if any(upper_name.startswith(pfx) for pfx in ST_PREFIXES):
                    return True
        return False

    def industry_l1(self, symbol: str, day: str) -> Optional[Tuple[str, str]]:
        records = self.members.get(symbol, [])
        if not records:
            return None

        # Choose primary and secondary search order based on SW2021 boundary
        if day < SW2021_EFFECTIVE_DATE:
            preferred_flags = ("N", "Y")
        else:
            preferred_flags = ("Y", "N")

        for flag in preferred_flags:
            for r in records:
                if r.get("is_new") == flag:
                    in_d = r.get("in_date") or "19900101"
                    out_d = r.get("out_date")
                    if in_d <= day and (not out_d or out_d >= day):
                        code, name = r.get("l1_code"), r.get("l1_name")
                        if code and name:
                            return (code, name)
        return None

    def eligible_universe(
        self,
        day: str,
        *,
        min_sessions: int = 252,
        exclude_st: bool = True,
        require_sw1: bool = True,
        mainboard_only: bool = False,
    ) -> Set[str]:
        eligible = set()
        for sym, master in self.masters.items():
            if mainboard_only:
                market = master.get("market") or ""
                if not (market.startswith("主板") or sym.startswith(("60", "00"))):
                    continue
            if not self.is_listed_and_mature(sym, day, min_sessions=min_sessions):
                continue
            if exclude_st and self.is_st(sym, day):
                continue
            if require_sw1 and self.industry_l1(sym, day) is None:
                continue
            eligible.add(sym)
        return eligible

    def industry_map(self, symbols: Iterable[str], day: str) -> Dict[str, str]:
        result = {}
        for sym in symbols:
            info = self.industry_l1(sym, day)
            if info:
                result[sym] = info[1]
        return result
