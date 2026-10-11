"""A-share discovery strategy: dated selection and synthetic adjusted-unit holdings.

This is a costed vendor-price-proxy simulation, never an executable cash-return NAV.
Industry metadata is a disclosed modern snapshot. No orders/accounts/services exist.
"""
from __future__ import annotations
import collections
import dataclasses
import datetime as dt
import gzip
import hashlib
import json
import math
import statistics
import sys
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REAL_ESTATE = frozenset(('房产服务', '区域地产', '全国地产', '园区开发'))
RULES = {
    'capital_cny': 1_000_000, 'risk_style': 'aggressive_long_only_unlevered',
    'start': '20150101', 'end': '20260930', 'history': 252, 'window': 201,
    'minimum_mean_amount20_cny': 50_000_000, 'minimum_market_members': 500,
    'market_gate': 'strictly_more_than_half_eligible_above_MA200',
    'momentum': 'adj_close[t-20]/adj_close[t-120]-1',
    'sector_members': 10, 'sector_gate': 'median_momentum_gt0_and_positive_change20_fraction_ge_half',
    'sector_count': 10, 'industry_stock_fraction': .2,
    'maximum_positions': 10, 'new_entry_fraction': .1,
    'industry_slots': 2, 'real_estate_slots': 4, 'retention_rank': 20,
    'review_clock': 'first_2015_session_then_calendar_month_last_session',
    'exit': 'close_below_MA60_or_15pct_from_postentry_adjusted_close_peak_or_age_ge126',
    'market_off': 'no_new_buys_existing_positions_follow_individual_exits',
    'intent_lifecycle': 'buy_single_due_open_attempt_sell_persistent_next_open_no_same_review_rebuy',
    'execution_availability': 'open_reference_adjustment_only_plus_daily_activity_existence_proxy_no_high_low_close_gate',
    'buy_lot_raw_shares': 100, 'participation_prior_ADV': .01,
    'commission_fraction': .0003, 'commission_min_cny': 5,
    'commission_scope': 'assumed_broker_all_in_ex_transfer_and_stamp_not_verified_tariff',
    'transfer_fraction': 'assumed_0.0003_before_20150801_then0.00002_before_20220429_else0.00001_both_sides_not_exact_early_tariff',
    'stamp_fraction': '0.001_before_20230828_else_0.0005_sell_only',
    'slippage_fraction': .001,
    'opening_guard': 'skip_buy_open_ge_preclose_times1.0499_skip_sell_le_times0.9501_not_actual_limit_certification',
    'missing_mark': 'carry_last_observation_provisional_and_final_zero_to_carry_interval',
    'corporate_actions': 'synthetic_adjusted_units_not_cash_dividends_or_certified_share_changes',
    'curves': ['sector_base','sector_double_cost','sector_extra_day','price_control'],
    'financial_policy_overlay': 'not_in_historical_rules_no_PIT_sources_available',
}

@dataclasses.dataclass
class Features:
    eligible: bytearray
    momentum: array
    change20: array
    ma60: array
    ma200: array
    adv20: array


