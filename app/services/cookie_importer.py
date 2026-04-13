import json
from pathlib import Path


class CookieImporter:
    def _parse_json(self, raw_text: str) -> list[dict]:
        payload = json.loads(raw_text)
        if isinstance(payload, dict) and "cookies" in payload:
            cookies = payload["cookies"]
        elif isinstance(payload, list):
            cookies = payload
        else:
            raise ValueError("Unsupported cookie JSON format")
        if not isinstance(cookies, list):
            raise ValueError("Cookie payload must be a list")
        return cookies

    def _parse_txt(self, raw_text: str, default_domain: str) -> list[dict]:
        cookies: list[dict] = []
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if any(line.startswith("#HttpOnly_") or "\t" in line for line in lines):
            for line in lines:
                if line.startswith("#") and not line.startswith("#HttpOnly_"):
                    continue
                http_only = line.startswith("#HttpOnly_")
                if http_only:
                    line = line.removeprefix("#HttpOnly_")
                parts = line.split("\t")
                if len(parts) != 7:
                    continue
                domain, _, path, secure, expires, name, value = parts
                cookies.append(
                    {
                        "domain": domain,
                        "path": path or "/",
                        "name": name,
                        "value": value,
                        "secure": secure.lower() == "true",
                        "httpOnly": http_only,
                        "expires": int(expires) if expires.isdigit() else -1,
                    }
                )
            return cookies

        for chunk in raw_text.replace("\n", ";").split(";"):
            if "=" not in chunk:
                continue
            name, value = chunk.split("=", 1)
            cookies.append(
                {
                    "domain": default_domain,
                    "path": "/",
                    "name": name.strip(),
                    "value": value.strip(),
                    "secure": True,
                    "httpOnly": False,
                }
            )
        return cookies

    def import_file(self, content: bytes, filename: str, default_domain: str, target_path: Path) -> Path:
        raw_text = content.decode("utf-8").strip()
        suffix = Path(filename).suffix.lower()
        if suffix == ".json" or raw_text.startswith("{") or raw_text.startswith("["):
            cookies = self._parse_json(raw_text)
        else:
            cookies = self._parse_txt(raw_text, default_domain=default_domain)

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps({"cookies": cookies, "origins": []}, indent=2), encoding="utf-8")
        return target_path


cookie_importer = CookieImporter()
