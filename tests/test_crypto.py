from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lego_dimensions_protocol.crypto import (
    decrypt_character_pages,
    encrypt_character_pages,
    generate_password,
    generate_password_bytes,
)


_SAMPLE_UID = [0x04, 0x9A, 0x74, 0x6A, 0x0B, 0x40, 0x80]


def _int_to_bytes(value: int) -> list[int]:
    return [(value >> shift) & 0xFF for shift in (24, 16, 8, 0)]


def test_roundtrip_character_encryption_and_decryption():
    encrypted = encrypt_character_pages(_SAMPLE_UID, 0x12345678)
    page24, page25 = (_int_to_bytes(value) for value in encrypted)
    decoded = decrypt_character_pages(_SAMPLE_UID, page24, page25)
    assert decoded == 0x12345678


def test_decrypt_invalid_payload_returns_zero():
    decoded = decrypt_character_pages(_SAMPLE_UID, [0, 0, 0, 1], [0, 0, 0, 2])
    assert decoded == 0


def test_generate_password_matches_expected_value():
    password = generate_password(_SAMPLE_UID)
    assert password == 0x7FFAD6D9


def test_generate_password_bytes_breaks_into_components():
    password_bytes = generate_password_bytes(_SAMPLE_UID)
    assert password_bytes == (0x7F, 0xFA, 0xD6, 0xD9)