def make_features(s):
    n = len(s.valid)
    eligible = bytearray(n)
    momentum, change20, ma60, ma200, adv20 = (array('d', [math.nan])*n for _ in range(5))
    sums = {60: 0., 200: 0.}
    amount_sum, valid_run = 0., 0
    valid_counts={20:0,60:0,200:0}
    for j in range(n):
        c = s.adj_close[j]
        for length in sums:
            sums[length] += c if math.isfinite(c) and c > 0 else 0
            if j >= length:
                old = s.adj_close[j-length]
                sums[length] -= old if math.isfinite(old) and old > 0 else 0
        a = s.amount_cny[j]
        amount_sum += a if math.isfinite(a) and a > 0 else 0
        if j >= 20:
            old = s.amount_cny[j-20]
            amount_sum -= old if math.isfinite(old) and old > 0 else 0
        for length in valid_counts:
            valid_counts[length]+=bool(s.valid[j])
            if j>=length:valid_counts[length]-=bool(s.valid[j-length])
        if j>=59 and valid_counts[60]==60:ma60[j]=sums[60]/60
        if j>=199 and valid_counts[200]==200:ma200[j]=sums[200]/200
        if j>=19 and valid_counts[20]==20:adv20[j]=amount_sum/20
        valid_run += bool(s.valid[j])
        if j >= 201:
            valid_run -= bool(s.valid[j-201])
        if j < 200 or valid_run != 201 or s.history[j] < 252:
            continue
        ma60[j], ma200[j], adv20[j] = sums[60]/60, sums[200]/200, amount_sum/20
        momentum[j] = s.adj_close[j-20]/s.adj_close[j-120]-1
        change20[j] = c/s.adj_close[j-20]-1
        eligible[j] = adv20[j] >= RULES['minimum_mean_amount20_cny']
    return Features(eligible,momentum,change20,ma60,ma200,adv20)


def select(j, panel, features, metadata):
    eligible = [code for code,f in features.items() if f.eligible[j] and metadata.get(code,{}).get('industry')]
    market_on = (len(eligible) >= RULES['minimum_market_members'] and
                 sum(panel[c].adj_close[j] > features[c].ma200[j] for c in eligible) > len(eligible)/2)
    trend = [c for c in eligible if features[c].momentum[j] > 0 and panel[c].adj_close[j] > features[c].ma60[j]]
    price = sorted(trend,key=lambda c:(-features[c].momentum[j],c))
    sectors = collections.defaultdict(list)
    for c in eligible:
        industry = metadata.get(c,{}).get('industry')
        if industry:
            sectors[industry].append(c)
    available=[]
    for industry,codes in sectors.items():
        m=statistics.median(features[c].momentum[j] for c in codes)
        breadth=sum(features[c].change20[j]>0 for c in codes)/len(codes)
        if len(codes)>=10 and m>0 and breadth>=.5:
            available.append((industry,m,codes))
    available.sort(key=lambda x:(-x[1],x[0]))
    pool=[]
    for industry,m,codes in available[:10]:
        # Fraction is taken before filtering MA60/positive momentum, no rescue.
        top=sorted(codes,key=lambda c:(-features[c].momentum[j],c))[:math.floor(len(codes)*.2)]
        pool.extend(c for c in top if c in set(trend))
    pool.sort(key=lambda c:(-features[c].momentum[j],c))
    counts=collections.Counter();real=0;rank=[]
    for c in pool:
        industry=metadata[c]['industry']
        if counts[industry]>=2 or (industry in REAL_ESTATE and real>=4):
            continue
        rank.append(c);counts[industry]+=1;real+=industry in REAL_ESTATE
        if len(rank)==20: break
    return {'market_on':market_on,'eligible_count':len(eligible),'sector_rank':rank,
            'price_rank':price[:20],'selected_sectors':[x[0] for x in available[:10]],
            'eligible_retired':sum(panel[c].source_kind=='tushare_retired' for c in eligible)}


def costs(notional, side, day, scale=1):
    commission=max(5.,notional*.0003)
    transfer=notional*(.0003 if day<'20150801' else .00002 if day<'20220429' else .00001)
    stamp=notional*(.001 if day<'20230828' else .0005) if side=='sell' else 0.
    return scale*(commission+transfer+stamp)


def fill_quote(s,j,side,slippage):
    # Only open/reference quotes determine the price guard; no high/low path peek.
    raw,pre=s.raw_open[j],s.pre_close[j]
    adj=s.adj_open[j]
    if not all(math.isfinite(x) and x>0 for x in (raw,pre,adj)):
        return None,'missing_open_or_reference'
    if not all(math.isfinite(x) and x>0 for x in (s.factor[j],s.amount_cny[j],s.volume[j])):
        return None,'missing_factor_or_nonpositive_daily_activity_proxy'
    if (side=='buy' and raw>=pre*1.0499) or (side=='sell' and raw<=pre*.9501):
        return None,'conservative_opening_guard'
    price=raw*(1+slippage if side=='buy' else 1-slippage)
    return (price,adj/raw),'available_assumed_open_fill'


