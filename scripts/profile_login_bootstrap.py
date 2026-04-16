import argparse
import os
import signal
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
    parser = argparse.ArgumentParser(description="Launch an interactive login browser for a profile.")
    parser.add_argument("--profile-id", required=True)
    return parser.parse_args()


def _terminate_process(proc):
    if not proc or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _handle_signal(signum, _frame):
    raise SystemExit(f"received signal {signum}")


def _cleanup_stale_display_lock(display: str) -> None:
    display_number = display.removeprefix(":")
    lock_path = Path(f"/tmp/.X{display_number}-lock")
    socket_path = Path(f"/tmp/.X11-unix/X{display_number}")
    result = subprocess.run(["pgrep", "-f", f"Xvfb {display}"], capture_output=True, text=True, check=False)
    if result.returncode == 0 and result.stdout.strip():
        return
    for candidate in (lock_path, socket_path):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass
        except IsADirectoryError:
            pass


def main(profile_id: str):
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
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

        executable = resolve_browser_executable()
        if executable is None:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                executable = p.chromium.executable_path

        debug_port = debug_port_for_profile(profile_id)
        profile_dir = Path(profile.user_data_dir).resolve()
        for lock_path in profile_dir.glob("Singleton*"):
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
        try:
            for tmp_lock in Path("/tmp").glob(".org.chromium.Chromium.*"):
                if tmp_lock.is_dir():
                    for child in tmp_lock.iterdir():
                        try:
                            if child.is_file() or child.is_symlink():
                                child.unlink()
                        except FileNotFoundError:
                            pass
                    try:
                        tmp_lock.rmdir()
                    except OSError:
                        pass
        except FileNotFoundError:
            pass

        args = [
            executable,
            f"--user-data-dir={profile_dir}",
            "--new-window",
            "--start-maximized",
            "--no-first-run",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            f"--remote-debugging-port={debug_port}",
            provider.start_url,
        ]

        if profile.proxy and profile.proxy.enabled:
            args.append(f"--proxy-server={profile.proxy.kind}://{profile.proxy.server}:{profile.proxy.port}")

    print(f"Interactive login opened for profile {profile_id} at {provider.start_url}")
    print(f"Browser executable: {executable}")
    print(f"Remote debugging port: {debug_port}")
    print("Complete login/security verification manually, then close the browser window.")
    xvfb_proc = None
    vnc_proc = None
    proc = None
    env = os.environ.copy()
    if not env.get("DISPLAY"):
        display = env.get("GATEWAY_XVFB_DISPLAY", ":99")
        enable_vnc = env.get("GATEWAY_ENABLE_VNC", "true").lower() == "true"
        vnc_port = env.get("GATEWAY_VNC_PORT", "5901")
        vnc_password = env.get("GATEWAY_VNC_PASSWORD", "")
        _cleanup_stale_display_lock(display)
        xvfb_proc = subprocess.Popen(  # noqa: S603
            ["Xvfb", display, "-screen", "0", "1280x720x24"],
            cwd=ROOT_DIR,
        )
        display_number = display.removeprefix(":")
        socket_path = Path(f"/tmp/.X11-unix/X{display_number}")
        for _ in range(20):
            if socket_path.exists():
                break
            time.sleep(0.25)
        if enable_vnc:
            vnc_args = ["x11vnc", "-display", display, "-rfbport", vnc_port, "-forever", "-shared"]
            if vnc_password:
                vnc_args += ["-passwd", vnc_password]
            else:
                vnc_args.append("-nopw")
            vnc_proc = subprocess.Popen(vnc_args, cwd=ROOT_DIR)  # noqa: S603
        env["DISPLAY"] = display

    try:
        proc = subprocess.Popen(args, cwd=ROOT_DIR, env=env)  # noqa: S603
        proc.wait()
    finally:
        for child in (proc, vnc_proc, xvfb_proc):
            _terminate_process(child)


if __name__ == "__main__":
    parsed = parse_args()
    main(parsed.profile_id)
