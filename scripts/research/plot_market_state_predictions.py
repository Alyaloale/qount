"""Plot saved walk-forward predictions against daily hindsight state labels."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
from matplotlib import font_manager
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.ticker import PercentFormatter
import matplotlib.pyplot as plt
import numpy as np

from qount.research.market_state_dataset import CurrentStateDataset,DEFAULT_ROOT

COLORS=('#D34C44','#188668','#3978B6')
NAMES=('上行','下行','震荡')
STATE_HEIGHT=np.array([1,-1,0])
DAY=86400000


def configure():
    for path in ('/System/Library/Fonts/Supplemental/Arial Unicode.ttf','/System/Library/Fonts/STHeiti Light.ttc'):
        if Path(path).exists():
            font_manager.fontManager.addfont(path)
            plt.rcParams['font.family']=font_manager.FontProperties(fname=path).get_name();break
    plt.rcParams.update({'axes.unicode_minus':False,'font.size':10,'figure.facecolor':'#FAFAF7'})


def price_curve(ax,x,close,labels,title):
    points=np.c_[x,close];segments=np.stack((points[:-1],points[1:]),axis=1)
    ax.plot(x,close,color='#899195',lw=.6,alpha=.5)
    ax.add_collection(LineCollection(segments,colors=[COLORS[c] for c in labels[1:]],linewidths=1.9))
    ax.scatter(x,close,c=[COLORS[c] for c in labels],s=6,linewidths=0,zorder=3)
    start=0
    for stop in range(1,len(x)+1):
        if stop<len(x) and labels[stop]==labels[start]:continue
        ax.axvspan(x[start]-.5,x[stop-1]+.5,color=COLORS[labels[start]],alpha=.055,lw=0)
        start=stop
    span=max(float(np.ptp(close)),float(close.mean())*.02)
    ax.set_ylim(close.min()-.08*span,close.max()+.08*span)
    ax.set_title(title,loc='left',fontsize=11,pad=7);ax.set_ylabel('收盘价 / USDT')


def style(ax,x):
    ax.set_facecolor('white');ax.grid(axis='y',alpha=.22,color='#9EAAAD',linewidth=.6)
    ax.set_xlim(x[0]-.5,x[-1]+.5);ax.tick_params(labelsize=9)
    for side in ('top','right'):ax.spines[side].set_visible(False)
    for side in ('bottom','left'):ax.spines[side].set_color('#B7C0C3')


def detail(d,p,t,rows,asset,out,seed):
    x=mdates.date2num(d['bar_open_at'][rows].astype('datetime64[ms]'))
    close=d['market'][rows,3];truth=d['state'][rows];prob=p['probabilities'][rows];pred=prob.argmax(1)
    phase=p['phase_probabilities'][rows];early=phase[:,1:3].sum(1)
    true_early=np.isin(t['phase'][rows],[1,2])&t['phase_valid'][rows]
    fig,axes=plt.subplots(5,1,figsize=(16,12),sharex=True,
        gridspec_kw={'height_ratios':[2,2,1.15,1.45,1.4],'hspace':.36})
    fig.subplots_adjust(left=.075,right=.975,top=.875,bottom=.09)
    price_curve(axes[0],x,close,truth,'实际状态：事后标签着色（前后28根日线，未来14日确认）')
    price_curve(axes[1],x,close,pred,'预测状态：同一收盘价，按当天预测概率最高的类别着色')
    axes[2].step(x,STATE_HEIGHT[truth],where='mid',color='#27363B',lw=1.8,label='实际状态')
    axes[2].step(x,STATE_HEIGHT[pred],where='mid',color='#8754A8',ls='--',lw=1.4,label='预测状态')
    wrong=truth!=pred
    axes[2].fill_between(x,-1.3,1.3,where=wrong,step='mid',color='#B6BFC4',alpha=.18)
    axes[2].set_yticks([-1,0,1],['下行','震荡','上行']);axes[2].set_ylim(-1.3,1.3)
    axes[2].set_title('实际与预测的状态阶梯曲线（灰色为不一致的日期）',loc='left',fontsize=11)
    axes[2].legend(loc='upper right',ncol=2,frameon=False,fontsize=9)
    for c in range(3):axes[3].plot(x,prob[:,c],color=COLORS[c],lw=1.3,label=NAMES[c])
    axes[3].set_title('主状态预测概率',loc='left',fontsize=11);axes[3].set_ylim(0,1.03)
    axes[3].yaxis.set_major_formatter(PercentFormatter(1));axes[3].legend(loc='upper right',ncol=3,frameon=False,fontsize=9)
    axes[4].fill_between(x,0,true_early.astype(float),step='mid',color='#737E83',alpha=.17,label='实际处于新趋势前3日')
    axes[4].step(x,true_early.astype(float),where='mid',color='#7E888C',lw=.8,alpha=.7)
    axes[4].plot(x,early,color='#8754A8',lw=1.4,label='预测新趋势早期概率（已做历史校准）')
    axes[4].set_ylim(0,1.03);axes[4].yaxis.set_major_formatter(PercentFormatter(1))
    axes[4].set_title('独立阶段输出：当天是否处于上行／下行段的前3日',loc='left',fontsize=11)
    axes[4].legend(loc='upper right',ncol=2,frameon=False,fontsize=9)
    for ax in axes:style(ax,x)
    for ax in axes[:-1]:ax.tick_params(labelbottom=False)
    axes[-1].xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5,maxticks=9))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    first=str(d['bar_open_at'][rows[0]].astype('datetime64[ms]'))[:10]
    last=str(d['bar_open_at'][rows[-1]].astype('datetime64[ms]'))[:10]
    onsets=d['switch_label'][rows]&(truth<2);correct=int(np.sum(pred[onsets]==truth[onsets]))
    fig.suptitle(f'{asset} · 预测与实际状态对照',x=.075,ha='left',y=.98,fontsize=19,fontweight='bold')
    fig.text(.075,.947,f'{first} — {last} UTC日线  |  {len(rows)}天  |  本图状态正确率 {(pred==truth).mean():.1%}  |  新趋势首日 {correct}/{int(onsets.sum())}  |  种子{seed}',fontsize=11,color='#505C62')
    legend=[Line2D([0],[0],color=COLORS[c],lw=4,label=NAMES[c]) for c in range(3)]
    fig.legend(handles=legend,loc='upper left',bbox_to_anchor=(.071,.932),ncol=3,frameon=False)
    fig.text(.075,.041,'模型仅使用截至当天已收盘的14根原生日线；按季度前推生成。横轴按日线开盘日期对齐，收盘后一分钟决策。',fontsize=10,color='#505C62')
    fig.text(.075,.02,'实际状态及早期阶段为事后标签；末尾只展示已成熟答案。阶段概率不是未来3天切换预报；本图属于已消费历史研究。',fontsize=10,color='#505C62')
    path=out/f'{asset.lower()}_prediction_vs_actual.png';fig.savefig(path,dpi=165,facecolor=fig.get_facecolor())
    plt.close(fig)
    return dict(asset=asset,rows=len(rows),first_bar=first,last_bar=last,accuracy=float((pred==truth).mean()),
        trend_onset_rows=int(onsets.sum()),trend_onset_correct=correct,figure=path.name)


def overview(d,p,selections,out,days,seed):
    fig,axes=plt.subplots(len(selections),2,figsize=(17,2.3*len(selections)+1.8),squeeze=False)
    fig.subplots_adjust(left=.07,right=.975,top=.91,bottom=.045,hspace=.55,wspace=.13)
    for j,(asset,rows) in enumerate(selections):
        x=mdates.date2num(d['bar_open_at'][rows].astype('datetime64[ms]'));close=d['market'][rows,3]
        truth=d['state'][rows];pred=p['probabilities'][rows].argmax(1)
        price_curve(axes[j,0],x,close,truth,f'{asset} · 实际状态')
        price_curve(axes[j,1],x,close,pred,f'{asset} · 预测状态  |  本窗正确率 {(truth==pred).mean():.1%}')
        for ax in axes[j]:
            style(ax,x);ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3,maxticks=5))
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        axes[j,1].set_ylabel('')
    fig.suptitle(f'日线实际状态与预测状态 · 最近{days}天',x=.07,ha='left',y=.985,fontsize=19,fontweight='bold')
    first=str(d['bar_open_at'][selections[0][1][0]].astype('datetime64[ms]'))[:10]
    last=str(d['bar_open_at'][selections[0][1][-1]].astype('datetime64[ms]'))[:10]
    fig.text(.07,.963,f'{first} — {last}  |  左右为同一收盘价、相同纵轴范围  |  季度前推历史预测，种子{seed}',fontsize=11,color='#505C62')
    legend=[Line2D([0],[0],color=COLORS[c],lw=4,label=NAMES[c]) for c in range(3)]
    fig.legend(handles=legend,bbox_to_anchor=(.065,.95),loc='upper left',ncol=3,frameon=False)
    fig.text(.07,.014,'实际状态需要未来14天确认；预测只读截至当天的14根日线。按UTC日线开盘日期对齐，仅展示有成熟标签和有效预测的日期。',fontsize=10,color='#505C62')
    path=out/'all_assets_prediction_vs_actual.png';fig.savefig(path,dpi=165,facecolor=fig.get_facecolor());plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dataset',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--run',type=Path,default=Path('state/research_runs/market_state_transition_default_20261101'))
    parser.add_argument('--targets',type=Path,default=Path('state/research_runs/market_state_transition_repair_20261101/targets.npz'))
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--days',type=int,default=180)
    parser.add_argument('--assets',nargs='+');args=parser.parse_args()
    if args.output.exists():parser.error('preserve existing plots; choose a new output')
    if args.days<14:parser.error('at least14 daily bars required')
    ds=CurrentStateDataset(args.dataset);d=ds.data;r=json.loads((args.run/'results.json').read_text())
    with np.load(args.run/'predictions.npz',allow_pickle=False) as z:p={k:z[k] for k in z.files}
    with np.load(args.targets,allow_pickle=False) as z:t={k:z[k] for k in z.files}
    np.testing.assert_array_equal(p['source_row'],d['source_row']);np.testing.assert_array_equal(t['source_row'],d['source_row'])
    np.testing.assert_array_equal(t['state'],d['state']);np.testing.assert_array_equal(t['available_at'],d['label_available_at'])
    if bool(p['smoke_only']):raise ValueError('smoke_predictions_are_not_a_valid_visual_comparison')
    valid=np.isfinite(p['probabilities']).all(1)&(p['quarter_id']>=0)
    np.testing.assert_allclose(p['probabilities'][valid].sum(1),1,atol=2e-7)
    if not np.isfinite(p['phase_probabilities'][valid]).all():raise ValueError('missing_phase_prediction')
    for fit in r['folds']:
        assert fit['latest_training_label']<fit['cutoff']
        cal=fit.get('phase_calibration',{}).get('latest_label')
        assert cal is None or cal<fit['cutoff']
    assets=args.assets or ds.asset_names;configure();args.output.mkdir(parents=True)
    selections=[];metrics=[]
    for asset in assets:
        if asset not in ds.asset_names:raise ValueError('unknown_asset:'+asset)
        rows=np.flatnonzero((d['asset']==asset)&valid);end=d['bar_open_at'][rows].max()
        rows=rows[d['bar_open_at'][rows]>=end-(args.days-1)*DAY]
        if len(rows)<14 or np.any(np.diff(d['bar_open_at'][rows])!=DAY):raise ValueError('insufficient_or_gapped_plot_dates')
        selections.append((asset,rows));metrics.append(detail(d,p,t,rows,asset,args.output,r['seed']))
    overview(d,p,selections,args.output,args.days,r['seed'])
    lines=['# 预测与实际曲线','',f"默认训练入口保存的季度前推预测；种子{r['seed']}，最近{args.days}天，按UTC日线开盘日期对齐。",'',
        '红=上行，绿=下行，蓝=震荡。实际/预测两张价格图共用同一收盘价与纵轴范围；比较的是状态预测。',
        '实际状态与早期阶段均为事后标签，到k+n才成熟。预测只使用截至k的原生日线，训练和概率校准不使用当折测试答案。','',
        '[全部标的总览](all_assets_prediction_vs_actual.png)','',
        '| 标的 | 起止日 | 图中正确率 | 新趋势首日正确/样本 | 详细图 |','|---|---|---:|---:|---|']
    for m in metrics:lines.append(f"| {m['asset']} | {m['first_bar']}—{m['last_bar']} | {m['accuracy']:.2%} | {m['trend_onset_correct']}/{m['trend_onset_rows']} | [查看]({m['figure']}) |")
    lines += ['', '早期阶段概率表示当天处于新上/下行段前3日的概率，图中灰色阶梯为同一定义的实际0/1标签。它不是预测价格，也不是未来3天切换概率。',
        '研究历史已消费，图中命中率不代表独立未来表现或交易收益。本图按固定最新窗口绘制全部标的，没有按表现挑选日期或币种。']
    (args.output/'index.md').write_text('\n'.join(lines)+'\n')
    (args.output/'plot_metrics.json').write_text(json.dumps(dict(dataset=str(args.dataset),run=str(args.run),days=args.days,assets=metrics,
        research_only=True,orders_authorized=False),ensure_ascii=False,indent=2)+'\n')
    print(args.output/'all_assets_prediction_vs_actual.png')
    print(json.dumps(metrics,ensure_ascii=False))


if __name__=='__main__':main()
