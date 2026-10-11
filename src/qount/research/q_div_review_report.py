"""Reader-facing dated Q-DIV dividend diagnostics; static inputs, no acquisition."""
import html
from pathlib import Path


# Editorial diligence queue, not a numerical score or strategy selection rule.
DEEPER = {'600900.SH', '600018.SH', '601326.SH'}
DIVIDEND_REVIEW = {'600351.SH', '603766.SH'}
NEXT_EVIDENCE = {
    '600900.SH': '来水与电量、折旧与检修资本开支、债务偿还；估值对稳定现金流的溢价',
    '600018.SH': '港口主业与联营投资收益拆分、货量/费率、母公司现金可上划性',
    '000651.SZ': '收入/利润变化、渠道及营运资本，经营现金流下降能否逆转',
    '000598.SZ': '项目回款、在建工程与资本开支，CFO下降是否为阶段性',
    '601326.SH': '吞吐量、煤炭运输结构、费率与维持性资本开支',
    '601919.SH': '运价/运量与运力交付，周期中枢盈利下的现金分红',
    '601088.SH': '煤价、煤电盈利及资本开支；跨A/H总市值口径',
    '600642.SH': '利润与CFO同步下降原因，燃料成本、投资收益及分红约束',
    '601857.SH': '油气价格、上游盈利与资本开支；跨A/H总市值口径',
    '600483.SH': '利润轻微下降的分部来源、燃料成本和项目投运现金需求',
    '600351.SH': '三次付款跨年度窗口、未来分红政策及母公司可分配现金，回购分开',
    '601225.SH': '煤价/销量与一次性损益，归母利润增长可重复程度',
    '600060.SH': '利润增长与CFO下降背离、存货应收和渠道现金回笼',
    '603233.SH': '利润增长与CFO下降背离、租赁及门店扩张资本需求',
    '002039.SZ': '来水波动、低基数、债务及水电维护资本开支',
    '603387.SH': '盈利增长来源、扣非及一次性收益，医疗业务回款',
    '603766.SH': '盈利/CFO下降与分红率上升，海外需求及中期授权实际实施',
    '000690.SZ': '煤电价差与新项目支出，历史分红波动',
    '002832.SZ': '消费需求、库存和渠道扩张，估值是否已计入增长',
    '601330.SH': '垃圾焚烧项目回款、特许经营项目资本开支与债务',
}


def category(row):
    if row['symbol'] in DIVIDEND_REVIEW:
        return '分红解释优先复核'
    if row['symbol'] in DEEPER:
        return '经营与估值优先深挖'
    if row['flags']:
        return '经营变化待复核'
    return '常规估值待核'


