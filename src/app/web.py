"""Minimal HTTP + crypto helpers that prefer the platform's native primitives.

On Workers these use `fetch` and WebCrypto from the JS runtime, which cost almost no
Python CPU — the free plan allows 10ms per request, and the libraries these replace
(authlib, google-auth, cryptography) cost ~200ms just to import and initialise.

Everything imports its dependencies inside the function: importing `js` off-Workers
fails, and importing httpx2 during module evaluation on Workers fails with
"Top-level await in module is unsettled".
"""

from __future__ import annotations

import base64
import json
from typing import Any


class HttpError(Exception):
    """A request could not be completed (network, DNS, TLS)."""


def _on_workers() -> bool:
    try:
        import js  # noqa: F401
    except ImportError:
        return False
    return True


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def jwt_payload(token: str) -> dict:
    """Decode a JWT's claims *without* verifying the signature.

    Only safe for a token received directly from the issuer's token endpoint over
    TLS, where the channel itself authenticates the response.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not a JWT")
    return json.loads(b64url_decode(parts[1]))


async def post_form(url: str, data: dict[str, str]) -> tuple[int, Any]:
    """POST form-encoded data, returning (status, parsed JSON or text)."""
    if _on_workers():
        return await _workers_request("POST", url, form=data)
    return await _httpx_request("POST", url, data=data)


async def get_json(
    url: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None
) -> tuple[int, Any]:
    if _on_workers():
        return await _workers_request("GET", url, params=params, headers=headers)
    return await _httpx_request("GET", url, params=params, headers=headers)


async def _workers_request(
    method: str,
    url: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    form: dict[str, str] | None = None,
) -> tuple[int, Any]:
    from js import Object, URLSearchParams
    from js import fetch as js_fetch
    from pyodide.ffi import to_js

    if params:
        url = f"{url}?{urlencode(params)}"
    options: dict[str, Any] = {"method": method}
    request_headers = dict(headers or {})
    if form is not None:
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        options["body"] = URLSearchParams.new(urlencode(form))
    if request_headers:
        options["headers"] = to_js(request_headers, dict_converter=Object.fromEntries)
    try:
        response = await js_fetch(url, to_js(options, dict_converter=Object.fromEntries))
        text = await response.text()
    except Exception as exc:  # noqa: BLE001 - JS exceptions arrive untyped
        raise HttpError(f"{method} {url} failed: {exc}") from exc
    return int(response.status), _maybe_json(text)


async def _httpx_request(
    method: str,
    url: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
) -> tuple[int, Any]:
    import httpx2

    try:
        async with httpx2.AsyncClient(timeout=10.0) as client:
            response = await client.request(
                method, url, params=params, headers=headers, data=data
            )
    except Exception as exc:  # noqa: BLE001 - httpx2 error hierarchy varies
        raise HttpError(f"{method} {url} failed: {exc}") from exc
    return response.status_code, _maybe_json(response.text)


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


def urlencode(data: dict[str, str]) -> str:
    from urllib.parse import urlencode as _urlencode

    return _urlencode(data)


async def sign_rs256(private_key_pem: str, signing_input: bytes) -> bytes:
    """RS256-sign with WebCrypto on Workers, falling back to `cryptography` locally."""
    if _on_workers():
        return await _sign_rs256_webcrypto(private_key_pem, signing_input)
    return _sign_rs256_cryptography(private_key_pem, signing_input)


def _pem_to_der(private_key_pem: str) -> bytes:
    body = "".join(
        line.strip()
        for line in private_key_pem.strip().splitlines()
        if "-----" not in line
    )
    return base64.b64decode(body)


async def _sign_rs256_webcrypto(private_key_pem: str, signing_input: bytes) -> bytes:
    from js import Object, Uint8Array, crypto
    from pyodide.ffi import to_js

    der = _pem_to_der(private_key_pem)
    algorithm = to_js(
        {"name": "RSASSA-PKCS1-v1_5", "hash": {"name": "SHA-256"}},
        dict_converter=Object.fromEntries,
    )
    key = await crypto.subtle.importKey(
        "pkcs8", Uint8Array.new(list(der)), algorithm, False, ["sign"]
    )
    signature = await crypto.subtle.sign(
        "RSASSA-PKCS1-v1_5", key, Uint8Array.new(list(signing_input))
    )
    return bytes(Uint8Array.new(signature))


def _sign_rs256_cryptography(private_key_pem: str, signing_input: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    return key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
