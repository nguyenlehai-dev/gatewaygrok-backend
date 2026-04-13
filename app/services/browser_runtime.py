import socket
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
