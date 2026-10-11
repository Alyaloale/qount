"""Static, credential-free Q-DIV snapshot report; no data or execution calls."""
import html
import json
from pathlib import Path


def render(technical, summary, reviewed, selected, out):
    esc=lambda x:html.escape(str(x))
    pct=lambda x:'—' if x is None else f'{x*100:.2f}%'
    def table(headers,rows):
        head=''.join('<th>'+esc(x)+'</th>' for x in headers)
        body=''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows)
        return '<div class="table"><table><thead><tr>'+head+'</tr></thead><tbody>'+body+'</tbody></table></div>'
    selected_rows=[[r['symbol'],r.get('name') or '—',r['industry'],pct(r['IVOL']),pct(r['yield_TTM']),
                    pct(r['quality']['ROE_TTM']),f"{r['quality']['CFO_to_parent_profit_TTM']:.2f}",
                    pct(r['Bias60']),pct(r['target_weight'])] for r in selected]
    failures=[[r['symbol'],r.get('name') or '—',r['status'],r.get('reason') or
               ', '.join(x['reason'] for x in (r.get('quality',{}),r.get('dividend',{})) if x.get('reason')!='pass')]
              for r in reviewed if r['status']!='pass']
    funnel=[['原价格面板',technical['source']['panel_securities']],['成熟且连续窗口有效',technical['mature_price_pool']],
            ['成交额与相对流动性通过',technical['liquid_pool']],['剔除当日ST且20日换手完整',technical['complete_turnover_pool']],
            ['低换手通过',technical['low_turnover_pool']],['趋势＋缩量入场＋IVOL有效',technical['technical_passers']],
            ['财务与分红同时通过',summary['counts'].get('pass',0)],['排名与行业数量上限后',len(selected)]]
    doc=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Q-DIV-IVOL｜2026-09-30 条件筛选</title><style>
*{{box-sizing:border-box}}body{{font:16px/1.65 system-ui,sans-serif;background:#f1f5f9;color:#14213a;margin:0}}
main{{max-width:1160px;margin:auto;padding:28px 20px 60px}}h1{{font-size:30px;line-height:1.3}}h2{{font-size:21px;margin-top:30px}}
.card{{background:white;border:1px solid #dce4ee;border-radius:14px;padding:22px;margin:16px 0}}.tag{{color:#7c4000;background:#fff3d6;padding:6px 10px;border-radius:7px;display:inline-block}}
.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}.metric{{font-size:29px;color:#125e66}}.muted{{color:#52627b}}
.table{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #e2e8f0;white-space:nowrap}}th{{background:#edf4f8}}
li{{margin:8px 0}}code{{overflow-wrap:anywhere}}@media(max-width:650px){{main{{padding:18px 12px}}.metrics{{grid-template-columns:1fr}}h1{{font-size:25px}}.card{{padding:16px}}}}
</style><main><p class="muted">qount / A股独立研究 / 2026-10-10</p><h1>高质量红利低特质波动：首轮条件筛选</h1>
<span class="tag">research_only · orders_authorized=false · 历史回测未运行</span>
<p>价格与资格日期 <b>2026-09-30</b>；财报和分红按公告日期过滤，但供应商历史修订版本尚未认证。这是一个有明确截止日期的条件研究快照。</p>
<div class="metrics"><div class="card">技术条件候选<div class="metric">{technical['technical_passers']}</div></div>
<div class="card">最终研究候选<div class="metric">{len(selected)}</div></div><div class="card">未分配目标资金<div class="metric">{pct(summary['target_cash_weight'])}</div></div></div>
<section class="card"><h2>逐层筛选</h2>{table(['筛选阶段','证券数'],funnel)}
<p class="muted">财务请求上限120只，按IVOL固定顺序取得；本次是否截断：{esc(technical['shortlist_truncated'])}。数据未知与不达门槛分别保留；不强行凑满15–20只。</p></section>
<section class="card"><h2>候选与目标权重</h2>{table(['证券','名称快照','行业快照','IVOL','已付股息率TTM','ROE TTM','CFO/归母利润','Bias60','目标权重'],selected_rows)}
<p>目标权重按股息率/IVOL分配，单股≤8%、同行业≤3只且≤20%。行业是2026-10-09快照，不是历史一级行业中性化；上限约束无法分配的资金保留为现金。这里没有模拟持仓、成交或收益。</p></section>
<section class="card"><h2>财务复核结果</h2><p>通过 {summary['counts'].get('pass',0)}；未通过 {summary['counts'].get('fail',0)}；证据未知 {summary['counts'].get('unknown',0)}。</p>
{table(['证券','名称快照','状态','原因'],failures)}</section>
<section class="card"><h2>冻结的判断标准与尚未运行的回测</h2><p>预设四条曲线：基础、双成本、额外一天、同池行业等权对照。三主格零回收年化须各&gt;8%，基础最大回撤&lt;25%、日频超额夏普&gt;0.8、闭合≥100笔；失败保留且停止该实现，禁止调参救援。当前这些指标均为未测。</p>
<p>尚缺：完整历史财报版本、ST与调查/分红取消事件、历史换手率与分红资格、完整市场/利率窗口，以及历史执行状态和结算证据。当前名单不能回填成2015年以来的历史股票池。历史组合执行引擎尚未接入本模块。</p></section>
<section class="card"><h2>本版的固定口径</h2><ul><li>20个交易日实际换手率；120日单市场因子残差波动，市场代理为沪深300价格指数，利率代理为前一交易日SHIBOR隔夜，均有代理局限。</li>
<li>财报公告及实际公告日期严格早于筛选日；TTM用当期累计＋上年全年－上年同期，ROE分母为两期归母权益均值。同日冲突修订记录列未知。</li>
<li>仅工业企业comp_type=1；ROE≥8%、CFO/归母利润≥0.8、负债率&lt;70%。不把金融企业工业化计算。</li>
<li>前三个完整财政年度连续实施现金分红；仅过去365日已支付、实施公告已知的税前现金额计入股息率，门槛≥2.5%。分红不再次添加到复权价格收益。</li>
<li>价格&gt;MA200且MA200不下降；Bias60∈[−3%,12%]、Bias120&lt;20%、60日收益≤30%，5日量≤60日量的85%。</li>
<li>每10交易日复核，最多20只，入场前20、留仓前35；连续3日跌破0.97MA200才确认趋势退出。12%组合回撤规则只冻结新增20个完整交易日，不保证回撤上限。</li></ul></section>
<p class="muted">冻结合同SHA-256：<code>{esc(summary['contract_sha256'])}</code><br>本报告无账户、服务、调度或订单接口。旧低波动候选及已有失败记录保持。</p></main></html>'''
    Path(out).parent.mkdir(parents=True,exist_ok=True)
    Path(out).write_text(doc)
