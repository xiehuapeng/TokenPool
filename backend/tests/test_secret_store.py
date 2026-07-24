import pytest

from app.utils.errors import GatewayError
from app.utils.secret_store import decrypt_secret, encrypt_secret


def test_secret_store_round_trip_without_plaintext_storage():
    raw_secret = "sk-team-repeat-view-test"

    ciphertext = encrypt_secret(raw_secret)

    assert raw_secret not in ciphertext
    assert decrypt_secret(ciphertext) == raw_secret


def test_legacy_secret_without_ciphertext_cannot_be_recovered():
    with pytest.raises(GatewayError) as exc_info:
        decrypt_secret(None)

    assert exc_info.value.code == "secret_not_available"
    assert exc_info.value.status_code == 409
