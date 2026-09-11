"""Launching a Cloudflare agent run: signing, payload, and the outbound POST.

The Worker is world-reachable, so a forged launch would spend real money
against a capped OpenRouter key. Requests are HMAC-signed over
"<timestamp>.<body>" and the Worker enforces a freshness window.
"""

import hashlib
import hmac


def sign_payload(secret: str, timestamp: str, body: str) -> str:
    """Return "v1=<hex>" for HMAC-SHA256 over "<timestamp>.<body>".

    The Cloudflare Worker implements the identical computation; the fixed
    vector in tests/test_agent_launch_signing.py is the shared contract.
    """
    mac = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{body}".encode("utf-8"),
        hashlib.sha256,
    )
    return f"v1={mac.hexdigest()}"
