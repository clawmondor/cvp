"""TOTP MFA service — secret generation, encryption, verification, QR codes."""

import base64
import io

import pyotp
import qrcode
from cryptography.fernet import Fernet


def generate_totp_secret() -> str:
    """Generate a new random TOTP secret (base32 encoded, 32 chars)."""
    return pyotp.random_base32()


def encrypt_secret(secret: str, fernet_key: str) -> str:
    """Encrypt a TOTP secret for storage using Fernet symmetric encryption."""
    f = Fernet(fernet_key.encode() if isinstance(fernet_key, str) else fernet_key)
    return f.encrypt(secret.encode()).decode()


def decrypt_secret(encrypted: str, fernet_key: str) -> str:
    """Decrypt a stored TOTP secret."""
    f = Fernet(fernet_key.encode() if isinstance(fernet_key, str) else fernet_key)
    return f.decrypt(encrypted.encode()).decode()


def verify_totp_code(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code. Allows 30-second window for clock drift."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_provisioning_uri(secret: str, email: str) -> str:
    """Generate an otpauth:// URI for authenticator app setup."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name="Contents Valuation Platform")


def generate_qr_code_data_uri(provisioning_uri: str) -> str:
    """Generate a base64-encoded PNG QR code as a data URI for inline display."""
    qr = qrcode.QRCode(version=1, box_size=6, border=4)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"
