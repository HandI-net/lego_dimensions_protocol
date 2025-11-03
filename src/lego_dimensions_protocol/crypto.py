"""Cryptography helpers ported from the ldnfctags vendor drop."""

from __future__ import annotations

from typing import Iterable, Sequence, Tuple

__all__ = [
    "decrypt_character_pages",
    "encrypt_character_pages",
    "generate_password",
    "generate_password_bytes",
]

_DELTA = 0x9E3779B9
_UID_LENGTH = 7
_PASSWORD_SEED = b"UUUUUUU(c) Copyright LEGO 2014AA"


def _from_be(value: int) -> int:
    return int.from_bytes(int(value & 0xFFFFFFFF).to_bytes(4, "big"), "little")


def _to_be(value: int) -> int:
    return int.from_bytes(int(value & 0xFFFFFFFF).to_bytes(4, "little"), "big")


def _ensure_uid(uid: Sequence[int]) -> Tuple[int, ...]:
    if len(uid) != _UID_LENGTH:
        raise ValueError(f"A LEGO Dimensions UID must contain {_UID_LENGTH} bytes.")
    return tuple(int(value) & 0xFF for value in uid)


def _tea_encrypt(values: Tuple[int, int], key: Tuple[int, int, int, int]) -> Tuple[int, int]:
    v0, v1 = values
    k0, k1, k2, k3 = key
    total = 0
    for _ in range(32):
        total = (total + _DELTA) & 0xFFFFFFFF
        v0 = (v0 + (((v1 << 4) + k0) ^ (v1 + total) ^ ((v1 >> 5) + k1))) & 0xFFFFFFFF
        v1 = (v1 + (((v0 << 4) + k2) ^ (v0 + total) ^ ((v0 >> 5) + k3))) & 0xFFFFFFFF
    return v0, v1


def _tea_decrypt(values: Tuple[int, int], key: Tuple[int, int, int, int]) -> Tuple[int, int]:
    v0, v1 = values
    k0, k1, k2, k3 = key
    total = (32 * _DELTA) & 0xFFFFFFFF
    for _ in range(32):
        v1 = (v1 - (((v0 << 4) + k2) ^ (v0 + total) ^ ((v0 >> 5) + k3))) & 0xFFFFFFFF
        v0 = (v0 - (((v1 << 4) + k0) ^ (v1 + total) ^ ((v1 >> 5) + k1))) & 0xFFFFFFFF
        total = (total - _DELTA) & 0xFFFFFFFF
    return v0, v1


def _scramble(uid: Tuple[int, ...], count: int) -> int:
    if not 0 < count <= 8:
        raise ValueError("Scramble count must be between 1 and 8 inclusive.")
    base = [
        0xFF,
        0xFF,
        0xFF,
        0xFF,
        0xFF,
        0xFF,
        0xFF,
        0xB7,
        0xD5,
        0xD7,
        0xE6,
        0xE7,
        0xBA,
        0x3C,
        0xA8,
        0xD8,
        0x75,
        0x47,
        0x68,
        0xCF,
        0x23,
        0xE9,
        0xFE,
        0xAA,
    ]
    for index, value in enumerate(uid):
        base[index] = value
    base[count * 4 - 1] = 0xAA

    v2 = 0
    for index in range(count):
        b = (
            (base[index * 4 + 3] << 24)
            | (base[index * 4 + 2] << 16)
            | (base[index * 4 + 1] << 8)
            | base[index * 4]
        )
        v4 = ((v2 >> 7) | (v2 << 25)) & 0xFFFFFFFF
        v5 = ((v2 >> 22) | (v2 << 10)) & 0xFFFFFFFF
        v2 = (b + v4 + v5 - v2) & 0xFFFFFFFF
    return v2


def _generate_teakey(uid: Tuple[int, ...]) -> Tuple[int, int, int, int]:
    key = (
        _scramble(uid, 3),
        _scramble(uid, 4),
        _scramble(uid, 5),
        _scramble(uid, 6),
    )
    return key


def _convert_to_int(block: Sequence[int]) -> int:
    if len(block) != 4:
        raise ValueError("Page data must contain exactly four bytes.")
    result = 0
    for value in block:
        result = (result << 8) | (int(value) & 0xFF)
    return result & 0xFFFFFFFF


def decrypt_character_pages(
    uid: Sequence[int],
    page24: Sequence[int],
    page25: Sequence[int],
) -> int:
    """Return the character identifier stored in *page24*/*page25*.

    The *uid* sequence must contain the full seven bytes reported by the portal
    for an NFC tag. ``0`` is returned when the decrypted payload does not match
    the expected structure.
    """

    uid_bytes = _ensure_uid(uid)
    key = tuple(_to_be(value) for value in _generate_teakey(uid_bytes))
    block = (
        _from_be(_convert_to_int(page24)),
        _from_be(_convert_to_int(page25)),
    )
    decrypted = _tea_decrypt(block, key)
    if decrypted[0] != decrypted[1]:
        return 0
    return _to_be(decrypted[0])


def encrypt_character_pages(uid: Sequence[int], character_id: int) -> Tuple[int, int]:
    """Return encrypted tag pages for *character_id* using *uid*.

    This mirrors the vendor implementation and is mainly exposed for testing so
    we can verify the decryptor behaves as expected.
    """

    uid_bytes = _ensure_uid(uid)
    key = tuple(_from_be(value) for value in _generate_teakey(uid_bytes))
    character_value = _from_be(character_id & 0xFFFFFFFF)
    payload = (character_value, character_value)
    encrypted = _tea_encrypt(payload, key)
    return tuple(_to_be(value) for value in encrypted)


def generate_password(uid: Sequence[int]) -> int:
    """Return the 32-bit password for *uid* as used by the portal."""

    uid_bytes = _ensure_uid(uid)
    base = bytearray(_PASSWORD_SEED)
    base[: len(uid_bytes)] = uid_bytes
    base[30] = 0xAA
    base[31] = 0xAA

    v2 = 0
    for index in range(8):
        chunk = (
            (base[index * 4 + 3] << 24)
            | (base[index * 4 + 2] << 16)
            | (base[index * 4 + 1] << 8)
            | base[index * 4]
        )
        v4 = ((v2 >> 25) | (v2 << 7)) & 0xFFFFFFFF
        v5 = ((v2 >> 10) | (v2 << 22)) & 0xFFFFFFFF
        v2 = (chunk + v4 + v5 - v2) & 0xFFFFFFFF
    return _to_be(v2)


def generate_password_bytes(uid: Sequence[int]) -> Tuple[int, int, int, int]:
    """Return the password for *uid* as four individual bytes."""

    value = generate_password(uid)
    return (
        (value >> 24) & 0xFF,
        (value >> 16) & 0xFF,
        (value >> 8) & 0xFF,
        value & 0xFF,
    )
