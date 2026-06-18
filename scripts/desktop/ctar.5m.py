#!/usr/bin/env python3
# <xbar.title>CTA-R 组合</xbar.title>
# <xbar.version>v1.0</xbar.version>
# <xbar.author>qount</xbar.author>
# <xbar.desc>Mac 菜单栏实时显示 CTA-R 持仓/盈亏,到点或漂移触发调仓提醒+通知。</xbar.desc>
# <xbar.dependencies>python3,ssh</xbar.dependencies>
#
# SwiftBar / xbar plugin. Pulls `qount.cta_portfolio status --json` from WSL over
# ssh (the data + engine live on WSL; the Mac is display-only) and renders the
# book in the menu bar. Turns red + fires a macOS notification (once/day) when a
# rebalance is due. Read-only; never places an order.
#
# Install:
#   brew install swiftbar           # or xbar
#   把本文件拷到 SwiftBar 插件目录(SwiftBar 偏好里设),文件名的 `5m` = 每 5 分钟刷新。
#   chmod +x ctar.5m.py
# 依赖:Mac 能 `ssh home`(已验证),WSL 上 cta_portfolio 可跑。
import json
import os
import subprocess
import sys
from datetime import date

SSH_HOST = "home"
WSL_SCRIPT = "cd ~/Code/qount && .venv/bin/python -m qount.cta_portfolio status --json\n"
NOTIFY_STAMP = os.path.expanduser("~/.cache/ctar_notify_date")


def fetch():
    r = subprocess.run(
        ["/usr/bin/ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
         "-o", "ClearAllForwardings=yes", SSH_HOST, "wsl.exe", "bash", "-s"],
        input=WSL_SCRIPT, capture_output=True, text=True, timeout=45,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "ssh failed").strip().splitlines()[-1:][0] if (r.stderr or r.stdout) else "ssh failed")
    for line in reversed(r.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError("no JSON from cta_portfolio")


def notify_once(title, body):
    today = date.today().isoformat()
    try:
        if os.path.exists(NOTIFY_STAMP) and open(NOTIFY_STAMP).read().strip() == today:
            return
        os.makedirs(os.path.dirname(NOTIFY_STAMP), exist_ok=True)
        open(NOTIFY_STAMP, "w").write(today)
    except OSError:
        pass
    subprocess.run(["/usr/bin/osascript", "-e",
                    f'display notification "{body}" with title "{title}" sound name "Glass"'],
                   capture_output=True)


def money(x):
    return f"{x:,.0f}"


def main():
    try:
        d = fetch()
    except Exception as exc:  # noqa: BLE001
        print("CTA ⚠️")
        print("---")
        print(f"取数失败: {exc}")
        print("Refresh | refresh=true")
        return

    due = d.get("due")
    day = d.get("day_pnl") or 0.0
    tot_pct = (d.get("total_pnl_pct") or 0.0) * 100
    src_live = d.get("price_source") == "sina_live"

    # --- menu bar title ---
    if due:
        print(f"🔔 CTA 调仓 | color=red")
    else:
        arrow = "▲" if day >= 0 else "▼"
        color = "green" if day >= 0 else "red"
        print(f"CTA {arrow}¥{money(abs(day))} | color={color}")

    print("---")
    print(f"总资产 ¥{money(d.get('equity',0))}" + (" | color=gray" if not src_live else ""))
    tp = d.get("total_pnl") or 0.0
    print(f"总盈亏 {'+' if tp>=0 else ''}¥{money(tp)} ({tot_pct:+.1f}%)   今日 {'+' if day>=0 else ''}¥{money(day)}")
    print(f"现金 ¥{money(d.get('cash',0))}   价格源 {'新浪实时' if src_live else '缓存收盘'}")
    print("---")
    print(f"{'ETF':<8}{'手数':>6}{'持仓股':>9}{'建仓':>8}{'收益%':>8}{'当前/目标w':>13} | font=Menlo")
    for p in sorted(d.get("positions", []), key=lambda x: -x["market_value"]):
        pct = (p.get("pnl_pct") or 0.0) * 100
        lots = round(p.get("lots", p["shares"] / 100))
        nm = p.get("name", p["symbol"])[:6]
        line = (f"{nm:<6}{lots:>5}手{round(p['shares']):>8d}{p.get('avg_cost', 0):>7.3f}{pct:>+7.1f}%"
                f"{p['weight']*100:>6.1f}/{p['target_weight']*100:>4.1f}%")
        print(f"{line} | font=Menlo color={'green' if pct>=0 else 'red'}")

    print("---")
    if due:
        reasons = " + ".join(d.get("due_reasons", []))
        print(f"🔔 需要调仓:{reasons} | color=red")
        for o in d.get("orders", []):
            tag = " *QDII" if o.get("qdii") else ""
            print(f"{o['side']} {o.get('name','')}{tag}  {o['lots']}手 @{o['limit_ref']:.3f}  ¥{money(o['amount'])} | font=Menlo")
        print("成交后在 WSL 跑 record-fill;全调完跑 mark-rebalanced | color=gray")
        notify_once("CTA-R 调仓提醒", f"{reasons};共 {len(d.get('orders',[]))} 笔。")
    else:
        print(f"✅ 暂不需调仓({d.get('trading_days_elapsed',0)}/21 交易日,"
              f"漂移 {(d.get('max_weight_drift') or 0)*100:.1f}%) | color=gray")

    print("---")
    print(f"数据 {d.get('data_date')} · 上次调仓 {d.get('last_rebalance_date')} · mode={d.get('mode')} | color=gray")
    print("立即刷新 | refresh=true")


if __name__ == "__main__":
    main()
