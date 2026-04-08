from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from src.config import load_config
from src.live_adaptive_trader import LiveAdaptivePaperTrader


def main() -> None:
    parser = argparse.ArgumentParser(description="Live adaptive paper trader (real market data, no order placement)")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--continuous", action="store_true", help="Restart the live trader after each completed run")
    parser.add_argument("--restart-delay-seconds", type=int, default=5, help="Delay before restarting in continuous mode")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    while True:
        config = load_config(str(config_path))
        config["_config_path"] = str(config_path)

        trader = LiveAdaptivePaperTrader(config)
        result = trader.run()
        print(json.dumps({"type": "FINAL", "result": result}))
        if not args.continuous:
            break
        print(
            json.dumps(
                {
                    "type": "SERVICE_RESTART",
                    "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "delay_seconds": max(1, int(args.restart_delay_seconds)),
                    "message": "Restarting live adaptive trader for continuous service",
                }
            )
        )
        time.sleep(max(1, int(args.restart_delay_seconds)))


if __name__ == "__main__":
    main()
