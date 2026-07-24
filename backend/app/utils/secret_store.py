import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import get_settings
from app.utils.errors import GatewayError


def _fernet() -> Fernet:
    pepper = get_settings().api_key_pepper.get_secret_value().encode("utf-8")
    derived_key = hmac.new(
        pepper,
        b"tokenpool-encrypted-secret-store-v1",
        hashlib.sha256,
    ).digest()
    return Fernet(base64.urlsafe_b64encode(derived_key))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str | None) -> str:
    if not ciphertext:
        raise GatewayError(
            "该记录创建于加密存储启用前，无法查看原文",
            status_code=409,
            code="secret_not_available",
        )
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise GatewayError(
            "无法解密该记录，请联系管理员检查密钥配置",
            status_code=500,
            code="secret_decryption_failed",
        ) from exc
