#!/usr/bin/env python3
"""Exit successfully only when all application and persistence checks pass."""
import argparse
import json
import time
from urllib.request import urlopen


def check(payload):
    return all(payload.get(key, {}).get("status") == "ok" for key in ("storage", "workspace")) and payload.get("status") == "ok"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8780/api/health")
    parser.add_argument("--attempts", type=int, default=30)
    args = parser.parse_args()
    for attempt in range(args.attempts):
        try:
            with urlopen(args.url, timeout=3) as response:
                if response.status == 200 and check(json.load(response)):
                    print("CollectStarInfo health: ok")
                    return 0
        except Exception:
            # Health error bodies can contain storage connection details.
            pass
        if attempt + 1 < args.attempts:
            time.sleep(1)
    print("CollectStarInfo health failed; inspect sanitized service diagnostics.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
