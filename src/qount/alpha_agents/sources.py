from __future__ import annotations

from .models import SourceRef


SOURCE_BOOK: dict[str, tuple[SourceRef, ...]] = {
    "binance_market_data": (
        SourceRef(
            title="Binance Public Data",
            url="https://github.com/binance/binance-public-data",
            source_type="official_exchange_doc",
            notes="Official guide for daily/monthly data.binance.vision public dumps.",
        ),
        SourceRef(
            title="Binance Data Collection",
            url="https://data.binance.vision/",
            source_type="official_exchange_data",
            notes="Public market data dump host; daily/monthly spot/futures files.",
        ),
        SourceRef(
            title="Binance USD-M Futures Exchange Information",
            url="https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information",
            source_type="official_exchange_doc",
            notes="/fapi/v1/exchangeInfo is the source for symbols, rate limits, and filters.",
        ),
        SourceRef(
            title="Binance USD-M Futures Kline/Candlestick Data",
            url="https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data",
            source_type="official_exchange_doc",
            notes="/fapi/v1/klines gives symbol bars; klines are keyed by open time.",
        ),
        SourceRef(
            title="Binance USD-M Futures Symbol Order Book Ticker",
            url="https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Symbol-Order-Book-Ticker",
            source_type="official_exchange_doc",
            notes="/fapi/v1/ticker/bookTicker gives best bid/ask and quantity for spread/slippage checks.",
        ),
        SourceRef(
            title="Binance Spot WebSocket Streams",
            url="https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams",
            source_type="official_exchange_doc",
            notes="Spot aggTrade, trade, diff depth, and partial book depth stream definitions.",
        ),
        SourceRef(
            title="Binance Futures WebSocket Market Streams",
            url="https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams",
            source_type="official_exchange_doc",
            notes="Futures bookTicker, diff depth, aggTrade, mark price, liquidation, and kline streams.",
        ),
    ),
    "binance_derivatives_state": (
        SourceRef(
            title="Binance USD-M Futures Funding Rate History",
            url="https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History",
            source_type="official_exchange_doc",
            notes="/fapi/v1/fundingRate provides fundingRate, fundingTime, and markPrice.",
        ),
        SourceRef(
            title="Binance USD-M Futures Open Interest Statistics",
            url="https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics",
            source_type="official_exchange_doc",
            notes="/futures/data/openInterestHist provides open interest history by period.",
        ),
        SourceRef(
            title="Binance USD-M Futures Open Interest",
            url="https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest",
            source_type="official_exchange_doc",
            notes="/fapi/v1/openInterest provides current open interest for a symbol.",
        ),
        SourceRef(
            title="Binance USD-M Futures Taker Buy/Sell Volume",
            url="https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Taker-BuySell-Volume",
            source_type="official_exchange_doc",
            notes="/futures/data/takerlongshortRatio provides taker buy volume, sell volume, and ratio by period.",
        ),
        SourceRef(
            title="Binance USD-M Futures Top Trader Long/Short Position Ratio",
            url="https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Top-Trader-Long-Short-Ratio",
            source_type="official_exchange_doc",
            notes="/futures/data/topLongShortPositionRatio provides top-trader position ratio; endpoint requires API key header.",
        ),
        SourceRef(
            title="Binance USD-M Futures Notional and Leverage Brackets",
            url="https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Notional-and-Leverage-Brackets",
            source_type="official_exchange_doc",
            notes="/fapi/v1/leverageBracket provides notional and leverage bracket data; signed endpoint.",
        ),
    ),
    "structural_market_data": (
        SourceRef(
            title="Deribit Volatility Index Data",
            url="https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data",
            source_type="official_exchange_doc",
            notes="Public BTC/ETH DVOL hourly OHLC history with continuation paging.",
        ),
        SourceRef(
            title="Hyperliquid Funding History",
            url="https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint#retrieve-funding-history",
            source_type="official_exchange_doc",
            notes="Public point-in-time funding and premium history by coin.",
        ),
        SourceRef(
            title="Deribit Instrument Directory",
            url="https://docs.deribit.com/api-reference/market-data/public-get_instruments",
            source_type="official_exchange_doc",
            notes="Current or recently expired instrument metadata; historical chain completeness must be audited.",
        ),
        SourceRef(
            title="Deribit Historical Trades By Currency And Time",
            url="https://docs.deribit.com/api-reference/market-data/public-get_last_trades_by_currency_and_time",
            source_type="official_exchange_doc",
            notes="Trade schema can expose IV and index fields where retained; old-history availability must be probed.",
        ),
        SourceRef(
            title="Deribit TradingView Chart Data",
            url="https://docs.deribit.com/api-reference/market-data/public-get_tradingview_chart_data",
            source_type="official_exchange_doc",
            notes="Historical OHLC/volume/cost by known instrument name; chart schema does not directly provide IV.",
        ),
        SourceRef(
            title="Tardis Binance Futures Historical Data",
            url="https://docs.tardis.dev/historical-data-details/binance-futures",
            source_type="data_provider_doc",
            notes="External normalized and raw Binance futures history including incremental L2 and liquidations; access and storage gates remain project-specific.",
        ),
    ),
    "validation": (
        SourceRef(
            title="Deflated Sharpe Ratio",
            url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551",
            source_type="primary_research",
            notes="Multiple-testing adjustment for selected Sharpe ratios.",
        ),
        SourceRef(
            title="Probability of Backtest Overfitting",
            url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253",
            source_type="primary_research",
            notes="CSCV/PBO framework for strategy selection overfit risk.",
        ),
        SourceRef(
            title="Advances in Financial Machine Learning",
            url="https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086",
            source_type="book",
            notes="Reference for purged CV, embargo, and triple-barrier labeling.",
        ),
        SourceRef(
            title="MLFinPy Labeling Documentation",
            url="https://mlfinpy.readthedocs.io/en/latest/Labelling.html",
            source_type="tutorial",
            notes="Secondary implementation guide for triple-barrier and meta-labeling; cannot override primary references.",
        ),
        SourceRef(
            title="QuantBeckman CPCV Tutorial",
            url="https://www.quantbeckman.com/p/with-code-combinatorial-purged-cross",
            source_type="tutorial",
            notes="Secondary tutorial with code for CPCV concepts; use for implementation ideas, not promotion evidence.",
        ),
    ),
    "agent_security": (
        SourceRef(
            title="OWASP Top 10 for Agentic Applications 2026",
            url="https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/",
            source_type="security_reference",
            notes="Agentic AI security risks and mitigations.",
        ),
        SourceRef(
            title="OWASP Agentic AI Threats and Mitigations",
            url="https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/",
            source_type="security_reference",
            notes="Threat model for agent tools, permissions, goal drift, and external-input attacks.",
        ),
        SourceRef(
            title="OWASP LLM Top 10",
            url="https://genai.owasp.org/llm-top-10/",
            source_type="security_reference",
            notes="Prompt injection, sensitive data disclosure, supply-chain, and excessive-agency risks.",
        ),
    ),
    "project_evidence": (
        SourceRef(
            title="qount current facts",
            url="docs/current.md",
            source_type="local_project_doc",
            notes="Current production truth, prior falsifications, and live boundaries.",
        ),
        SourceRef(
            title="qount project rules",
            url="docs/project-rules.md",
            source_type="local_project_doc",
            notes="Research isolation, anti-overfit rules, and code architecture constraints.",
        ),
        SourceRef(
            title="qount update log",
            url="docs/update-log.md",
            source_type="local_project_doc",
            notes="MiniTrend beta attribution and historical research evidence.",
        ),
    ),
    "llm_gateway": (
        SourceRef(
            title="relay-station ChatGPT gateway",
            url="~/Code/relay-station/README.md",
            source_type="local_infra_doc",
            notes=(
                "OpenAI-compatible endpoint https://llm.alyaloale.com/v1; current "
                "research default is gpt-5.6-terra with single-request fail-closed limits."
            ),
        ),
    ),
}


def sources_for_tags(tags: tuple[str, ...]) -> tuple[SourceRef, ...]:
    out: list[SourceRef] = []
    seen: set[str] = set()
    for tag in tags:
        for source in SOURCE_BOOK.get(tag, ()):
            if source.url not in seen:
                out.append(source)
                seen.add(source.url)
    return tuple(out)
