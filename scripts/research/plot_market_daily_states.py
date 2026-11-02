"""Plot retained daily closes colored by their actual per-day state labels."""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
from matplotlib import font_manager
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.colors import to_rgba
import matplotlib.pyplot as plt
import numpy as np

STATE_STYLE={
    'uptrend':('#D84A4A','上行'), 'downtrend':('#148B6A','下行'),
    'rotation':('#3979BD','双向轮动'), 'compression':('#9365BD','波动收缩'),
    'low_efficiency_chop':('#8C969E','低效率震荡'),
    'transition':('#D79B25','转换（历史旧类）'),
}
SCALES=('3天参考尺度','1周参考尺度','2周参考尺度','约1个月参考尺度')


def plot_asset(data, asset, output, days, compare=None, end_date=None):
    indices=np.flatnonzero(data['asset']==asset)
    if not len(indices):raise ValueError(f'asset absent: {asset}')
    # known_at is a release clock, not the close date; remove the 60s buffer.
    clocks=data['known_at'][indices]-60000
    if end_date is not None:
        limit=int((dt.datetime.fromisoformat(end_date).replace(tzinfo=dt.timezone.utc)+dt.timedelta(days=1)).timestamp())*1000
        keep=clocks<=limit
        indices=indices[keep];clocks=clocks[keep]
        if not len(indices):raise ValueError('no_prices_before_plot_end')
    first=clocks.max()-days*86400000
    indices=indices[clocks>=first];clocks=clocks[clocks>=first]
    dates=[dt.datetime.fromtimestamp(int(t)/1000,dt.timezone.utc) for t in clocks]
    # Midnight is the end of the previous crypto session.
    if str(data['group'][indices[0]])=='crypto':
        dates=[d-dt.timedelta(seconds=1) for d in dates]
    x=mdates.date2num(dates);price=data['ohlcv'][indices,3]
    states=data['daily_state'][indices]
    horizons=data['horizon'][indices]
    panel_titles=SCALES
    changes=None
    if compare is not None:
        if not np.array_equal(data['known_at'],compare['known_at']) or not np.array_equal(data['asset'],compare['asset']):
            raise ValueError('comparison_daily_calendar_mismatch')
        states=np.c_[compare['daily_state'][indices,2],states[:,2]]
        horizons=np.c_[horizons[:,2],horizons[:,2]]
        panel_titles=('两周尺度：原标签','两周尺度：边界与弱短段处理后')
        changes=states[:,0]!=states[:,1]
    panels=states.shape[1]
    colors_for_states=tuple(STATE_STYLE[str(name)][0] for name in data['state_names'])
    names_for_states=tuple(STATE_STYLE[str(name)][1] for name in data['state_names'])
    centered=bool(data['label_uses_future']) if 'label_uses_future' in data else False
    comparison=compare is not None
    fig=plt.figure(figsize=(14,12 if panels==4 else 9),facecolor='#FAFAF7')
    grid=fig.add_gridspec(panels*2,1,height_ratios=[7,0.55]*panels,hspace=.50 if comparison else .26,
                         left=.075,right=.975,top=.80 if comparison else .895,bottom=.12 if comparison else .085)
    low,high=float(price.min()),float(price.max());padding=(high-low)*.08
    shared=None
    for j in range(panels):
        ax=fig.add_subplot(grid[j*2],sharex=shared)
        if shared is None:shared=ax
        strip=fig.add_subplot(grid[j*2+1],sharex=shared)
        ax.set_facecolor('white')
        points=np.c_[x,price]
        segments=np.stack((points[:-1],points[1:]),axis=1)
        colors=[colors_for_states[int(c)] if c>=0 else '#424A52' for c in states[1:,j]]
        ax.plot(x,price,color='#3B4246',linewidth=.65,alpha=.5,zorder=1)
        styles=['solid' if c>=0 else 'dashed' for c in states[1:,j]]
        ax.add_collection(LineCollection(segments,colors=colors,linestyles=styles,linewidths=2.0,zorder=3))
        ax.scatter(x,price,c=[colors_for_states[int(c)] if c>=0 else '#222222' for c in states[:,j]],s=6,zorder=4,linewidths=0)
        if changes is not None and j==1:
            ax.scatter(x[changes],price[changes],s=32,facecolors='none',edgecolors='#20272B',linewidths=.8,zorder=5)
        # Shade actual contiguous state spells. No fixed five-day separators.
        start=0
        for stop in range(1,len(x)+1):
            if stop<len(x) and states[stop,j]==states[start,j]:continue
            c=int(states[start,j])
            if c>=0:ax.axvspan(x[start]-.5,x[stop-1]+.5,color=colors_for_states[c],alpha=.065,lw=0,zorder=0)
            else:ax.axvspan(x[start]-.5,x[stop-1]+.5,color='#8C969E',alpha=.12,lw=0,zorder=0)
            start=stop
        n=int(horizons[0,j])
        description=f'过去 {n} 根（含当日）＋未来 {n} 根' if centered else f'局部窗口 {n+2} 根日线'
        ax.set_title(f'{panel_titles[j]}  |  n={n}，{description}',loc='left',fontsize=12,pad=7,fontweight='bold')
        ax.set_ylabel('USDT',fontsize=10,color='#454C50')
        ax.set_ylim(low-padding,high+padding);ax.set_xlim(x[0]-.5,x[-1]+.5)
        ax.grid(axis='y',color='#DCE0E2',linewidth=.6)
        ax.tick_params(axis='both',labelsize=9)
        ax.tick_params(axis='x',labelbottom=False,bottom=False)
        for spine in ('top','right'):ax.spines[spine].set_visible(False)
        ax.spines['left'].set_color('#BDC5C9');ax.spines['bottom'].set_visible(False)
        rgba=np.array([to_rgba(colors_for_states[int(c)] if c>=0 else '#222222') for c in states[:,j]])
        strip.imshow(rgba[None,:,:],extent=[x[0]-.5,x[-1]+.5,0,1],aspect='auto',interpolation='nearest')
        strip.set_yticks([])
        for spine in strip.spines.values():spine.set_visible(False)
        strip.tick_params(axis='x',labelbottom=j==panels-1,bottom=j==panels-1,labelsize=9)
        strip.xaxis.set_major_locator(mdates.MonthLocator())
        strip.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    title='前后2n窗口的日线状态标注' if centered else '日线状态划分 · 同一价格，不同参考尺度'
    if compare is not None:title='两周尺度：边界归属与短段处理对照'
    fig.suptitle(f'{asset}  {title}',fontsize=18,fontweight='bold',x=.075,ha='left',y=.975 if comparison else .985)
    weight_text='以当日为中心加权，半衰期 n/3；每天独立标注' if centered else '每天重算，越近数据权重越高，半衰期 n/3'
    fig.text(.075,.935 if comparison else .951,f'{dates[0]:%Y-%m-%d} 至 {dates[-1]:%Y-%m-%d}  |  {weight_text}',fontsize=11,color='#50595F')
    handles=[Line2D([0],[0],color=c,lw=4,label=n) for c,n in zip(colors_for_states,names_for_states)]
    if centered:handles.append(Line2D([0],[0],color='#424A52',lw=2,ls='--',label='未标注（数据不足）'))
    if compare is not None:handles.append(Line2D([0],[0],marker='o',mfc='none',mec='#20272B',ls='none',label='标签变更'))
    fig.legend(handles=handles,loc='upper left',bbox_to_anchor=(.07,.90 if comparison else .939),ncol=len(handles),frameon=False,fontsize=10,columnspacing=1.2)
    footer=('五种颜色均为历史结构类别；深灰虚线为未来数据不足的未标注区间，不是模型低置信度状态。' if centered else '线条颜色与下方色带均取自当日日标签；背景按连续状态段着色。颜色在当日收盘后可知。')
    fig.text(.075,.045 if comparison else .027,footer,fontsize=10,color='#50595F')
    fig.text(.075,.020 if comparison else .010,'初版规则用于检查分段合理性；同一尺度同一标注规则对应下一周期预测，标签不作为当时已知的交易信号。',fontsize=9,color='#6B7378')
    output.mkdir(parents=True,exist_ok=True)
    stem=output/(asset.lower()+('_2week_before_after' if compare is not None else '_daily_states'))
    fig.savefig(stem.with_suffix('.png'),dpi=180,facecolor=fig.get_facecolor())
    fig.savefig(stem.with_suffix('.svg'),facecolor=fig.get_facecolor())
    plt.close(fig)
    print(stem.with_suffix('.png'),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--assets',nargs='+',default=['BTCUSDT','ETHUSDT'])
    parser.add_argument('--days',type=int,default=210)
    parser.add_argument('--compare-to',type=Path,help='baseline dataset; compare only the two-week scale')
    parser.add_argument('--end-date',help='optional close-date cutoff for a historical detail view, YYYY-MM-DD')
    args=parser.parse_args()
    for path in ('/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
                 '/System/Library/Fonts/STHeiti Light.ttc'):
        if Path(path).exists():
            font_manager.fontManager.addfont(path)
            plt.rcParams['font.family']=font_manager.FontProperties(fname=path).get_name()
            break
    plt.rcParams['axes.unicode_minus']=False
    with np.load(args.dataset,allow_pickle=False) as data:
        if args.compare_to:
            with np.load(args.compare_to,allow_pickle=False) as baseline:
                for asset in args.assets:plot_asset(data,asset,args.output,args.days,compare=baseline,end_date=args.end_date)
        else:
            for asset in args.assets:plot_asset(data,asset,args.output,args.days,end_date=args.end_date)


if __name__=='__main__':main()
