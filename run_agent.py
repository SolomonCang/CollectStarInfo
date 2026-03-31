from pathlib import Path
import sys
from datetime import datetime
import time

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> None:
    start_time = time.perf_counter()
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[run_agent] Start at {started_at}")

    from astro_agent.cli import main as cli_main

    try:
        print("[run_agent] Initializing CLI workflow...")
        cli_main()
        elapsed = time.perf_counter() - start_time
        print(f"[run_agent] Completed successfully in {elapsed:.2f}s")
    except KeyboardInterrupt:
        elapsed = time.perf_counter() - start_time
        print(f"[run_agent] Interrupted by user after {elapsed:.2f}s")
        raise
    except Exception as exc:
        elapsed = time.perf_counter() - start_time
        print(f"[run_agent] Failed after {elapsed:.2f}s: {exc}")
        raise


if __name__ == "__main__":
    main()
