import os
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path


def resolve_browser_executable() -> str | None:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def debug_port_for_profile(profile_id: str) -> int:
    try:
        profile_value = uuid.UUID(profile_id).int
    except ValueError:
        profile_value = sum(ord(char) for char in profile_id)
    return 40000 + (profile_value % 20000)


def debug_endpoint_for_profile(profile_id: str) -> str:
    return f"http://127.0.0.1:{debug_port_for_profile(profile_id)}"


def is_debug_port_open(profile_id: str) -> bool:
    port = debug_port_for_profile(profile_id)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


ROOT_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = ROOT_DIR / "storage" / "runtime"
_SCHEDULED_STOPS: dict[str, threading.Timer] = {}
_SCHEDULED_STOPS_LOCK = threading.Lock()


def _profile_browser_pid_path(profile_id: str) -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    return RUNTIME_DIR / f"profile-browser-{profile_id}.pid"


def _profile_browser_log_path(profile_id: str) -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    return RUNTIME_DIR / f"profile-browser-{profile_id}.log"


def warm_browser_reuse_enabled() -> bool:
    value = os.getenv("GATEWAY_WARM_BROWSER_REUSE_FOR_JOBS", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def live_browser_idle_timeout_seconds() -> int:
    raw_value = os.getenv("GATEWAY_WARM_BROWSER_IDLE_TIMEOUT_SECONDS", "600").strip()
    try:
        timeout_seconds = int(raw_value)
    except ValueError:
        timeout_seconds = 600
    return max(timeout_seconds, 15)


def cancel_scheduled_profile_browser_stop(profile_id: str) -> bool:
    with _SCHEDULED_STOPS_LOCK:
        timer = _SCHEDULED_STOPS.pop(profile_id, None)
    if timer is None:
        return False
    timer.cancel()
    return True


def schedule_profile_browser_stop(profile_id: str, delay_seconds: int | None = None) -> int:
    timeout_seconds = delay_seconds if delay_seconds is not None else live_browser_idle_timeout_seconds()
    timeout_seconds = max(int(timeout_seconds), 1)

    def _stop() -> None:
        try:
            stop_profile_browser(profile_id)
        finally:
            with _SCHEDULED_STOPS_LOCK:
                _SCHEDULED_STOPS.pop(profile_id, None)

    cancel_scheduled_profile_browser_stop(profile_id)
    timer = threading.Timer(timeout_seconds, _stop)
    timer.daemon = True
    with _SCHEDULED_STOPS_LOCK:
        _SCHEDULED_STOPS[profile_id] = timer
    timer.start()
    return timeout_seconds


def launch_profile_browser(profile_id: str) -> bool:
    cancel_scheduled_profile_browser_stop(profile_id)
    if is_debug_port_open(profile_id):
        return False

    pid_path = _profile_browser_pid_path(profile_id)
    if pid_path.exists():
        try:
            existing_pid = int(pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            existing_pid = 0
        if existing_pid:
            try:
                os.kill(existing_pid, 0)
                return False
            except OSError:
                pid_path.unlink(missing_ok=True)

    script_path = ROOT_DIR / "scripts" / "profile_login_bootstrap.py"
    log_path = _profile_browser_log_path(profile_id)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n[launcher] starting on-demand browser for {profile_id} at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        handle.flush()
        env = os.environ.copy()
        env["GATEWAY_ENABLE_VNC"] = "false"
        proc = subprocess.Popen(
            [sys.executable, str(script_path), "--profile-id", profile_id],
            cwd=ROOT_DIR,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    pid_path.write_text(str(proc.pid), encoding="utf-8")
    return True


def wait_for_debug_port(profile_id: str, timeout_seconds: float = 20.0, interval_seconds: float = 0.5) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if is_debug_port_open(profile_id):
            return True
        time.sleep(interval_seconds)
    return is_debug_port_open(profile_id)


def stop_profile_browser(profile_id: str) -> bool:
    cancel_scheduled_profile_browser_stop(profile_id)
    pid_path = _profile_browser_pid_path(profile_id)
    pid = 0
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = 0

    stopped = False
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            stopped = True
        except OSError:
            pass
        for _ in range(20):
            if not is_debug_port_open(profile_id):
                break
            time.sleep(0.25)
        pid_path.unlink(missing_ok=True)

    if is_debug_port_open(profile_id):
        subprocess.run(["pkill", "-f", f"chrome --user-data-dir=/app/storage/profiles/{profile_id}/user-data"], check=False)
        time.sleep(1.0)
        stopped = True
    return stopped