def render(summary, rows, sources, out):
    esc = lambda value: html.escape(str(value), quote=True)
    pct = lambda value: '未知' if value is None else f'{value * 100:.2f}%'
    num = lambda value: '未知' if value is None else f'{value:.2f}'
    money = lambda value: '未知' if value is None else f'{value / 1e8:,.3f}'
    def table(headers, body):
        return '<div class="scroll"><table><thead><tr>' + ''.join('<th>' + esc(x) + '</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + esc(v) + '</td>' for v in r) + '</tr>' for r in body) + '</tbody></table></div>'
    groups = ['经营与估值优先深挖', '分红解释优先复核', '经营变化待复核', '常规估值待核']
    counts = {g: sum(category(r) == g for r in rows) for g in groups}
    by_code = {r['symbol']: r for r in rows}
    source_link = {s['id']: '<a href="' + esc(s['url']) + '" target="_blank" rel="noreferrer">' + esc(s['title']) + '</a>' for s in sources['sources']}
    cards = ''
    for symbol in ('600900.SH', '600018.SH', '601326.SH'):
        r = by_code[symbol]
        cards += f'''<article class="card"><p class="eyebrow">经营与估值优先深挖 · 研究判断</p><h3>{esc(r['name'])} <small>{esc(symbol)}</small></h3>
<p>最新H1利润同比 {pct(r['latest_YTD_parent_profit_growth'])}，CFO同比 {pct(r['latest_YTD_CFO_growth'])}；已付股息率 {pct(r['paid_dividend_yield'])}，CFO/滚动已付现金 {num(r['CFO_TTM_to_paid_cash_365d'])}倍。<a href="#numerical-sources">数字来源</a></p>
<p><b>为何现在研究：</b>已进入冻结候选，盈利和CFO均未同比下降，适合先查现金能否长期留给股东。<b>预期差：</b>尚未建立；9/30估值代理不代表当前便宜。</p>
<p><b>首要否决点：</b>扣除必要资本开支、偿债及子公司留存后不能持续支持分红。<b>深挖重点：</b>{esc(NEXT_EVIDENCE[symbol])}。</p>
<p><b>进入可投资讨论的条件：</b>补齐可比TTM/母公司现金、估值情景与新鲜行情资格。<b>证伪证据：</b>后续披露显示分红持续依赖举债或一次性收益。<b>下一工作：</b>现金流审阅 → 可比估值；当前列观察研究。</p></article>'''
    board = ''
    for r in rows:
        label = category(r)
        flags = []
        if 'trailing_cash_exceeds_latest_TTM_profit' in r['flags']:
            flags.append('滚动现金高于TTM利润')
        if 'latest_YTD_profit_declined' in r['flags']:
            flags.append('利润同比下降')
        if 'latest_YTD_CFO_declined' in r['flags']:
            flags.append('CFO同比下降')
        values = [r['snapshot_rank'], r['name'], r['symbol'], label,
                  pct(r['paid_dividend_yield']), num(r['PE_parent_TTM_A_quote_proxy']),
                  pct(r['cash_paid_365d_to_latest_TTM_profit']),
                  num(r['CFO_TTM_to_paid_cash_365d']),
                  pct(r['latest_YTD_parent_profit_growth']), pct(r['latest_YTD_CFO_growth']),
                  '；'.join(flags) or '本项同比/现金覆盖未触发标记']
        board += '<tr data-group="' + esc(label) + '">' + ''.join('<td>' + esc(v) + '</td>' for v in values) + '</tr>'
    headings = ['原排名', '名称', '证券', '研究队列', '已付股息率', '市值/TTM利润', '365日现金/TTM利润', 'CFO/365日现金', 'H1利润同比', 'H1 CFO同比', '核查提示']
    board = '<div class="scroll"><table id="board"><thead><tr>' + ''.join('<th>' + esc(x) + '</th>' for x in headings) + '</tr></thead><tbody>' + board + '</tbody></table></div>'
    annual = []
    for r in rows:
        for a in r['annual']:
            annual.append([r['name'], a['fiscal_year'], money(a['parent_profit_cny']),
                           money(a['paid_for_fiscal_year_through_cutoff_cny']),
                           pct(a['cash_to_matched_fiscal_profit']), num(a['CFO_to_cash'])])
    events = []
    for symbol in ('600351.SH', '603766.SH'):
        for e in by_code[symbol]['paid_events']:
            if e['in_trailing_payment_window']:
                events.append([by_code[symbol]['name'], e['fiscal_period'], e['implementation_announcement'],
                               e['pay_date'], num(e['cash_per_share_cny']), money(e['cash_cny'])])
    steps = table(['候选', '首先需要的证据', '预期/估值状态'],
                  [[r['name'], NEXT_EVIDENCE[r['symbol']], '当前价格与预期差未核；仅作研究观察'] for r in rows])
    source_register = ''.join('<li id="' + esc(s['id']) + '"><b>' + esc(s['announcement_date']) + '</b> · ' + source_link[s['id']] + '：' + esc(s['review_status']) + '。</li>' for s in sources['sources'])
    tiles = ''.join('<div><span>' + esc(g) + '</span><strong>' + str(counts[g]) + '</strong></div>' for g in groups)
    content = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Q-DIV｜分红质量与候选深挖 · 2026-10-11</title><style>
*{{box-sizing:border-box}}body{{margin:0;color:#172c3a;background:#f3f5f5;font:16px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}main{{max-width:1320px;margin:auto;padding:34px 28px 64px}}h1{{font-size:34px;line-height:1.35;max-width:900px}}h2{{font-size:23px;margin:0 0 16px}}h3{{font-size:21px;margin:4px 0 12px}}small,.muted{{color:#566876;font-size:14px}}a{{color:#096970;text-underline-offset:3px}}p{{margin:12px 0}}.eyebrow{{font-size:13px;color:#397279;letter-spacing:.04em}}.badge{{display:inline-block;background:#e3efed;color:#175b51;border-radius:5px;padding:4px 10px;font-size:13px}}.card,section{{background:#fff;border:1px solid #dbe3e4;border-radius:12px;padding:24px;margin:20px 0}}.hero{{background:#142f3a;color:#f5f8f9;border:0;padding:30px}}.hero .muted{{color:#c8d8dd}}.hero a{{color:#b4e1dc}}.tiles{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0 0}}.tiles div{{border-top:1px solid #56717b;padding-top:13px}}.tiles span{{display:block;font-size:14px}}.tiles strong{{font-size:32px;font-weight:600}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}.cards .card{{margin:0;padding:20px}}.cards p{{font-size:14px}}.scroll{{overflow-x:auto;border:1px solid #e1e7e8;border-radius:7px}}table{{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}}th,td{{padding:11px 13px;text-align:left;border-bottom:1px solid #e1e7e8;vertical-align:top}}th{{background:#eef3f3;font-weight:600;white-space:nowrap}}#board td{{white-space:nowrap}}td:last-child{{min-width:150px}}tr:last-child td{{border:0}}.note{{border-left:3px solid #b37c30;background:#faf5ec;padding:14px 18px}}.toolbar{{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}}input,select{{font:inherit;padding:8px 12px;border:1px solid #9cafb6;border-radius:6px;background:#fff;max-width:100%}}summary{{cursor:pointer;font-weight:600}}li{{margin:8px 0}}code{{word-break:break-all}}nav{{display:flex;flex-wrap:wrap;gap:18px;margin:22px 0}}@media(max-width:950px){{.cards{{grid-template-columns:1fr}}}}@media(max-width:600px){{main{{padding:16px 12px 40px}}h1{{font-size:27px}}.hero,section,.card{{padding:19px}}.tiles{{grid-template-columns:repeat(2,1fr)}}.toolbar{{display:block}}input,select{{width:100%;margin:5px 0}}}}
</style></head><body><main><p class="eyebrow">QOUNT / A股独立研究 / 2026-10-11</p>
<section class="hero"><span class="badge">research_only · orders_authorized=false</span><h1>先看现金分红的质量，<br>再讨论股息率是否值得买</h1>
<p>在20个冻结候选上完成财年与付款日拆分。亚宝的滚动现金/TTM利润为 <b>117.76%</b>，按2025财政年度纯现金核算为 <b>75.68%</b>；隆鑫对应 <b>91.87% / 87.24%</b>。比例差异需要解释付款窗口，现有证据尚不能将其命名为特别分红。<a href="#payment">查看对账</a></p>
<p class="muted">研究队列优先处理两家分红解释及七家经营变化；长江电力、上港集团、秦港股份进入经营与估值深挖。尚无已证实的预期差或买入价。价格日期2026-09-30，行业描述2026-10-09；没有刷新价格、重选名单或运行历史收益。</p><div class="tiles">{tiles}</div></section>
<nav><a href="#candidates">20候选复核表</a><a href="#payment">两家分红对账</a><a href="#deep">优先深挖</a><a href="#next">证据队列</a><a href="#sources">来源与方法</a></nav>
<section id="candidates"><h2>同一份名单，增加现金与盈利诊断</h2><p>最新半年利润下降5家、CFO下降7家，两者有重叠；20家TTM CFO均高于滚动已付现金，最低覆盖 <b>{num(summary['minimum_CFO_to_paid_cash'])}倍</b>。<a href="#numerical-sources">数据与复算依据</a></p>
<p class="note">CFO是合并经营现金流，尚未扣资本开支、偿债或少数股东现金需求。这里的现金/TTM利润不是法定分红率，股息率也不是未来收益承诺。</p>
<div class="toolbar"><label>搜索 <input id="search" placeholder="名称 / 证券代码" aria-label="搜索候选"></label><label>研究队列 <select id="group" aria-label="研究队列"><option value="">全部候选</option>{''.join('<option>'+esc(g)+'</option>' for g in groups)}</select></label><span id="visible" class="muted" aria-live="polite">20 / 20</span></div>{board}
<p class="muted">按原冻结IVOL排名展示；研究队列是定性审阅安排，不是新的选股评分。市值/TTM利润仅为9/30 A股报价下总市值代理，跨A/H公司尚未桥接；不据此作跨行业便宜程度排名。历史已付股息率的原目标权重加权值 {pct(summary['target_weighted_historical_paid_yield'])}，只是静态描述，不是组合实际收益。</p></section>
<section id="payment"><h2>亚宝与隆鑫：付款窗口和财政年度分开</h2>
{table(['公司','分红所属期','实施公告日','付款日','税前元/股','现金亿元'],events)}
<p>付款日与基数来自已核验的供应商公开响应；部分实施PDF未能由网页工具读到，原文读取范围见<a href="#sources">来源记录</a>。不能声称完成两家公司公告全集或特别分红分类。</p>
<p><b>亚宝：</b>365日三笔合计3.806亿元，最新TTM归母3.232亿元；2025财政年度归属现金2.422亿元/利润3.200亿元 = 75.68%。其预案另把回购与现金分红合计为109.95%，本次明确排除回购。{source_link['YB-FY25']}；2026H1利润同比+1.83%、CFO同比+7.81%，见{source_link['YB-H126']}。</p>
<p><b>隆鑫：</b>365日两笔现金14.375亿元，最新TTM归母15.647亿元；2025纯现金分配/同财年归母87.24%，高于2024的73.26%与2023的35.20%。2026中期分红授权/预计额未计入已付现金。{source_link['LX-FY25']}；其中2025中期的付款日期见{source_link['LX-MID25']}。H1利润−7.73%、CFO−31.20%为已核验供应商报表计算，原半年报PDF仍待读。</p>
<p><b>研究含义：</b>亚宝优先解释下一窗口分红是否回归；隆鑫优先查盈利/CFO下降与分红率提高的关系。两者仍保留原名单与目标权重。只有后续资本开支、母公司现金及分红政策证据才能支持可持续性结论。</p>
<details><summary>展开全部20家 · 2023—2025同财年分红与现金覆盖（60行）</summary><p class="muted">现金仅为截至9/30已实施且已付、归属于该财政年度的金额；不包含尚未实施的未来权利。单位亿元。</p>{table(['公司','财年','归母利润','已付现金','现金/同财年利润','同财年CFO/现金'],annual)}</details></section>
<section id="deep"><h2>三家优先经营与估值深挖</h2><p>优先级来自原名单、经营增长和现金覆盖的研究判断。尚未核当前价格、共识预期或估值情景，均处于估值与入场证据待核阶段。</p><div class="cards">{cards}</div></section>
<section id="next"><h2>下一份证据应解决什么</h2>{steps}
<p>本轮没有因诊断标记剔除候选。若要运行Q-DIV历史四曲线，仍须逐信号日重建财报版本、风险/取消分红事件、换手/分红、市场/利率和执行结算资料，并独立验证组合引擎；当前20只不能回填历史股票池。</p></section>
<section id="sources"><h2>证据与解释口径</h2><p id="numerical-sources">数值来源：2026-10-10冻结快照及其480个已验证三表/分红响应，本轮在WSL/E直接读取原工件；未新取认证供应商数据。<a href="../../state/research_runs/ashare_q_div_review_20261011/diagnostics.json">逐证券诊断</a> · <a href="../../state/research_runs/ashare_q_div_review_20261011/independent-verification.json">独立复算回执</a> · <a href="../../docs/ashare-q-div-ivol-study-2026-10.md">研究协议</a>。</p>
<p>20家/60财年/94付款事件从原响应独立重算，数值一致；并非全3407证券的重新筛选，也不认证历史版本。市值用total_mv万元×10000；事件现金用税前每股现金×基准股本万股×10000，字段定义见<a href="https://tushare.pro/document/2?doc_id=103">官方分红文档</a>及<a href="https://tushare.pro/document/2?doc_id=32">每日指标文档</a>。现金窗口为(2025-09-30, 2026-09-30]；财报公告严格早于9/30。最新TTM为2025全年+2026H1−2025H1；同财年现金与年度利润另算。</p>
<ul>{source_register}</ul><p class="muted">没有现金总回报认证、独立样本外或历史回测。没有修改冻结经济参数，新增主要规则0、收益实验0、参数搜索0；无账户、订单、服务或调度变化。</p></section>
<script>const rows=[...document.querySelectorAll('#board tbody tr')];function filter(){{const q=document.getElementById('search').value.trim().toLowerCase(),g=document.getElementById('group').value;let n=0;for(const r of rows){{const ok=(!q||r.textContent.toLowerCase().includes(q))&&(!g||r.dataset.group===g);r.hidden=!ok;if(ok)n++;}}document.getElementById('visible').textContent=n+' / '+rows.length;}}document.getElementById('search').addEventListener('input',filter);document.getElementById('group').addEventListener('change',filter);</script>
</main></body></html>'''
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(content)
