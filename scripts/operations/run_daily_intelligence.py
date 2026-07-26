#!/usr/bin/env python3
"""Run one audited daily intelligence batch and optionally deliver a notification."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.llm import AlphaLLMConfig  # noqa: E402
from qount.alpha_agents.llm import VOLC_CODING_PLAN_BASE_URL  # noqa: E402
from qount.alpha_agents.llm import VOLC_CODING_PLAN_DEFAULT_MAX_TOKENS  # noqa: E402
from qount.alpha_agents.llm import VOLC_CODING_PLAN_DEFAULT_MODEL  # noqa: E402
from qount.alpha_agents.llm import VOLC_CODING_PLAN_PROFILE  # noqa: E402
from qount.intelligence import BraveSearchProvider  # noqa: E402
from qount.intelligence import OfficialFeedSearchProvider  # noqa: E402
from qount.intelligence import alert_from_daily_intelligence  # noqa: E402
from qount.intelligence import fetch_binance_market_pulse  # noqa: E402
from qount.intelligence import run_daily_intelligence  # noqa: E402
from qount.notifications import NotificationStore  # noqa: E402
from qount.notifications import OPENCLAW_WEIXIN_PROVIDER_NAME  # noqa: E402
from qount.notifications import OpenClawWeixinProvider  # noqa: E402
from qount.notifications import ProviderTransport  # noqa: E402
from qount.notifications import RateLimitPolicy  # noqa: E402
from qount.notifications import synchronize_producer_incidents  # noqa: E402
from qount.notifications import WECOM_PROVIDER_NAME  # noqa: E402
from qount.notifications import WeComGroupRobotProvider  # noqa: E402
from qount.notifications import load_provider_credential  # noqa: E402
from qount.reporting import read_vps_authority_bundle  # noqa: E402


DAILY_INTELLIGENCE_DEFAULT_LLM_MODEL = VOLC_CODING_PLAN_DEFAULT_MODEL
DAILY_INTELLIGENCE_DEFAULT_LLM_BASE_URL = VOLC_CODING_PLAN_BASE_URL
DAILY_INTELLIGENCE_DEFAULT_LLM_PROVIDER_PROFILE = VOLC_CODING_PLAN_PROFILE
DAILY_INTELLIGENCE_DEFAULT_LLM_MAX_TOKENS = VOLC_CODING_PLAN_DEFAULT_MAX_TOKENS


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-root", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--notification-store", type=Path, required=True)
    parser.add_argument(
        "--search-provider",
        choices=("official-feeds", "brave"),
        default="official-feeds",
    )
    parser.add_argument("--search-credential-path", type=Path)
    parser.add_argument("--with-llm", action="store_true")
    parser.add_argument("--llm-credential-path", type=Path)
    parser.add_argument(
        "--llm-base-url",
        default=DAILY_INTELLIGENCE_DEFAULT_LLM_BASE_URL,
    )
    parser.add_argument(
        "--llm-provider-profile",
        default=DAILY_INTELLIGENCE_DEFAULT_LLM_PROVIDER_PROFILE,
    )
    parser.add_argument(
        "--llm-model",
        default=DAILY_INTELLIGENCE_DEFAULT_LLM_MODEL,
        help="Provider model dedicated to the daily intelligence workflow.",
    )
    parser.add_argument(
        "--llm-max-tokens",
        type=int,
        default=DAILY_INTELLIGENCE_DEFAULT_LLM_MAX_TOKENS,
    )
    parser.add_argument("--enqueue-wecom", action="store_true")
    parser.add_argument("--send-wecom", action="store_true")
    parser.add_argument("--wecom-credential-path", type=Path)
    parser.add_argument("--enqueue-personal-weixin", action="store_true")
    parser.add_argument("--send-personal-weixin", action="store_true")
    parser.add_argument("--personal-weixin-credential-path", type=Path)
    parser.add_argument("--personal-weixin-context-token-directory", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    bundle = read_vps_authority_bundle(args.authority_root.resolve())
    if args.search_provider == "brave":
        if args.search_credential_path is None:
            raise ValueError("search_credential_path_required")
        search_credential = load_provider_credential(
            args.search_credential_path.resolve(), provider="brave_web_search"
        )
        if search_credential is None:
            raise ValueError("search_credential_required")
        search_provider = BraveSearchProvider(credential=search_credential)
    else:
        if args.search_credential_path is not None:
            raise ValueError("search_credential_not_used")
        search_provider = OfficialFeedSearchProvider()
    llm_config = AlphaLLMConfig.from_env(
        enabled_override=args.with_llm,
        load_local_file=False,
    )
    if args.with_llm:
        if args.llm_credential_path is None:
            raise ValueError("llm_credential_path_required")
        llm_credential = load_provider_credential(
            args.llm_credential_path.resolve(),
            provider=args.llm_provider_profile,
        )
        if llm_credential is None:
            raise ValueError("llm_credential_required")
        llm_config = replace(
            llm_config,
            base_url=args.llm_base_url,
            api_key=llm_credential,
            model=args.llm_model,
            max_tokens=args.llm_max_tokens,
            provider_profile=args.llm_provider_profile,
        )
    market = fetch_binance_market_pulse(observed_at=now)
    run = run_daily_intelligence(
        created_at=now,
        market_pulse=market.pulse,
        market_bodies=market.raw_bodies,
        runtime_ledger_snapshot=bundle.ledger_snapshot,
        search_provider=search_provider,
        archive_root=str(args.archive_root.resolve()),
        llm_config=llm_config,
    )

    wecom_requested = args.enqueue_wecom or args.send_wecom
    personal_weixin_requested = (
        args.enqueue_personal_weixin or args.send_personal_weixin
    )
    if wecom_requested and personal_weixin_requested:
        raise ValueError("multiple_notification_providers_not_supported")
    deliveries = ()
    notification_channel = None
    if wecom_requested:
        notification_channel = "wecom"
    elif personal_weixin_requested:
        notification_channel = OPENCLAW_WEIXIN_PROVIDER_NAME
    if notification_channel is not None:
        store = NotificationStore(args.notification_store.resolve())
        intelligence_alert = alert_from_daily_intelligence(run.report)
        if intelligence_alert.severity == "INFO":
            store.enqueue(
                intelligence_alert,
                recorded_at=now,
                channels=(notification_channel,),
                max_attempts=3,
            )
            store.resolve_alert(intelligence_alert.alert_id, resolved_at=now)
            store.resolve_superseded_alerts(
                active_alert_ids=(),
                source_type="intelligence",
                categories=("daily_intelligence",),
                resolved_at=now,
            )
        else:
            synchronize_producer_incidents(
                store,
                (intelligence_alert,),
                source_type="intelligence",
                categories=("daily_intelligence",),
                observed_at=now,
                channels=(notification_channel,),
                max_attempts=3,
            )
        if args.send_wecom:
            if args.wecom_credential_path is None:
                raise ValueError("wecom_credential_path_required")
            transport = ProviderTransport(
                WeComGroupRobotProvider(),
                provider_name=WECOM_PROVIDER_NAME,
                credential_path=args.wecom_credential_path.resolve(),
                require_credential=True,
                timeout_seconds=8,
                rate_limit=RateLimitPolicy(max_calls=2, window_seconds=1.0),
            )
            deliveries = store.deliver_due(
                attempted_at=now,
                transport=transport,
                channel="wecom",
                limit=10,
                retry_base_seconds=300,
            )
        elif args.send_personal_weixin:
            if args.personal_weixin_credential_path is None:
                raise ValueError("personal_weixin_credential_path_required")
            context_token_directory = (
                None
                if args.personal_weixin_context_token_directory is None
                else args.personal_weixin_context_token_directory
            )
            transport = ProviderTransport(
                OpenClawWeixinProvider(
                    context_token_directory=context_token_directory
                ),
                provider_name=OPENCLAW_WEIXIN_PROVIDER_NAME,
                credential_path=args.personal_weixin_credential_path.resolve(),
                require_credential=True,
                timeout_seconds=20,
                rate_limit=RateLimitPolicy(max_calls=2, window_seconds=1.0),
            )
            deliveries = store.deliver_due(
                attempted_at=now,
                transport=transport,
                channel=OPENCLAW_WEIXIN_PROVIDER_NAME,
                limit=10,
                retry_base_seconds=300,
            )

    print(
        json.dumps(
            {
                "status": "completed",
                "report_id": run.report.report_id,
                "report_hash": run.report.report_hash,
                "report_status": run.report.status,
                "archive": run.archive.as_dict(),
                "notification_enqueued": notification_channel is not None,
                "notification_channel": notification_channel,
                "search_provider": args.search_provider,
                "deliveries": list(deliveries),
                "orders_allowed": False,
                "live_changes_allowed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
