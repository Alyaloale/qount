"""Cash entitlement, payment timing, continuation and read-model regressions."""
import copy
import datetime as dt
import json
import math
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from qount.contracts import canonical_hash
from qount.dual_engine.g20_cash import NY, SYMBOLS, new_account, normalize_cache, refresh, step, validate
from qount.dual_engine.contracts import G20_PROXY_SYMBOLS


def bars(price=10):
    return {s:dict(open=price,high=price,low=price,close=price) for s in SYMBOLS}


def advance(data, day, *, actions=(), decision=None, price=10, observed=None, reconstructed=False):
    return step(data,day=day,bar=bars(price),actions=actions,decision=decision,
        opening=dt.datetime.fromisoformat(day+"T09:30:00").replace(tzinfo=NY),
        observed_at=observed or day+"T22:00:00+00:00",reconstructed=reconstructed)


def dividend(pay="2026-02-05"):
    return dict(kind="dividend",symbol="BIL",amount=1.,pay_date=pay,amount_source="issuer",source="issuer")


def held():
    data=new_account("2026-01-30T22:00:00+00:00")
    data["initial_equity"]=1000
    data["layer"]["sleeves"]["g20"].update(cash=0.,positions={"BIL":100.})
    return data


def seed_cache(root):
    directory=root/"market-cache/yahoo-public";directory.mkdir(parents=True)
    dates=[]
    day=dt.date(2025,8,1)
    from qount.research_data.bars import session
    while day<=dt.date(2026,2,6):
        if day.weekday()<5 and (day.year<2026 or session(int(dt.datetime.combine(day,dt.time(12),NY).timestamp()))):
            dates.append(day.isoformat())
        day+=dt.timedelta(days=1)
    for symbol in {*SYMBOLS,*G20_PROXY_SYMBOLS}:
        rows=[]
        for i,d in enumerate(dates):
            price=10*(1.001 if symbol=="XLV" else 1.0001)**i
            rows.append(dict(date=d,open=price,high=price,low=price,close=price,adjClose=price))
        (directory/(symbol+"-1d.json")).write_text(json.dumps(dict(rows=rows,events={})))
    policy=dict(verified_actions=[],sources={"BIL":"issuer","proshares":"issuer","direxion":"issuer"},pay_dates={})
    p=root/"policy.json";p.write_text(json.dumps(policy))
    return p


