import argparse
import subprocess
import sys
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

def main(profile_id: str):
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
        args = [
            executable,
            f"--user-data-dir={Path(profile.user_data_dir).resolve()}",
            "--new-window",
            "--start-maximized",
            "--no-first-run",
            "--disable-dev-shm-usage",
            f"--remote-debugging-port={debug_port}",
            provider.start_url,
        ]

        if profile.proxy and profile.proxy.enabled:
            args.append(f"--proxy-server={profile.proxy.kind}://{profile.proxy.server}:{profile.proxy.port}")

    print(f"Interactive login opened for profile {profile_id} at {provider.start_url}")
    print(f"Browser executable: {executable}")
    print(f"Remote debugging port: {debug_port}")
    print("Complete login/security verification manually, then close the browser window.")
    proc = subprocess.Popen(args, cwd=ROOT_DIR)  # noqa: S603
    proc.wait()


if __name__ == "__main__":
    parsed = parse_args()
    main(parsed.profile_id)
