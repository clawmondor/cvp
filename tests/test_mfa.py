"""Tests for MFA service — TOTP generation, encryption, verification."""

import pyotp

from cvp.services.mfa import (
    decrypt_secret,
    encrypt_secret,
    generate_provisioning_uri,
    generate_qr_code_data_uri,
    generate_totp_secret,
    verify_totp_code,
)

# Use a fixed Fernet key for testing (base64 of 32 bytes)
TEST_FERNET_KEY = "dGVzdGtleXRoYXRpczMyYnl0ZXNsb25nMTIzNDU2Nzg="


def test_generate_totp_secret():
    secret = generate_totp_secret()
    assert len(secret) == 32  # base32 encoded, 32 chars
    pyotp.TOTP(secret)  # doesn't raise


def test_encrypt_decrypt_roundtrip():
    secret = "JBSWY3DPEHPK3PXP"
    encrypted = encrypt_secret(secret, TEST_FERNET_KEY)
    assert encrypted != secret
    decrypted = decrypt_secret(encrypted, TEST_FERNET_KEY)
    assert decrypted == secret


def test_verify_totp_code_valid():
    secret = generate_totp_secret()
    totp = pyotp.TOTP(secret)
    code = totp.now()
    assert verify_totp_code(secret, code) is True


def test_verify_totp_code_invalid():
    secret = generate_totp_secret()
    assert verify_totp_code(secret, "000000") is False


def test_generate_provisioning_uri():
    uri = generate_provisioning_uri("JBSWY3DPEHPK3PXP", "user@example.com")
    assert "otpauth://totp/" in uri
    # email may be URL-encoded (@→%40)
    assert "user@example.com" in uri or "user%40example.com" in uri
    assert "Contents+Valuation+Platform" in uri or "Contents%20Valuation%20Platform" in uri


def test_generate_qr_code_data_uri():
    uri = generate_provisioning_uri("JBSWY3DPEHPK3PXP", "user@example.com")
    data_uri = generate_qr_code_data_uri(uri)
    assert data_uri.startswith("data:image/png;base64,")
    assert len(data_uri) > 100