class G20CashTests(unittest.TestCase):
    def test_buying_on_ex_date_does_not_receive_dividend(self):
        data=new_account("2026-01-30T22:00:00+00:00")
        data["pending"]=dict(target={"BIL":1.},decision_date="2026-01-30",available_at=data["created_at"])
        data=advance(data,"2026-02-02",actions=[dividend()])
        self.assertTrue(data["trades"])
        self.assertEqual(data["income"],[])

    def test_sale_on_ex_date_keeps_right_and_payment_does_not_double_profit(self):
        data=held();data["pending"]=dict(target={},decision_date="2026-01-30",available_at=data["created_at"])
        data=advance(data,"2026-02-02",actions=[dividend()],price=9)
        self.assertEqual(data["receivables"][0]["value"],100)
        self.assertAlmostEqual(data["observations"][-1]["equity"],998.2)
        data=advance(data,"2026-02-05",price=9)
        self.assertEqual(data["receivables"],[])
        self.assertAlmostEqual(data["layer"]["sleeves"]["g20"]["cash"],998.2)
        self.assertEqual(data["distributions_received"],100)
        self.assertAlmostEqual(data["observations"][-1]["equity"],998.2)
        again=advance(data,"2026-02-06",price=9)
        self.assertEqual(again["distributions_received"],100)

    def test_payment_is_not_spendable_at_same_day_open(self):
        data=held();data["pending"]=dict(target={},decision_date="2026-01-30",available_at=data["created_at"])
        data=advance(data,"2026-02-02",actions=[dividend()],price=9)
        data["pending"]=dict(target={"BIL":1.},decision_date="2026-02-04",available_at="2026-02-04T22:00:00+00:00")
        data=advance(data,"2026-02-05",price=9)
        self.assertLessEqual(data["layer"]["sleeves"]["g20"]["positions"]["BIL"],99)
        self.assertGreaterEqual(data["layer"]["sleeves"]["g20"]["cash"],100)

    def test_unknown_payment_remains_unspendable_receivable(self):
        data=advance(held(),"2026-02-02",actions=[dividend(None)],price=9)
        data=advance(data,"2026-02-06",price=9)
        self.assertEqual(data["distributions_received"],0)
        self.assertEqual(data["layer"]["sleeves"]["g20"]["cash"],0)
        self.assertEqual(data["observations"][-1]["receivable"],100)

    def test_late_reconstructed_observation_cannot_backdate_a_fill(self):
        data=new_account("2026-02-02T22:00:00+00:00")
        data["pending"]=dict(target={"BIL":1.},decision_date="2026-01-30",available_at=data["created_at"])
        data=advance(data,"2026-02-02",reconstructed=True)
        self.assertEqual(data["trades"],[])
        data=advance(data,"2026-02-03")
        self.assertTrue(data["trades"])
        self.assertEqual(data["trades"][0]["date"],"2026-02-03")

    def test_split_normalization_and_physical_shares_preserve_value(self):
        stamp=int(dt.datetime(2026,2,3,9,30,tzinfo=NY).timestamp())
        cache={"BIL":dict(rows=[dict(date=d,open=1,high=1,low=1,close=1,adjClose=1)
                 for d in ("2026-02-02","2026-02-03")],events={"splits":{"x":dict(date=stamp,numerator=10,denominator=1)}})}
        panels,actions,_=normalize_cache(cache,dict(verified_actions=[],pay_dates={},sources={"BIL":"issuer"}))
        self.assertEqual(panels["BIL"]["2026-02-02"]["close"],10)
        data=advance(held(),"2026-02-03",actions=actions["2026-02-03"],price=1)
        self.assertEqual(data["layer"]["sleeves"]["g20"]["positions"]["BIL"],1000)
        self.assertEqual(data["observations"][-1]["equity"],1000)

    def test_refresh_is_idempotent_and_continuation_preserves_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);policy=seed_cache(root)
            first=refresh(root,policy_path=policy,observed_at="2026-01-30T23:00:00+00:00",bootstrap=True)
            second=refresh(root,policy_path=policy,observed_at="2026-02-06T23:00:00+00:00")
            self.assertEqual(second["observations"][:len(first["observations"])],first["observations"])
            path=root/"g20-cash/forward.json";before=path.read_bytes()
            third=refresh(root,policy_path=policy,observed_at="2026-02-07T23:00:00+00:00")
            self.assertEqual(before,path.read_bytes());self.assertEqual(second,third)
            for trade in second["trades"]:
                self.assertLess(trade["decision_date"],trade["date"])

    def test_adapter_and_database_keep_income_out_of_buy_sell_count(self):
        from qount.api.adapters.g20_cash import adapt_g20_cash,g20_cash_trades
        from qount.api.db import init_db,save_paper_line,get_paper_trades
        from qount.api.paper_filter import is_forward_paper_line
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/"g20-cash").mkdir()
            data=advance(held(),"2026-02-02",actions=[dividend(None)],price=9)
            (root/"g20-cash/forward.json").write_text(json.dumps(data))
            config=dict(root=str(root/"g20-cash"),reference_date="2026-02-03")
            line=adapt_g20_cash("dual_g20","G20",config)
            self.assertIsNone(line.error);self.assertTrue(is_forward_paper_line(line))
            self.assertEqual(line.metrics.trade_count,0)
            db=str(root/"api.db");init_db(db);save_paper_line(line,db_path=db,trade_events=g20_cash_trades(config))
            events=get_paper_trades("dual_g20",db_path=db,forward_only=False)
            self.assertEqual([e.side for e in events],["DIVIDEND_ACCRUAL"])
            next_year=advance(data,"2027-01-04",price=10)
            (root/"g20-cash/forward.json").write_text(json.dumps(next_year))
            line=adapt_g20_cash("dual_g20","G20",config)
            self.assertAlmostEqual(line.metrics.ytd_return_pct,
                (next_year["observations"][-1]["equity"]/data["observations"][-1]["equity"]-1)*100)

    def test_changed_cash_or_corrupt_hash_is_rejected(self):
        data=advance(held(),"2026-02-02")
        changed=copy.deepcopy(data);changed["observations"][0]["equity"]+=1
        with self.assertRaises(ValueError):validate(changed)
        changed["state_hash"]=canonical_hash({k:v for k,v in changed.items() if k!="state_hash"})
        with self.assertRaises(ValueError):validate(changed)

    def test_existing_collector_refreshes_cash_account_on_unchanged_closed_input(self):
        repo=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location("g20_collector",repo/"scripts/operations/collect_dual_engine_market.py")
        collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/"state").mkdir();(root/"g20-cash").mkdir()
            p=root/"state/program.json";p.write_text(json.dumps(dict(last_data_cutoff="same")))
            (root/"g20-cash/forward.json").write_text("{}")
            before=p.read_bytes()
            with patch.object(collector,"collect_market_cycle",return_value=SimpleNamespace(data_cutoff="same")), \
                 patch("qount.dual_engine.g20_cash.refresh") as refresh_mock:
                result=collector.main(["--config",str(repo/"deploy/dual_engine/paper-v1.json"),
                    "--state-root",str(root),"--event","daily-close"])
            self.assertEqual(result,0);refresh_mock.assert_called_once();self.assertEqual(p.read_bytes(),before)


if __name__=="__main__":unittest.main()