@dataclasses.dataclass
class Position:
    units: float
    entry_j: int
    entry_cost: float
    peak: float
    last_mark: float
    last_mark_j: int
    entry_signal_j: int


class Book:
    def __init__(self,name,metadata):
        self.name=name;self.metadata=metadata;self.cash=1_000_000.;self.positions={}
        self.pending=[];self.pending_sells=set();self.pending_buys=set()
        self.scale=2 if name=='sector_double_cost' else 1
        self.delay=1 if name=='sector_extra_day' else 0
        self.trades=[];self.closed=[];self.curve=[];self.blocks=collections.Counter();self.intents=[]

    @property
    def sector_rules(self): return self.name!='price_control'

    def nav(self):return self.cash+sum(p.units*p.last_mark for p in self.positions.values())

    def slots_allow(self,code,excluded=()):
        held=[c for c in self.positions if c not in excluded]
        if len(held)>=10:return False
        if not self.sector_rules:return True
        industry=self.metadata.get(code,{}).get('industry')
        if sum(self.metadata.get(c,{}).get('industry')==industry for c in held)>=2:return False
        return not (industry in REAL_ESTATE and sum(self.metadata.get(c,{}).get('industry') in REAL_ESTATE for c in held)>=4)

    def execute(self,j,day,panel):
        due=sorted([x for x in self.pending if x['due_j']==j],key=lambda x:(x['side']!='sell',x['order']))
        self.pending=[x for x in self.pending if x['due_j']!=j]
        for intent in due:
            code,side=intent['symbol'],intent['side'];s=panel[code]
            (self.pending_sells if side=='sell' else self.pending_buys).discard(code)
            if side=='sell' and code not in self.positions:continue
            if side=='buy' and (code in self.positions or not self.slots_allow(code)):
                self.blocks['slot_or_exposure_cap']+=1;continue
            quote,reason=fill_quote(s,j,side,.001*self.scale)
            if quote is None:
                self.blocks[side+':'+reason]+=1
                if side=='sell':
                    self.pending.append({**intent,'due_j':j+1});self.pending_sells.add(code)
                continue
            raw,ratio=quote
            if side=='sell':
                p=self.positions[code]
                if j<=p.entry_j:
                    self.blocks['T_plus_1']+=1;continue
                notional=p.units*ratio*raw
                # A block never replaces a sold/bought name using future availability.
                if notional>intent['adv20']*.01:
                    self.blocks['sell_participation_cap']+=1
                    self.pending.append({**intent,'due_j':j+1});self.pending_sells.add(code)
                    continue
                fee=costs(notional,'sell',day,self.scale);self.cash+=notional-fee
                pnl=notional-fee-p.entry_cost
                self.closed.append({'symbol':code,'entry_j':p.entry_j,'exit_j':j,'holding_sessions':j-p.entry_j,
                    'pnl_cny':pnl,'entry_cost_cny':p.entry_cost,'net_trade_return':pnl/p.entry_cost,'reason':intent['reason']})
                units=p.units;del self.positions[code]
            else:
                # Quantity was sized at decision close in whole raw lots. Only reduce
                # at fill for real cash/participation; never increase after a gap down.
                shares=intent['raw_shares']
                limit=min(self.cash,intent['budget_cny'],intent['adv20']*.01)
                shares=min(shares,math.floor(limit/(raw*(1+.0003*self.scale+.00002*self.scale))/100)*100)
                while shares>=100 and raw*shares+costs(raw*shares,'buy',day,self.scale)>limit:shares-=100
                if shares<100:
                    self.blocks['cash_or_lot_or_participation']+=1;continue
                notional=shares*raw;fee=costs(notional,'buy',day,self.scale);self.cash-=notional+fee
                units=shares/ratio
                # The entry-day closing price is not known at the opening fill.
                self.positions[code]=Position(units,j,notional+fee,0.,s.adj_open[j],j,intent['signal_j'])
            assert self.cash>=-1e-7
            self.trades.append({'date':day,'j':j,'signal_j':intent['signal_j'],'symbol':code,'side':side,
                'units':units,'raw_price_with_slippage':raw,'adjusted_per_raw_ratio':ratio,'notional_cny':notional,
                'fees_cny':fee,'cash_after':self.cash,'reason':intent['reason']})

    def mark(self,j,day,panel):
        unknown=0.;max_age=0;weights=collections.Counter();real=0.;max_weight=0
        for code,p in self.positions.items():
            s=panel[code];close=s.adj_close[j]
            if s.valid[j] and math.isfinite(close) and close>0:
                p.last_mark=close;p.last_mark_j=j;p.peak=max(p.peak,close)
            else:unknown+=p.units*p.last_mark
            max_age=max(max_age,j-p.last_mark_j)
            v=p.units*p.last_mark;weights[self.metadata.get(code,{}).get('industry') or '__unknown__']+=v
            if self.metadata.get(code,{}).get('industry') in REAL_ESTATE:real+=v
            max_weight=max(max_weight,v)
        nav=self.nav()
        row={'date':day,'j':j,'nav_carry_proxy_cny':nav,'cash_cny':self.cash,'positions':len(self.positions),
             'missing_mark_value_cny':unknown,'missing_mark_fraction':unknown/nav,'max_stale_sessions':max_age,
             'max_name_weight':max_weight/nav,'max_industry_weight':max(weights.values(),default=0)/nav,
             'real_estate_weight':real/nav,'provisional':unknown>0}
        self.curve.append(row);return row

    def decisions(self,j,day,panel,features,selection,monthly,last_j):
        ranking=selection['sector_rank' if self.sector_rules else 'price_rank'];keep=set(ranking)
        exits={}
        for code,p in self.positions.items():
            c=panel[code].adj_close[j] if panel[code].valid[j] else math.nan;ma=features[code].ma60[j]
            reason=('age126' if j-p.entry_j>=126 else
                'trailing15_close' if math.isfinite(c) and p.peak>0 and c<=p.peak*.85 else
                'below_MA60_close' if math.isfinite(c) and math.isfinite(ma) and c<ma else
                'monthly_rank_exit' if monthly and code not in keep else None)
            if reason:exits[code]=reason
        for code,reason in sorted(exits.items()):
            if code in self.pending_sells or j+1+self.delay>last_j:continue
            adv=features[code].adv20[j]
            if not math.isfinite(adv):
                # Last known predecision liquidity, not a future available day.
                adv=next((features[code].adv20[k] for k in range(j,-1,-1) if math.isfinite(features[code].adv20[k])),0.)
            self.plan(j,code,'sell',reason,adv20=adv)
        if not monthly or not selection['market_on'] or j+1+self.delay>last_j:return
        # Reserve slots using predecision planned exits; fill rechecks actual holdings.
        reserved=[c for c in self.positions if c not in exits]
        for code in ranking:
            if code in self.positions or code in self.pending_buys or len(reserved)>=10:continue
            industry=self.metadata.get(code,{}).get('industry')
            if self.sector_rules:
                if sum(self.metadata.get(c,{}).get('industry')==industry for c in reserved)>=2:continue
                if industry in REAL_ESTATE and sum(self.metadata.get(c,{}).get('industry') in REAL_ESTATE for c in reserved)>=4:continue
            budget=self.nav()*.1
            shares=math.floor(budget/panel[code].raw_close[j]/100)*100
            self.plan(j,code,'buy','monthly_entry',adv20=features[code].adv20[j],raw_shares=shares,budget_cny=budget)
            reserved.append(code)

    def plan(self,j,code,side,reason,**kwargs):
        intent={'signal_j':j,'due_j':j+1+self.delay,'symbol':code,'side':side,'reason':reason,'order':len(self.intents),**kwargs}
        self.pending.append(intent);self.intents.append(intent)
        (self.pending_sells if side=='sell' else self.pending_buys).add(code)


