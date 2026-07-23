import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.config.settings import get_settings


SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=32,
    )
    return "$".join(
        [
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_text, digest_text = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text)
        expected = base64.urlsafe_b64decode(digest_text)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int) -> tuple[str, int]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.jwt_expire_minutes)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": expires,
            "type": "access",
            "iss": "team-ai-gateway",
            "aud": "team-ai-gateway",
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    return token, settings.jwt_expire_minutes * 60


def decode_access_token(token: str) -> int | None:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience="team-ai-gateway",
            issuer="team-ai-gateway",
        )
        if payload.get("type") != "access":
            return None
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def generate_api_key() -> tuple[str, str, str]:
    raw_key = f"sk-team-{secrets.token_urlsafe(32)}"
    prefix = f"{raw_key[:16]}..."
    return raw_key, prefix, hash_api_key(raw_key)


def hash_api_key(raw_key: str) -> str:
    pepper = get_settings().api_key_pepper.get_secret_value().encode("utf-8")
    return hmac.new(pepper, raw_key.encode("utf-8"), hashlib.sha256).hexdigest()
