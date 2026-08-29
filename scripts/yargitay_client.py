"""Small HTTP client for the public Yargitay decision search endpoints."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from http.cookiejar import CookieJar
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener


BASE_URL = "https://karararama.yargitay.gov.tr"
NETWORK_ERRORS = (HTTPError, URLError, TimeoutError, ConnectionError, OSError)


class YargitayClientError(RuntimeError):
    """Raised when an endpoint cannot be reached or returns invalid data."""


@dataclass(slots=True)
class YargitayClient:
    base_url: str = BASE_URL
    timeout: float = 30.0
    _opener: Any = field(init=False, repr=False)
    _session_ready: bool = field(init=False, default=False, repr=False)
    _search_signature: str | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.reset_session()

    def reset_session(self) -> None:
        """Discard cookies and prepared-search state before a retry."""
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self._session_ready = False
        self._search_signature = None

    def list_decisions(
        self,
        *,
        start_date: str,
        end_date: str,
        page_number: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        if page_number < 1:
            raise ValueError("page_number must be at least 1")
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")

        payload = {
            "arananKelime": "",
            "baslangicTarihi": start_date,
            "birimYrgCezaDaire": "",
            "birimYrgHukukDaire": "",
            "birimYrgKurulDaire": "",
            "bitisTarihi": end_date,
            "esasIlkSiraNo": "",
            "esasSonSiraNo": "",
            "esasYil": "",
            "kararIlkSiraNo": "",
            "kararSonSiraNo": "",
            "kararYil": "",
            "pageNumber": page_number,
            "pageSize": page_size,
            "siralama": "3",
            "siralamaDirection": "desc",
        }
        search_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"pageNumber", "pageSize"}
        }
        self._prepare_search(search_payload)
        return self._request_json(
            "/aramadetaylist",
            method="POST",
            body=json.dumps({"data": payload}, ensure_ascii=False).encode("utf-8"),
        )

    def get_decision(self, decision_id: str) -> dict[str, Any]:
        if not decision_id.strip():
            raise ValueError("decision_id cannot be empty")
        query = urlencode({"id": decision_id})
        return self._request_json(f"/getDokuman?{query}")

    def _request_json(
        self, path: str, *, method: str = "GET", body: bytes | None = None
    ) -> dict[str, Any]:
        if not self._session_ready:
            self._start_session()
        request = Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "Origin": self.base_url.rstrip("/"),
                "Referer": f"{self.base_url.rstrip('/')}/",
                "User-Agent": "Mozilla/5.0 yargitay-rag-staj-projesi/0.1",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                status = getattr(response, "status", 200)
                raw = response.read()
        except NETWORK_ERRORS as exc:
            raise YargitayClientError(f"Yargitay request failed: {exc}") from exc

        if status != 200:
            raise YargitayClientError(f"Unexpected HTTP status: {status}")
        try:
            # ``utf-8-sig`` remains strict UTF-8 while also accepting an optional
            # byte-order mark that some HTTP intermediaries may prepend.
            result = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise YargitayClientError("Response is not valid UTF-8 JSON") from exc
        if not isinstance(result, dict):
            raise YargitayClientError("Response root must be a JSON object")
        metadata = result.get("metadata")
        if result.get("data") is None and isinstance(metadata, dict):
            code = metadata.get("FMC", "UNKNOWN_SERVICE_ERROR")
            message = metadata.get("FMTE", "No error message")
            raise YargitayClientError(f"Yargitay service error {code}: {message}")
        return result

    def _prepare_search(self, payload: dict[str, Any]) -> None:
        signature = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if self._search_signature == signature:
            return
        if not self._session_ready:
            self._start_session()
        request = Request(
            f"{self.base_url.rstrip('/')}/detayliArama",
            data=json.dumps({"data": payload}, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "text/html, */*; q=0.01",
                "Content-Type": "application/json; charset=utf-8",
                "Origin": self.base_url.rstrip("/"),
                "Referer": f"{self.base_url.rstrip('/')}/",
                "User-Agent": "Mozilla/5.0 yargitay-rag-staj-projesi/0.1",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                status = getattr(response, "status", 200)
                raw = response.read()
        except NETWORK_ERRORS as exc:
            raise YargitayClientError(f"Could not prepare Yargitay search: {exc}") from exc
        if status != 200:
            raise YargitayClientError(f"Search preparation returned HTTP {status}")
        if not raw.strip():
            raise YargitayClientError("Search preparation returned an empty response")
        self._search_signature = signature

    def _start_session(self) -> None:
        request = Request(
            f"{self.base_url.rstrip('/')}/",
            headers={"User-Agent": "Mozilla/5.0 yargitay-rag-staj-projesi/0.1"},
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                response.read()
        except NETWORK_ERRORS as exc:
            raise YargitayClientError(f"Could not start Yargitay session: {exc}") from exc
        self._session_ready = True
