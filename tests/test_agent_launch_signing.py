from cvp.services.agent_launch import sign_payload


def test_known_vector():
    """Fixed vector — the Cloudflare Worker implements the same computation.

    If this value changes, the Worker's verify() must change with it.
    """
    sig = sign_payload("topsecret", "1757462400", '{"run_id":"abc"}')
    assert sig == ("v1=a3e15302f3da219c4094cc60fc43f2bc5d694071dc2d6664006f1b55ff891fd3")


def test_signature_is_prefixed_and_hex():
    sig = sign_payload("k", "1", "{}")
    assert sig.startswith("v1=")
    assert len(sig) == 3 + 64
    int(sig[3:], 16)  # raises if not hex


def test_different_body_changes_signature():
    a = sign_payload("k", "1", '{"a":1}')
    b = sign_payload("k", "1", '{"a":2}')
    assert a != b


def test_different_timestamp_changes_signature():
    a = sign_payload("k", "1", "{}")
    b = sign_payload("k", "2", "{}")
    assert a != b
