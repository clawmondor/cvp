from claimos.services.audit import get_client_ip


class _CaseInsensitiveHeaders(dict):
    """Minimal case-insensitive headers dict, mimicking FastAPI's Headers object."""

    def get(self, key: str, default=None):  # type: ignore[override]
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    def __init__(self, headers: dict[str, str], host: str = "127.0.0.1") -> None:
        self.headers = _CaseInsensitiveHeaders(headers)
        self.client = _FakeClient(host)


def test_get_client_ip_prefers_cf_connecting_ip():
    req = _FakeRequest(headers={"CF-Connecting-IP": "203.0.113.42"})
    assert get_client_ip(req) == "203.0.113.42"


def test_get_client_ip_falls_back_to_x_forwarded_for():
    req = _FakeRequest(headers={"X-Forwarded-For": "203.0.113.10, 10.0.0.1"})
    assert get_client_ip(req) == "203.0.113.10"


def test_get_client_ip_falls_back_to_request_client():
    req = _FakeRequest(headers={}, host="127.0.0.1")
    assert get_client_ip(req) == "127.0.0.1"


def test_get_client_ip_handles_case_insensitive_header():
    req = _FakeRequest(headers={"cf-connecting-ip": "198.51.100.7"})
    assert get_client_ip(req) == "198.51.100.7"
