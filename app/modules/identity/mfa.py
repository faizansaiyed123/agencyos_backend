"""TOTP (RFC 6238) helpers — pure functions, no I/O. Works with any standard
authenticator app (Google Authenticator, Authy, 1Password, etc.); nothing here
calls out to a third-party service.
"""

import io
import secrets

import pyotp
import qrcode
import qrcode.image.svg

from app.core.security import hash_token

_RECOVERY_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I ambiguity


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(*, secret: str, account_email: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account_email, issuer_name=issuer)


def qr_code_svg(uri: str) -> str:
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def verify_totp_code(*, secret: str, code: str) -> bool:
    # valid_window=1 tolerates ±30s of clock drift between server and device.
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def generate_recovery_codes(count: int) -> list[str]:
    """Returns plaintext codes (e.g. 'XZ7K-QM2P'). Caller stores only the hash of
    each (see app.core.security.hash_token) and shows the plaintext exactly once."""
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(_RECOVERY_CODE_ALPHABET) for _ in range(8))
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def hash_recovery_code(code: str) -> str:
    # Recovery codes are opaque random strings like refresh/invite tokens, so the
    # same SHA-256-of-a-high-entropy-value scheme in security.py applies here.
    return hash_token(code.upper().replace("-", ""))
