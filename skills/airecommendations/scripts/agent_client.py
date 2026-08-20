#!/usr/bin/env python3
"""Zero-dependency reference client for the AI Recommendations agent API.

External AI agents use this to read items that need pricing and to submit
pricing recommendations. It depends only on the Python standard library, so it
drops into any agent environment without extra installs.

Auth is a single ``X-API-Key`` header. An admin mints the key in the app under
System Admin -> Agent Keys; it is shown once at creation (format
``agk_live_<prefix>_<secret>``). Provide it via the constructor or the
``AI_RECS_API_KEY`` environment variable.

Quick start::

    from agent_client import AiRecommendationsClient, dollars_to_cents

    client = AiRecommendationsClient("https://app.example.com", api_key="agk_live_...")
    for item in client.list_items(min_confidence="high"):
        # ... shop for a matching product for `item` ...
        client.submit_recommendation(
            item["item_id"],
            retail_unit_cents=dollars_to_cents("129.99"),
            shipping_cents=dollars_to_cents("9.50"),
            source_url="https://retailer.example/product/123",
            source_retailer="Retailer",
            product_title="What you found",
            rationale="Why it matches",
            item_crop_id=item["crops"][0]["item_crop_id"] if item["crops"] else None,
        )

Run ``python agent_client.py --help`` for a CLI demo of the poll->submit loop.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


class AgentApiError(RuntimeError):
    """Raised when the API returns a non-2xx response.

    Attributes:
        status: the HTTP status code (e.g. 401, 404, 409, 422).
        detail: the server-provided error detail, if any.
    """

    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(f"HTTP {status}: {detail}")


def dollars_to_cents(amount: str | int | float | Decimal) -> int:
    """Convert a dollar amount to integer cents (half-up rounding).

    The API stores and expects currency as integer cents, never floats. Prefer
    passing a string (e.g. "129.99") to avoid binary float rounding surprises.
    """
    cents = (Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


class AiRecommendationsClient:
    """Client for the ``/api/agent/*`` recommendation endpoints."""

    def __init__(self, base_url: str, api_key: str | None = None, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("AI_RECS_API_KEY", "")
        self.timeout = timeout

    # -- Public API -------------------------------------------------------

    def list_items(
        self,
        *,
        min_confidence: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return items that need a recommendation.

        Items are high-confidence, still unpriced, and below the 5-pending cap.
        ``min_confidence`` (``"high"``/``"medium"``/``"low"``) overrides the
        server's configured default threshold. Page with ``limit``/``offset``.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if min_confidence is not None:
            params["min_confidence"] = min_confidence
        payload = self._request("GET", "/api/agent/items", params=params)
        return payload["items"]

    def get_item(self, item_id: str) -> dict[str, Any]:
        """Return one item's detail (same shape as a feed entry). 404 -> AgentApiError."""
        return self._request("GET", f"/api/agent/items/{item_id}")

    def fetch_crop(self, image_url_or_path: str) -> bytes:
        """Fetch a crop image's raw bytes.

        Pass the ``image_url`` from a crop entry (e.g.
        ``/api/agent/crops/<path>``) or a bare crop path.
        """
        if image_url_or_path.startswith("/api/agent/crops/"):
            path = image_url_or_path
        elif image_url_or_path.startswith("/"):
            path = image_url_or_path
        else:
            path = f"/api/agent/crops/{image_url_or_path}"
        return self._request("GET", path, parse_json=False)

    def submit_recommendation(
        self,
        item_id: str,
        *,
        retail_unit_cents: int,
        source_url: str,
        source_retailer: str,
        shipping_cents: int = 0,
        match_type: str = "exact",
        product_title: str = "",
        rationale: str = "",
        item_crop_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit a pricing recommendation for an item.

        Currency values are integer cents. ``source_url`` and ``source_retailer``
        are required (empty values -> 422). Returns ``{"id", "status", "item_id"}``.
        Raises AgentApiError on 404 (unknown item), 409 (item already has 5
        pending recommendations), or 422 (validation, e.g. missing source /
        negative cents).
        """
        body = {
            "proposed_retail_unit_cents": retail_unit_cents,
            "proposed_shipping_cents": shipping_cents,
            "source_url": source_url,
            "source_retailer": source_retailer,
            "match_type": match_type,
            "product_title": product_title,
            "rationale": rationale,
            "item_crop_id": item_crop_id,
        }
        return self._request("POST", f"/api/agent/items/{item_id}/recommendations", json_body=body)

    # -- Internals --------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        parse_json: bool = True,
    ) -> Any:
        url = self.base_url + path
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        headers = {"X-API-Key": self.api_key, "Accept": "application/json"}
        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        status, body = self._send(method, url, headers, data)

        if status >= 400:
            raise AgentApiError(status, _extract_detail(body))
        if not parse_json:
            return body
        return json.loads(body) if body else None

    def _send(
        self, method: str, url: str, headers: dict[str, str], data: bytes | None
    ) -> tuple[int, bytes]:
        """The single network seam. Override in tests to avoid real HTTP."""
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


def _extract_detail(body: bytes) -> str:
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return body.decode("utf-8", "replace") if body else ""
    if isinstance(parsed, dict) and "detail" in parsed:
        return (
            json.dumps(parsed["detail"])
            if not isinstance(parsed["detail"], str)
            else parsed["detail"]
        )
    return json.dumps(parsed)


def _demo(base_url: str, api_key: str, *, min_confidence: str | None, dry_run: bool) -> None:
    client = AiRecommendationsClient(base_url, api_key=api_key)
    items = client.list_items(min_confidence=min_confidence, limit=10)
    print(f"{len(items)} item(s) need a recommendation:")
    for item in items:
        crops = ", ".join(c["image_url"] for c in item["crops"]) or "(no crops)"
        print(f"  - {item['item_id']}  {item['description']!r}  crops: {crops}")
        if dry_run:
            continue
        # Replace this stub with a real product search before submitting.
        client.submit_recommendation(
            item["item_id"],
            retail_unit_cents=dollars_to_cents("0.00"),
            source_url="https://example.com/replace-me",
            source_retailer="Replace Me",
            product_title="Replace with the product you found",
            rationale="Replace with why it matches",
            item_crop_id=item["crops"][0]["item_crop_id"] if item["crops"] else None,
        )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="AI Recommendations agent client demo.")
    parser.add_argument(
        "--base-url", required=True, help="App base URL, e.g. https://app.example.com"
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("AI_RECS_API_KEY", ""),
        help="Agent API key (or set AI_RECS_API_KEY).",
    )
    parser.add_argument("--min-confidence", choices=["high", "medium", "low"], default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List items only; do not submit placeholder recommendations.",
    )
    args = parser.parse_args()
    if not args.api_key:
        parser.error("provide --api-key or set AI_RECS_API_KEY")
    _demo(args.base_url, args.api_key, min_confidence=args.min_confidence, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
