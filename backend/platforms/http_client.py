"""
HTTP-клиент с TLS-impersonation (curl_cffi) и fallback на httpx.

Использовать на HTTP-first платформах до браузера.
Вкл/выкл: CURL_CFFI_ENABLED=true|false (по умолчанию true).
Impersonate: CURL_CFFI_IMPERSONATE=chrome (или chrome131, safari, …).
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any


def curl_cffi_enabled() -> bool:
    raw = (os.environ.get("CURL_CFFI_ENABLED") or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _impersonate() -> str:
    return (os.environ.get("CURL_CFFI_IMPERSONATE") or "chrome").strip() or "chrome"


class HttpResponse:
    """Минимальный контракт как у httpx.Response (status_code / text / json / raise_for_status)."""

    def __init__(
        self,
        *,
        status_code: int,
        text: str,
        headers: dict[str, str] | None = None,
        url: str = "",
    ) -> None:
        self.status_code = int(status_code)
        self.text = text or ""
        self.content = self.text.encode("utf-8", errors="replace")
        self.headers = headers or {}
        self.url = url

    def json(self) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code} for {self.url}")


class HttpClient:
    def __init__(
        self,
        *,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = True,
        timeout: float = 20.0,
    ) -> None:
        self._headers = dict(headers or {})
        self._follow = follow_redirects
        self._timeout = float(timeout)
        self._backend = "httpx"
        self._session: Any = None
        self._close = None

        if curl_cffi_enabled():
            try:
                from curl_cffi import requests as crequests

                self._session = crequests.Session(impersonate=_impersonate())
                self._backend = "curl_cffi"
                self._close = self._session.close
            except Exception as exc:
                print(
                    f"[http_client] curl_cffi недоступен ({exc}), fallback → httpx",
                    file=sys.stderr,
                )

        if self._session is None:
            import httpx

            self._session = httpx.Client(
                headers=self._headers,
                follow_redirects=self._follow,
                timeout=self._timeout,
            )
            self._backend = "httpx"
            self._close = self._session.close

    @property
    def backend(self) -> str:
        return self._backend

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        if self._close:
            try:
                self._close()
            except Exception:
                pass
            self._close = None

    def get(self, url: str, *, params: dict | None = None, headers: dict | None = None, timeout: float | None = None) -> HttpResponse:
        return self.request("GET", url, params=params, headers=headers, timeout=timeout)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        timeout: float | None = None,
        json_body: Any = None,
    ) -> HttpResponse:
        merged = {**self._headers, **(headers or {})}
        to = self._timeout if timeout is None else float(timeout)
        if self._backend == "curl_cffi":
            r = self._session.request(
                method.upper(),
                url,
                params=params,
                headers=merged or None,
                timeout=to,
                allow_redirects=self._follow,
                json=json_body,
            )
            hdrs = {str(k): str(v) for k, v in dict(getattr(r, "headers", {}) or {}).items()}
            return HttpResponse(
                status_code=int(getattr(r, "status_code", 0) or 0),
                text=getattr(r, "text", "") or "",
                headers=hdrs,
                url=str(getattr(r, "url", url) or url),
            )

        kw: dict[str, Any] = {
            "params": params,
            "headers": merged or None,
            "timeout": to,
        }
        if json_body is not None:
            kw["json"] = json_body
        r = self._session.request(method.upper(), url, **kw)
        hdrs = {str(k): str(v) for k, v in dict(r.headers).items()}
        return HttpResponse(
            status_code=int(r.status_code),
            text=r.text or "",
            headers=hdrs,
            url=str(r.url),
        )


def get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    follow_redirects: bool = True,
    params: dict | None = None,
) -> HttpResponse:
    with HttpClient(headers=headers, follow_redirects=follow_redirects, timeout=timeout) as client:
        return client.get(url, params=params)
