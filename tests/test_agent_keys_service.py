from cvp.services.agent_keys import generate_key, hash_key, parse_prefix


def test_generate_key_shape():
    full, prefix, key_hash = generate_key()
    assert full.startswith("agk_live_")
    assert prefix in full
    assert hash_key(full) == key_hash
    assert parse_prefix(full) == prefix


def test_hash_is_deterministic_and_prefix_roundtrips():
    full, prefix, key_hash = generate_key()
    assert hash_key(full) == hash_key(full)
    assert parse_prefix(full) == prefix
    assert parse_prefix("not-a-key") is None
