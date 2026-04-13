import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.browser_runtime import is_debug_port_open


def parse_args():
    parser = argparse.ArgumentParser(description="Keep an interactive login browser alive for a profile.")
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--interval", type=float, default=15.0)
    return parser.parse_args()


def main(profile_id: str, interval: float):
    script_path = ROOT_DIR / "scripts" / "profile_login_bootstrap.py"
    log_path = ROOT_DIR / "storage" / f"watchdog-{profile_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    child = None

    print(f"[watchdog] starting for profile {profile_id} with interval={interval}s", flush=True)
    while True:
        if child is not None and child.poll() is not None:
            print(f"[watchdog] browser launcher exited with code {child.returncode}", flush=True)
            child = None

        if child is None and not is_debug_port_open(profile_id):
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\n[watchdog] relaunch requested at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                handle.flush()
                child = subprocess.Popen(  # noqa: S603
                    [sys.executable, str(script_path), "--profile-id", profile_id],
                    cwd=ROOT_DIR,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                )
            print(f"[watchdog] launched browser bootstrap pid={child.pid}", flush=True)

        time.sleep(interval)


if __name__ == "__main__":
    parsed = parse_args()
    main(parsed.profile_id, parsed.interval)
