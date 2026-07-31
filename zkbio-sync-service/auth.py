"""JWT authentication and authenticated HTTP requests for ZKBioTime."""

from typing import Any
from urllib.parse import urljoin

import requests


class ZKBioClient:
    """A small ZKBioTime HTTP client with in-memory JWT handling."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout: float = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.username = username
        self.password = password
        self.timeout = timeout
        self.token: str | None = None
        self.session = requests.Session()

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        return urljoin(self.base_url, path_or_url.lstrip("/"))

    def get_token(self, timeout: float | None = None) -> str:
        """Return the cached JWT, requesting one when necessary."""
        if self.token is not None:
            return self.token

        response = self.session.post(
            self._url("/jwt-api-token-auth/"),
            json={
                "username": self.username,
                "password": self.password,
            },
            timeout=self.timeout if timeout is None else timeout,
        )
        response.raise_for_status()

        try:
            payload: Any = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            content_type = response.headers.get("Content-Type", "unknown")
            preview = " ".join(response.text.split())[:240]
            detail = f": {preview}" if preview else ""
            raise ValueError(
                "ZKBioTime authentication service returned a non-JSON "
                f"response (HTTP {response.status_code}, {content_type})"
                f"{detail}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError("ZKBioTime authentication returned invalid JSON")

        token = payload.get("token") or payload.get("access")
        if not isinstance(token, str) or not token:
            raise ValueError("ZKBioTime authentication response did not contain a JWT")

        self.token = token
        return token

    def request(self, method: str, path_or_url: str, **kwargs: Any) -> requests.Response:
        """Make an authenticated request, refreshing the JWT once after a 401."""
        base_headers = dict(kwargs.pop("headers", {}))
        timeout = kwargs.pop("timeout", self.timeout)
        headers = {
            **base_headers,
            "Authorization": f"Bearer {self.get_token()}",
        }

        response = self.session.request(
            method,
            self._url(path_or_url),
            headers=headers,
            timeout=timeout,
            **kwargs,
        )

        if response.status_code == 401:
            self.token = None
            retry_headers = {
                **base_headers,
                "Authorization": f"Bearer {self.get_token()}",
            }
            response = self.session.request(
                method,
                self._url(path_or_url),
                headers=retry_headers,
                timeout=timeout,
                **kwargs,
            )

        response.raise_for_status()
        return response
