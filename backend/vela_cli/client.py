"""HTTP client and credential storage for vela CLI."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

DEFAULT_API_BASE = "http://127.0.0.1:8000/api/v1"
CREDENTIALS_PATH = Path.home() / ".vela" / "credentials.json"


class VelaApiError(Exception):
    def __init__(self, status_code: int, body: Any):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body}")


def get_api_base() -> str:
    return (os.environ.get("VELA_API_BASE") or DEFAULT_API_BASE).rstrip("/")


def load_token() -> str:
    env = (os.environ.get("VELA_API_TOKEN") or "").strip()
    if env:
        return env
    if CREDENTIALS_PATH.exists():
        try:
            data = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
            return str(data.get("access_token") or "").strip()
        except (OSError, json.JSONDecodeError):
            return ""
    return ""


def save_credentials(access_token: str, api_base: Optional[str] = None) -> None:
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "access_token": access_token,
        "api_base": api_base or get_api_base(),
    }
    CREDENTIALS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def clear_credentials() -> None:
    if CREDENTIALS_PATH.exists():
        CREDENTIALS_PATH.unlink()


class ApiClient:
    def __init__(self, token: Optional[str] = None, base: Optional[str] = None):
        self.base = (base or get_api_base()).rstrip("/")
        self.token = (token if token is not None else load_token()).strip()
        self._http = httpx.Client(timeout=httpx.Timeout(120.0, connect=30.0))

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _headers(self, auth: bool = True) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if auth and self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        json_body: Any = None,
        data: Any = None,
        params: Optional[Dict[str, Any]] = None,
        content_type: Optional[str] = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{self.base}{path}"
        headers = self._headers(auth=auth)
        if content_type:
            headers["Content-Type"] = content_type
        elif json_body is not None:
            headers["Content-Type"] = "application/json"
        resp = self._http.request(
            method.upper(),
            url,
            headers=headers,
            json=json_body,
            data=data,
            params=params,
        )
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            raise VelaApiError(resp.status_code, body)
        if resp.status_code == 204 or not resp.content:
            return {"ok": True}
        try:
            return resp.json()
        except Exception:
            return {"text": resp.text}

    def get(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        return self.request("POST", path, **kw)

    def put(self, path: str, **kw: Any) -> Any:
        return self.request("PUT", path, **kw)

    def patch(self, path: str, **kw: Any) -> Any:
        return self.request("PATCH", path, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        return self.request("DELETE", path, **kw)