def metrics(curve,closed,initial=1_000_000):
    nav=[initial]+[r['nav_carry_proxy_cny'] for r in curve]
    returns=[b/a-1 for a,b in zip(nav,nav[1:])]
    high=initial;dd=0
    for v in nav:high=max(high,v);dd=min(dd,v/high-1)
    n=len(returns);vol=statistics.pstdev(returns) if n else 0
    last=curve[-1] if curve else {'nav_carry_proxy_cny':initial,'missing_mark_value_cny':0}
    lower=last['nav_carry_proxy_cny']-last['missing_mark_value_cny']
    return {'total_return_carry_proxy':nav[-1]/initial-1,'CAGR_carry_proxy':(nav[-1]/initial)**(252/n)-1 if n else 0,
        'final_unknown_zero_recovery_return':lower/initial-1,
        'CAGR_unknown_zero_recovery':(lower/initial)**(252/n)-1 if n and lower>0 else None,
        'max_drawdown_carry_proxy':dd,'sharpe_zero_cash_rate_carry_proxy':statistics.fmean(returns)/vol*math.sqrt(252) if vol else None,
        'mean_invested_fraction':statistics.fmean(1-r['cash_cny']/r['nav_carry_proxy_cny'] for r in curve) if curve else 0,
        'closed_trades':len(closed),'closed_win_fraction':sum(t['pnl_cny']>0 for t in closed)/len(closed) if closed else None,
        'median_hold_sessions':statistics.median(t['holding_sessions'] for t in closed) if closed else None,
        'provisional_mark_days':sum(r['provisional'] for r in curve),'maximum_missing_mark_fraction':max((r['missing_mark_fraction'] for r in curve),default=0),
        'maximum_stale_sessions':max((r['max_stale_sessions'] for r in curve),default=0),
        'peak_name_weight':max((r['max_name_weight'] for r in curve),default=0),
        'peak_industry_weight':max((r['max_industry_weight'] for r in curve),default=0),
        'peak_real_estate_weight':max((r['real_estate_weight'] for r in curve),default=0)}


