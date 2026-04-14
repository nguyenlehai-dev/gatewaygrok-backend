import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy.orm import joinedload

from app.db.session import SessionLocal
from app.models.profile import Profile
from app.services.automation.registry import get_provider
from app.services.browser_runtime import debug_port_for_profile, resolve_browser_executable


def parse_args():
    parser = argparse.ArgumentParser(description="Keep a profile browser running without VNC for automation.")
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--url", default=None, help="Optional start URL override")
    return parser.parse_args()


def _browser_processes_for_user_data_dir(user_data_dir: Path) -> list[str]:
    try:
        result = subprocess.run(  # noqa: S603
            ["pgrep", "-af", str(user_data_dir.resolve())],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []

    if result.returncode not in (0, 1):
        return []

    lines = []
    for line in result.stdout.splitlines():
        if "chrome-linux/chrome" not in line:
            continue
        if "--user-data-dir=" not in line:
            continue
        lines.append(line)
    return lines


def _xvfb_running(display: str) -> bool:
    try:
        result = subprocess.run(  # noqa: S603
            ["pgrep", "-af", f"Xvfb {display}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def main(profile_id: str, start_url_override: str | None):
    with SessionLocal() as db:
        profile = (
            db.query(Profile)
            .options(joinedload(Profile.proxy))
            .filter(Profile.id == profile_id)
            .first()
        )
        if not profile:
            raise SystemExit(f"Profile not found: {profile_id}")

        provider = get_provider(profile.category)
        if provider is None:
            raise SystemExit(f"Provider not found for category: {profile.category.value}")

        user_data_dir = Path(profile.user_data_dir).resolve()
        start_url = start_url_override or provider.start_url

        executable = resolve_browser_executable()
        if executable is None:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                executable = p.chromium.executable_path

        debug_port = debug_port_for_profile(profile_id)
        args = [
            executable,
            f"--user-data-dir={user_data_dir}",
            "--new-window",
            "--start-maximized",
            "--no-first-run",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-gpu",
            "--enable-unsafe-swiftshader",
            "--use-angle=swiftshader",
            f"--remote-debugging-port={debug_port}",
            start_url,
        ]

        if profile.proxy and profile.proxy.enabled:
            args.append(f"--proxy-server={profile.proxy.kind}://{profile.proxy.server}:{profile.proxy.port}")

    print(f"Runtime browser opened for profile {profile_id} at {start_url}")
    print(f"Browser executable: {executable}")
    print(f"Remote debugging port: {debug_port}")
    print("No VNC attached. Browser will stay alive for automation while the profile session remains open.")

    xvfb_proc = None
    env = os.environ.copy()
    if not env.get("DISPLAY"):
        display = env.get("GATEWAY_XVFB_DISPLAY", ":99")
        if not _xvfb_running(display):
            lock_path = Path(f"/tmp/.X{display.lstrip(':')}-lock")
            socket_path = Path(f"/tmp/.X11-unix/X{display.lstrip(':')}")
            if lock_path.exists():
                lock_path.unlink()
            if socket_path.exists():
                socket_path.unlink()
            xvfb_proc = subprocess.Popen(  # noqa: S603
                ["Xvfb", display, "-screen", "0", "1280x720x24"],
                cwd=ROOT_DIR,
            )
            time.sleep(1.0)
        env["DISPLAY"] = display

    try:
        proc = subprocess.Popen(args, cwd=ROOT_DIR, env=env)  # noqa: S603
        proc.wait()
        while _browser_processes_for_user_data_dir(user_data_dir):
            time.sleep(1.0)
    finally:
        if xvfb_proc and xvfb_proc.poll() is None:
            xvfb_proc.terminate()


if __name__ == "__main__":
    parsed = parse_args()
    main(parsed.profile_id, parsed.url)
