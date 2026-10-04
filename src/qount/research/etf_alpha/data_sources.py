"""Public issuer parsers and an independent US equity session calendar.

Issuer histories are retrospective vintages, not historical availability proof.
No parser treats a publication date or an ex-date as a historical observation.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from decimal import Decimal
from html.parser import HTMLParser


class PublicHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.props = []
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        for key, value in attrs:
            if key == "componentprops" and value:
                try:
                    obj = json.loads(value)
                except ValueError:
                    continue
                if "distributionTableData" in obj:
                    self.props.append(obj["distributionTableData"])

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    @property
    def text(self):
        return " ".join(" ".join(self.parts).split())


def source_text(raw: bytes) -> str:
    parser = PublicHTML()
    parser.feed(raw.decode("utf-8"))
    return parser.text


def iso_date(value) -> str:
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError("unrecognized source date")


def amount(value) -> float:
    result = float(Decimal(str(value)))
    if not math.isfinite(result) or result < 0:
        raise ValueError("nonfinite or negative cash distribution")
    return result


def event(symbol, ex_date, record_date, pay_date, cash, **parts) -> dict:
    ex, record, pay = map(iso_date, (ex_date, record_date, pay_date))
    if pay < ex or record < ex:
        raise ValueError("distribution date order is invalid")
    return {"symbol": symbol, "ex_date": ex, "record_date": record,
            "pay_date": pay, "cash_per_share": amount(cash),
            "currency": "USD", "issuer_components": parts,
            "historical_asof_verified": False,
            "announcement_date": None, "available_at_historical_time": None,
            "share_basis": "issuer_reported_per_share; historical_split_basis_requires_reconciliation"}


def unique_events(rows: list[dict]) -> list[dict]:
    seen = set()
    for row in rows:
        key = row["symbol"], row["ex_date"]
        if key in seen:
            raise ValueError("duplicate issuer distribution: explicit review required")
        seen.add(key)
    return sorted(rows, key=lambda row: (row["ex_date"], row["symbol"]))


def parse_ishares(raw: bytes, symbol: str) -> list[dict]:
    parser = PublicHTML()
    parser.feed(raw.decode("utf-8"))
    if len(parser.props) != 1 or not re.search(r"\b" + re.escape(symbol) + r"\b", parser.text):
        raise ValueError("issuer identity or full distribution component missing")
    columns = {col["name"]: col["value"] for col in parser.props[0]}
    required = ("exDate", "recordDate", "payableDate", "totalDistribution")
    if not all(key in columns for key in required):
        raise ValueError("issuer distribution columns missing")
    lengths = {len(values) for values in columns.values()}
    if len(lengths) != 1 or not columns["exDate"]:
        raise ValueError("issuer distribution arrays differ or are empty")
    return unique_events([event(symbol, columns["exDate"][i], columns["recordDate"][i],
                                columns["payableDate"][i], columns["totalDistribution"][i],
                                **{key: values[i] for key, values in columns.items() if key not in required})
                          for i in range(len(columns["exDate"]))])


def parse_ssga(raw: bytes, *, start: str | None = None, end: str | None = None) -> list[dict]:
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(info.file_size for info in archive.infolist()) > 80_000_000:
            raise ValueError("oversize issuer workbook")
        strings = ["".join(value.itertext()) for value in
                   ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("s:si", ns)]
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows, header = [], None
    for row in sheet.findall("s:sheetData/s:row", ns):
        cells = {}
        for cell in row.findall("s:c", ns):
            value = cell.find("s:v", ns)
            if value is not None:
                cells[cell.get("r").rstrip("0123456789")] = (
                    strings[int(value.text)] if cell.get("t") == "s" else value.text)
        if cells.get("B") == "TICKER":
            header = cells
        symbol = cells.get("B")
        if symbol not in {"SPY", "BIL"}:
            continue
        if header is None or any(header.get(key) != label for key, label in
                                 {"D": "EX-DATE", "E": "RECORD DATE", "F": "PAYABLE DATE"}.items()):
            raise ValueError("issuer workbook schema changed")
        expected = {"SPY": "78462F103", "BIL": "78468R663"}[symbol]
        if cells.get("C") != expected:
            raise ValueError("issuer workbook CUSIP mismatch")
        # Preserve the complete original workbook, but only qualify the declared
        # research window. An out-of-window source error must not remove valid
        # in-window SPY/BIL records or be silently corrected.
        ex_date = iso_date(cells["D"])
        if (start and ex_date < start) or (end and ex_date > end):
            continue
        parts = {"dividend": cells.get("G") or "0", "short_term_gain": cells.get("H") or "0",
                 "long_term_gain": cells.get("I") or "0"}
        cash = sum(Decimal(value) for value in parts.values())
        rows.append(event(symbol, cells["D"], cells["E"], cells["F"], cash, **parts))
    if {row["symbol"] for row in rows} != {"SPY", "BIL"}:
        raise ValueError("complete SPY and BIL distribution histories required")
    return unique_events(rows)


def parse_invesco(raw: bytes, symbol: str) -> list[dict]:
    value = json.loads(raw)
    expected = {"QQQ": "46090E103", "DBC": "46138B103"}[symbol]
    if value.get("cusip") != expected or value.get("currencyCode") != "USD":
        raise ValueError("issuer CUSIP/currency mismatch; empty ticker response is not data")
    rows = value.get("distributions")
    if not isinstance(rows, list) or not rows:
        raise ValueError("issuer distribution history missing")
    return unique_events([event(symbol, row["exDate"], row["recordDate"], row["payDate"],
                                row["distributionAmountPerUnit"],
                                **{key: val for key, val in row.items() if key.endswith("Distribution")})
                          for row in rows])


def _nth_weekday(year, month, weekday, occurrence):
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (occurrence - 1))


def _last_monday(year, month):
    first_next = dt.date(year + (month == 12), month % 12 + 1, 1)
    last = first_next - dt.timedelta(days=1)
    return last - dt.timedelta(days=last.weekday())


def _observed(day, *, saturday=True):
    if day.weekday() == 6:
        return day + dt.timedelta(days=1)
    if day.weekday() == 5 and saturday:
        return day - dt.timedelta(days=1)
    return day


def _easter(year):
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    n = h + l - 7 * m + 114
    return dt.date(year, n // 31, n % 31 + 1)


SPECIAL_CLOSURES = {
    "2012-10-29": ("Hurricane Sandy", "nasdaq_sandy29"),
    "2012-10-30": ("Hurricane Sandy", "nasdaq_sandy30"),
    "2018-12-05": ("President Bush national mourning", "nyse_bush"),
    "2025-01-09": ("President Carter national mourning", "nasdaq_carter"),
}


def equity_calendar(start: str, end: str) -> list[dict]:
    """Daily session presence, derived from exchange rules, not input quote dates.

    Limited to the audited 2009--2026 range. Early closes remain trading sessions;
    this function does not purport to supply historical intraday/settlement hours.
    """
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if first > last or first.year < 2009 or last.year > 2026:
        raise ValueError("calendar outside reviewed 2009--2026 contract")
    holidays = {}
    for year in range(first.year, last.year + 1):
        ordinary = {
            _observed(dt.date(year, 1, 1), saturday=False): "New Year",
            _nth_weekday(year, 1, 0, 3): "Martin Luther King Jr",
            _nth_weekday(year, 2, 0, 3): "Washington birthday",
            _easter(year) - dt.timedelta(days=2): "Good Friday",
            _last_monday(year, 5): "Memorial Day",
            _observed(dt.date(year, 7, 4)): "Independence Day",
            _nth_weekday(year, 9, 0, 1): "Labor Day",
            _nth_weekday(year, 11, 3, 4): "Thanksgiving",
            _observed(dt.date(year, 12, 25)): "Christmas",
        }
        if year >= 2022:
            ordinary[_observed(dt.date(year, 6, 19))] = "Juneteenth"
        holidays.update(ordinary)
    result = []
    day = first
    while day <= last:
        special = SPECIAL_CLOSURES.get(day.isoformat())
        reason = "weekend" if day.weekday() >= 5 else holidays.get(day, "")
        if special:
            reason = special[0]
        result.append({"date": day.isoformat(), "is_session": not bool(reason),
                       "closure_reason": reason, "special_source_id": special[1] if special else None,
                       "method": "independent_exchange_rule_calendar", "intraday_hours_verified": False})
        day += dt.timedelta(days=1)
    return result


def compare_sessions(calendar: list[dict], input_dates: tuple[str, ...]) -> dict:
    expected = {row["date"] for row in calendar if row["is_session"]}
    actual = set(input_dates)
    missing, extra = sorted(expected - actual), sorted(actual - expected)
    return {"expected_sessions": len(expected), "input_sessions": len(input_dates),
            "missing_sessions": missing, "unexpected_sessions": extra,
            "duplicate_count": len(input_dates) - len(actual),
            "status": "pass" if not (missing or extra or len(input_dates) != len(actual)) else "fail"}


def reconcile_events(official: list[dict], legacy: dict[tuple[str, str], float]) -> tuple[dict, list[dict]]:
    issuer = {(row["symbol"], row["ex_date"]): row["cash_per_share"] for row in official}
    details = []
    for symbol, day in sorted(set(issuer) | set(legacy)):
        a, b = issuer.get((symbol, day)), legacy.get((symbol, day))
        if a is None:
            status = "legacy_only"
        elif b is None:
            status = "issuer_only_zero" if a == 0 else "issuer_only_positive"
        elif abs(a - b) <= 1e-6:
            status = "match"
        elif abs(a - b) <= 0.000501:
            status = "rounding_compatible"
        else:
            status = "amount_mismatch_requires_review"
        details.append({"symbol": symbol, "ex_date": day, "issuer_cash_per_share": a,
                        "legacy_nominal_cash_per_share": b, "status": status})
    summary = {}
    for symbol in sorted({key[0] for key in issuer} | {key[0] for key in legacy}):
        rows = [row for row in details if row["symbol"] == symbol]
        counts = {status: sum(row["status"] == status for row in rows) for status in sorted({row["status"] for row in rows})}
        summary[symbol] = {"issuer_rows": sum(row["symbol"] == symbol for row in official),
                           "issuer_positive_rows": sum(row["symbol"] == symbol and row["cash_per_share"] > 0 for row in official),
                           "legacy_rows": sum(key[0] == symbol for key in legacy), "statuses": counts}
    return summary, details