def backtest(sessions,panel,metadata):
    features={c:make_features(s) for c,s in panel.items()}
    start=next(j for j,d in enumerate(sessions) if d>='20150101');end=len(sessions)-1
    books={name:Book(name,metadata) for name in RULES['curves']};signals=[]
    for j in range(start,end+1):
        day=sessions[j];monthly=j==start or j==end or sessions[j+1][:6]!=day[:6]
        for book in books.values():book.execute(j,day,panel);book.mark(j,day,panel)
        # Select only on scheduled reviews; daily exits do not consult future ranks.
        selection=select(j,panel,features,metadata) if monthly else {'market_on':False,'sector_rank':[],'price_rank':[]}
        if monthly:signals.append({'date':day,'j':j,**selection})
        for book in books.values():book.decisions(j,day,panel,features,selection,monthly,end)
    return books,signals


def write_json(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def run(contract_path,out):
    from qount.research.ashare_backtest_data import load_panel
    contract=json.loads(contract_path.read_text())
    if (contract.get('rules')!=RULES or contract.get('research_only') is not True or contract.get('orders_authorized') is not False
        or contract.get('promotion_evidence') is not False or contract.get('authorization')!={'backtest':True,'orders':False,'services':False}):raise ValueError('strategy_contract_invalid')
    if sys.platform!='linux' or out.exists() or not out.resolve().is_relative_to(Path('/mnt/e/qount_data/qount/artifacts/equity_selection')):raise ValueError('fresh_WSL_E_output_required')
    for name,sha in contract['implementation_sha256'].items():
        p=(ROOT/name).resolve()
        if not p.is_relative_to(ROOT) or digest(p)!=sha:raise ValueError('frozen_code_mismatch:'+name)
    if sys.version.split()[0]!=contract['python_version']:raise ValueError('python_version_mismatch')
    sessions,panel,metadata,diagnostics=load_panel(contract)
    out.mkdir(parents=True);write_json(out/'contract.json',contract)
    started=dt.datetime.now(dt.timezone.utc).isoformat();books,signals=backtest(sessions,panel,metadata)
    summary={'research_only':True,'orders_authorized':False,'promotion_evidence':False,
        'status':'conditional_snapshot_industry_adjusted_unit_discovery_backtest','started_at':started,
        'finished_at':dt.datetime.now(dt.timezone.utc).isoformat(),'price_cutoff':sessions[-1],
        'formal_cash_NAV_certified':False,'historical_PIT_certified':False,'financial_or_policy_signal_backtested':False,'common_universe':'known_snapshot_industry_both_candidate_and_control_no_current_ST_or_status_filter',
        'independent_OOS':False,'DSR_or_PBO':'not_computed_one_new_strategy_rule_set_four_registered_curves',
        'registered_strategy_rule_sets':1,'registered_curves':4,'parameter_searches':0,'source':diagnostics,'results':{}}
    write_json(out/'signals.json',signals)
    for name,book in books.items():
        result=metrics(book.curve,book.closed)
        result.update(fees_cny=sum(t['fees_cny'] for t in book.trades),fills=len(book.trades),blocked=dict(book.blocks),final_open_positions=len(book.positions))
        result['yearly']={year:metrics([r for r in book.curve if r['date'].startswith(year)],[],initial=next((r['nav_carry_proxy_cny'] for r in reversed(book.curve) if r['date']<year+'0101'),1_000_000)) for year in sorted({r['date'][:4] for r in book.curve})}
        result['segments']={label:metrics([r for r in book.curve if lo<=r['date']<=hi],[],initial=next((r['nav_carry_proxy_cny'] for r in reversed(book.curve) if r['date']<lo),1_000_000)) for label,lo,hi in [('2015–2018','20150101','20181231'),('2019–2022','20190101','20221231'),('2023–2026','20230101','20260930')]}
        summary['results'][name]=result
        for suffix,data in [('curve',book.curve),('fills',book.trades),('closed',book.closed),('intents',book.intents)]:
            with gzip.open(out/(name+'-'+suffix+'.jsonl.gz'),'wt',encoding='utf-8') as f:
                for row in data:f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
        holdings=[]
        for code,p in sorted(book.positions.items()):
            s=panel[code];f=make_features(s);c=s.adj_close[-1];ma=f.ma60[-1]
            holdings.append({'symbol':code,'name':metadata.get(code,{}).get('name'),'industry_snapshot':metadata.get(code,{}).get('industry'),
                **dataclasses.asdict(p),'weight_carry_proxy':p.units*p.last_mark/book.nav(),
                'unrealized_proxy_pnl_cny':p.units*p.last_mark-p.entry_cost,'current_mark_missing':p.last_mark_j!=len(sessions)-1,
                'adjusted_close_trailing_exit_level':p.peak*.85,'MA60_exit_level':ma if math.isfinite(ma) else None,
                'max_age_exit_j':p.entry_j+126,'entry_date':sessions[p.entry_j],
                'dated_ST_board_tradability':'pending','fundamental_review':'separate_current_overlay_not_historical_filter'})
        write_json(out/(name+'-holdings.json'),holdings)
    primary=summary['results']['sector_base'];control=summary['results']['price_control']
    summary['decision']={'historical_proxy_profitable':primary['total_return_carry_proxy']>0,
        'all_primary_cost_delay_cells_positive':all(summary['results'][n]['final_unknown_zero_recovery_return']>0 for n in RULES['curves'][:3]),
        'sector_increment_total_return_over_price_control':primary['total_return_carry_proxy']-control['total_return_carry_proxy'],
        'production_or_profitability_certification':False}
    write_json(out/'summary.json',summary)
    write_json(out/'manifest.json',{p.name:digest(p) for p in sorted(out.iterdir()) if p.is_file()})
    return summary
