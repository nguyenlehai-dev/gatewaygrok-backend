import shutil
from pathlib import Path

from app.core.config import settings


class ProfileStorageService:
    def prepare(self, profile_id: str) -> dict[str, str]:
        root = settings.profiles_root / profile_id
        cookie_dir = root / "cookies"
        cache_dir = root / "cache"
        asset_dir = root / "assets"
        user_data_dir = root / "user-data"
        output_dir = root / "output"
        for path in (cookie_dir, cache_dir, asset_dir, user_data_dir, output_dir):
            path.mkdir(parents=True, exist_ok=True)
        return {
            "root": str(root),
            "cookie_dir": str(cookie_dir),
            "cache_dir": str(cache_dir),
            "asset_dir": str(asset_dir),
            "user_data_dir": str(user_data_dir),
            "output_dir": str(output_dir),
        }

    def cookie_state_path(self, profile_id: str) -> Path:
        paths = self.prepare(profile_id)
        return Path(paths["cookie_dir"]) / "storage_state.json"

    def output_dir(self, profile_id: str) -> Path:
        return Path(self.prepare(profile_id)["output_dir"])

    def asset_dir(self, profile_id: str) -> Path:
        return Path(self.prepare(profile_id)["asset_dir"])

    def delete(self, profile_id: str) -> None:
        root = settings.profiles_root / profile_id
        if root.exists():
            shutil.rmtree(root)


profile_storage = ProfileStorageService()
