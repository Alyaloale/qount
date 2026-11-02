"""Show the three label architectures and their independent path attributes."""
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
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--assets',nargs='+',default=['BTCUSDT','ETHUSDT'])
    parser.add_argument('--days',type=int,default=210)
    args=parser.parse_args()
    for path in ('/System/Library/Fonts/Supplemental/Arial Unicode.ttf','/System/Library/Fonts/STHeiti Light.ttc'):
        if Path(path).exists():
            font_manager.fontManager.addfont(path)
            plt.rcParams['font.family']=font_manager.FontProperties(fname=path).get_name();break
    plt.rcParams['axes.unicode_minus']=False
    with np.load(args.dataset,allow_pickle=False) as z:d={k:z[k] for k in z.files}
    args.output.mkdir(parents=True,exist_ok=True)
    palette=('#D84A4A','#148B6A','#3979BD','#9365BD','#8C969E')
    for asset in args.assets:
        rows=np.flatnonzero(d['asset']==asset);clock=d['known_at'][rows]-60000
        keep=clock>=clock.max()-args.days*86400000;rows=rows[keep];clock=clock[keep]
        adjust=1 if d['group'][rows[0]]=='crypto' else 0
        dates=[dt.datetime.fromtimestamp(int(t)/1000-adjust,dt.timezone.utc) for t in clock]
        x=mdates.date2num(dates);price=d['ohlcv'][rows,3]
        fig,axes=plt.subplots(6,1,figsize=(14,15),sharex=True,
            gridspec_kw=dict(height_ratios=[2.3,2.3,2.3,1,1,1],hspace=.42))
        fig.set_facecolor('#FAFAF7');fig.subplots_adjust(left=.075,right=.97,top=.875,bottom=.07)
        names=('A 五类：当前修正版','B 三类：直接合并非方向类别','C 三类：方向与属性分开')
        for ax,name,key in zip(axes[:3],names,('state5','merged_three','factored_three')):
            labels=d[key][rows];points=np.c_[x,price]
            segments=np.stack((points[:-1],points[1:]),axis=1)
            colors=[palette[c] if c>=0 else '#424A52' for c in labels[1:]]
            ax.plot(x,price,lw=.6,c='#60686D',alpha=.5)
            ax.add_collection(LineCollection(segments,colors=colors,linewidths=2,
                linestyles=['solid' if c>=0 else 'dashed' for c in labels[1:]]))
            start=0
            for end in range(1,len(rows)+1):
                if end<len(rows) and labels[end]==labels[start]:continue
                c=labels[start]
                ax.axvspan(x[start]-.5,x[end-1]+.5,color=palette[c] if c>=0 else '#424A52',alpha=.06,lw=0)
                start=end
            pad=(price.max()-price.min())*.08
            ax.set_ylim(price.min()-pad,price.max()+pad);ax.set_ylabel('USDT')
            ax.set_title(name,loc='left',fontsize=12,pad=7)
        attr=d['attributes'][rows]
        axes[3].plot(x,attr[:,0],c='#9365BD',lw=1.4)
        axes[3].axhline(.65,c='#454D52',lw=.9,ls='--')
        axes[3].fill_between(x,0,attr[:,0],where=attr[:,1]==1,color='#9365BD',alpha=.25)
        axes[3].set_ylabel('振幅比');axes[3].set_title('独立属性：收缩比（紫色填充为≤0.65，可与上行/下行共存）',loc='left',fontsize=10)
        axes[4].plot(x,attr[:,2]*100,c='#D79B25',lw=1.4);axes[4].set_ylabel('日波动 %')
        axes[4].set_title('独立属性：加权日收益波动率',loc='left',fontsize=10)
        axes[5].plot(x,attr[:,3],c='#3979BD',lw=1.4);axes[5].set_ylim(0,1);axes[5].set_ylabel('路径效率')
        axes[5].set_title('独立属性：整段净位移 / 总收盘路径长度',loc='left',fontsize=10)
        for ax in axes:
            ax.set_xlim(x[0]-.5,x[-1]+.5);ax.grid(axis='y',c='#DBE1E4',lw=.6)
            ax.tick_params(labelsize=9);ax.set_facecolor('white')
            for side in ('top','right'):ax.spines[side].set_visible(False)
            ax.spines['left'].set_color('#BDC5C9');ax.spines['bottom'].set_color('#BDC5C9')
        axes[-1].xaxis.set_major_locator(mdates.MonthLocator());axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        n=int(d['horizon'][rows[0]])
        fig.suptitle(f'{asset}  五类与三类主状态＋独立属性',x=.075,ha='left',y=.985,fontsize=18)
        fig.text(.075,.951,f'{dates[0]:%Y-%m-%d} 至 {dates[-1]:%Y-%m-%d}  |  同一日线、n={n}，前后合计2n根事后标注',fontsize=11,c='#50595F')
        handles=[Line2D([0],[0],c=c,lw=3,label=n) for c,n in zip(palette,('上行','下行','轮动 / 震荡','收缩（五类）','低效率（五类）'))]
        handles.append(Line2D([0],[0],c='#424A52',ls='--',lw=2,label='未标注'))
        fig.legend(handles=handles,bbox_to_anchor=(.07,.938),loc='upper left',ncol=6,frameon=False,fontsize=10)
        fig.text(.075,.022,'曲线颜色与属性均为历史标签，不是模型预测；尾部缺少未来n根而未标注。独立属性不代表统计独立或已获交易优势。',fontsize=10,c='#50595F')
        path=args.output/(asset.lower()+'_factorization')
        fig.savefig(path.with_suffix('.png'),dpi=170,facecolor=fig.get_facecolor())
        fig.savefig(path.with_suffix('.svg'),facecolor=fig.get_facecolor());plt.close(fig)
        print(path.with_suffix('.png'),flush=True)


if __name__=='__main__':main()
