"""Monitor training progress in real-time."""

import json
import sys
import time
from pathlib import Path

def parse_log_line(line):
    """Parse JSON log line, return None if invalid."""
    try:
        return json.loads(line.strip())
    except:
        return None

def monitor_training(root_dir: Path):
    """Monitor all training processes under root_dir."""
    print(f"Monitoring: {root_dir}")
    print("=" * 80)
    
    while True:
        # Find all train.log files
        log_files = list(root_dir.rglob("train.log"))
        
        if not log_files:
            print("No training logs found yet...")
            time.sleep(5)
            continue
        
        # Aggregate progress
        progress = []
        for log_file in log_files:
            config_name = log_file.parent.parent.name
            seed = log_file.parent.name
            
            with open(log_file) as f:
                lines = f.readlines()
            
            if not lines:
                continue
            
            # Find last valid JSON line
            last_rec = None
            for line in reversed(lines):
                rec = parse_log_line(line)
                if rec and "episode" in rec:
                    last_rec = rec
                    break
            
            if last_rec:
                progress.append({
                    "config": config_name,
                    "seed": seed,
                    "episode": last_rec["episode"],
                    "return": last_rec.get("ann_log_return", 0),
                    "drawdown": last_rec.get("p95_max_dd", 0),
                    "kl": last_rec.get("kl", 0),
                    "seconds": last_rec.get("seconds", 0),
                })
        
        # Display
        print("\033[2J\033[H")  # Clear screen
        print(f"Training Progress - {time.strftime('%H:%M:%S')}")
        print("=" * 100)
        print(f"{'Config':<25} {'Seed':<15} {'Ep':<5} {'Return':>8} {'DD':>8} {'KL':>8} {'Time/ep':>8}")
        print("-" * 100)
        
        for p in sorted(progress, key=lambda x: (x["config"], x["seed"])):
            print(f"{p['config']:<25} {p['seed']:<15} {p['episode']:<5} "
                  f"{p['return']:>8.4f} {p['drawdown']:>8.4f} {p['kl']:>8.4f} {p['seconds']:>8.1f}s")
        
        print("-" * 100)
        print(f"Total running: {len(progress)} / Expected: 32 (Stage A)")
        
        if progress:
            avg_ep = sum(p["episode"] for p in progress) / len(progress)
            print(f"Average progress: {avg_ep:.1f} / 30 episodes ({avg_ep/30*100:.1f}%)")
        
        time.sleep(10)

if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("experiments/p2_us_final_20261002_optimized")
    monitor_training(root)
