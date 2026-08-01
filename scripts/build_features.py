import pandas as pd
import numpy as np
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "raw")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "processed")
os.makedirs(OUT_DIR, exist_ok=True)

# 代理映射 (3x 资产 -> 1x 观测资产)
PROXY_MAP = {
    'TQQQ': 'QQQ',
    'SOXL': 'SMH',
    'FAS': 'XLF',
    'CURE': 'XLV',
    'URTY': 'IWM',
    'DRN': 'VNQ',
    'ERX': 'XLE',
    'TMF': 'TLT',
    'BIL': 'SHY'
}

def calc_robust_zscore(series, window):
    rolling_median = series.rolling(window).median()
    # MAD = median(|x - median|)
    rolling_mad = series.rolling(window).apply(lambda x: np.median(np.abs(x - np.median(x))), raw=True)
    # Prevent division by zero
    rolling_mad = np.where(rolling_mad == 0, 1e-8, rolling_mad)
    return (series - rolling_median) / (1.4826 * rolling_mad)

def calculate_technical_features(df_proxy):
    df = df_proxy.copy()
    close = df['Close']
    
    # 动量 (Momentum)
    df['return_21d'] = close.pct_change(21)
    df['return_52d'] = close.pct_change(52)
    df['return_57d'] = close.pct_change(57)
    df['return_63d'] = close.pct_change(63)
    df['return_68d'] = close.pct_change(68)
    df['return_74d'] = close.pct_change(74)
    df['return_90d'] = close.pct_change(90)
    df['return_126d'] = close.pct_change(126)
    
    # 波动率 (Volatility)
    daily_ret = close.pct_change()
    df['volatility_21d'] = daily_ret.rolling(21).std() * np.sqrt(252)
    
    # 多尺度 Robust Z-Score
    df['z_score_21d'] = calc_robust_zscore(close, 21)
    df['z_score_63d'] = calc_robust_zscore(close, 63)
    df['z_score_126d'] = calc_robust_zscore(close, 126)
    df['z_score_252d'] = calc_robust_zscore(close, 252)
    
    # 距离 200 日均线的偏离度 (Macro Trend Filter)
    df['ma_200_dist'] = close / close.rolling(200).mean() - 1.0

    
    # RSI (14 days)
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=13, adjust=False).mean()
    ema_down = down.ewm(com=13, adjust=False).mean()
    rs = ema_up / (ema_down + 1e-8)
    df['rsi_14d'] = 100 - (100 / (1 + rs))
    
    # MACD Histogram
    exp1 = close.ewm(span=12, adjust=False).mean()
    exp2 = close.ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    df['macd_hist'] = (macd - signal) / close
    
    return df

def build_features():
    print("Loading raw dataset...")
    raw_path = os.path.join(DATA_DIR, "all_assets_daily.parquet")
    if not os.path.exists(raw_path):
        print(f"Error: {raw_path} not found. Run download_ai_dataset.py first.")
        return
        
    df = pd.read_parquet(raw_path)
    # Ensure MultiIndex with 'Close' is flattened if it exists
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # 1. 提取所有宏观和观测资产数据
    macro_pivoted = df.pivot_table(index=df.index, columns='Ticker', values='Close')
    macro_pivoted.ffill(inplace=True)
    
    macro_features = pd.DataFrame(index=macro_pivoted.index)
    
    # VIX 相关特征 (恐慌斜率与速度)
    if '^VIX' in macro_pivoted.columns:
        macro_features['vix_level'] = calc_robust_zscore(macro_pivoted['^VIX'], 63)
        macro_features['vix_roc_21d'] = macro_pivoted['^VIX'].pct_change(21)
        if '^VIX3M' in macro_pivoted.columns:
            macro_features['vix_slope'] = macro_pivoted['^VIX'] - macro_pivoted['^VIX3M']
        else:
            macro_features['vix_slope'] = 0.0
            
    # TNX 相关特征 (利率与流动性)
    if '^TNX' in macro_pivoted.columns:
        macro_features['tnx_level'] = calc_robust_zscore(macro_pivoted['^TNX'], 252)
        macro_features['tnx_roc_63d'] = macro_pivoted['^TNX'].pct_change(63)
        
    # 股债相关性崩塌特征 (SPY & TLT)
    if 'SPY' in macro_pivoted.columns and 'TLT' in macro_pivoted.columns:
        spy_ret = macro_pivoted['SPY'].pct_change()
        tlt_ret = macro_pivoted['TLT'].pct_change()
        macro_features['corr_spy_tlt_63d'] = spy_ret.rolling(63).corr(tlt_ret)
    
    macro_features.fillna(0, inplace=True)
    
    print("Processing execution assets via observation proxies...")
    final_dfs = []
    
    for ticker, proxy in PROXY_MAP.items():
        print(f"Processing {ticker} (using proxy {proxy})")
        df_target = df[df['Ticker'] == ticker].copy()
        if proxy not in macro_pivoted.columns:
            print(f"Warning: Proxy {proxy} not found for {ticker}.")
            continue
            
        df_proxy = df[df['Ticker'] == proxy].copy()
        if len(df_proxy) == 0:
            continue
            
        # 计算代理的特征
        proxy_features = calculate_technical_features(df_proxy)
        
        # 将代理特征合并到目标资产的日历上
        df_target = df_target.join(proxy_features.drop(columns=['Ticker', 'Close', 'Open', 'High', 'Low', 'Volume']), rsuffix='_proxy')
        df_target = df_target.join(macro_features)
        
        # 目标资产自身的执行特征 (跳空, 真实收益, Target)
        df_target['gap_risk'] = (df_target['Open'] - df_target['Close'].shift(1)) / df_target['Close'].shift(1)
        df_target['target_fwd_return_21d'] = df_target['Close'].pct_change(21).shift(-21)
        
        df_target.dropna(subset=['target_fwd_return_21d'], inplace=True)
        final_dfs.append(df_target)
        
    final_dataset = pd.concat(final_dfs)
    final_dataset.sort_index(inplace=True)
    
    out_path = os.path.join(OUT_DIR, "ai_training_dataset.parquet")
    final_dataset.to_parquet(out_path)
    print(f"\nFinal dataset saved to {out_path}")
    print(f"Total rows: {len(final_dataset)}")
    print(f"Features: {list(final_dataset.columns)}")

if __name__ == "__main__":
    build_features()
