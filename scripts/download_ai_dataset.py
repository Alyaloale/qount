import yfinance as yf
import pandas as pd
import os
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "raw")
os.makedirs(DATA_DIR, exist_ok=True)

# 1. 进攻执行资产 (3x ETFs)
OFFENSIVE_TICKERS = ['TQQQ', 'SOXL', 'FAS', 'CURE', 'URTY', 'DRN', 'ERX']

# 2. 防守执行资产 (Treasury & Cash)
DEFENSIVE_TICKERS = ['TMF', 'BIL']

# 3. 观测资产 (1x Underlying, Macro, VIX curve, etc.)
OBSERVATION_TICKERS = [
    'QQQ', 'SMH', 'XLF', 'XLV', 'IWM', 'VNQ', 'XLE', # 1x Proxies for the 3x ETFs
    'SPY', 'TLT', 'SHY',                             # Broad Market & Treasuries
    'GLD', 'USO', 'UUP',                             # Commodities & Dollar
    '^VIX', '^VIX3M', '^TNX'                         # VIX term structure and 10yr yield
]

ALL_TICKERS = OFFENSIVE_TICKERS + DEFENSIVE_TICKERS + OBSERVATION_TICKERS

def download_data():
    print(f"Starting data download for {len(ALL_TICKERS)} tickers...")
    print(f"Tickers: {ALL_TICKERS}")
    
    combined_dfs = {}
    
    for ticker in ALL_TICKERS:
        print(f"Fetching {ticker}...")
        success = False
        retries = 60
        # Create a custom session to spoof User-Agent and bypass Yahoo rate limits
        import requests
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
        })
        
        while not success and retries > 0:
            try:
                # 使用带自定义 User-Agent 的 session，如果有本地环境变量代理 requests 也会自动接管
                df = yf.download(ticker, period="max", auto_adjust=True, progress=False, session=session)
                
                if df.empty:
                    raise Exception("Empty dataframe returned (likely rate limited).")
                    
                df.dropna(how='all', inplace=True)
                
                # yfinance >= 0.2.0 returns MultiIndex (Price, Ticker) even for single tickers. 
                # We MUST flatten it BEFORE assigning df['Ticker'] and concatenating!
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                    
                success = True
                time.sleep(3)
                
            except Exception as e:
                print(f"Error fetching {ticker}: {e}. Retrying in 10s...")
                time.sleep(10)
                retries -= 1
                
        if not success:
            print(f"Failed to fetch {ticker} after retries.")
            continue
                
        # 添加 Ticker 标识列
        df['Ticker'] = ticker
        combined_dfs[ticker] = df
        print(f"[{ticker}] Saved {len(df)} rows. Range: {df.index.min().date()} to {df.index.max().date()}")

    if not combined_dfs:
        print("Error: No data downloaded at all.")
        return

    # 合并所有数据
    final_df = pd.concat(combined_dfs.values())
    
    # 保存为 parquet 格式
    out_path = os.path.join(DATA_DIR, "all_assets_daily.parquet")
    final_df.to_parquet(out_path)
    print(f"\nAll data combined and saved to {out_path}")
    print(f"Total rows across all tickers: {len(final_df)}")

if __name__ == "__main__":
    download_data()
