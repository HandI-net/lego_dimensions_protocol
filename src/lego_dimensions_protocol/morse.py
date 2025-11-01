"""Utility helpers for flashing Morse code on the LEGO Dimensions portal."""

from __future__ import annotations

import re
import time
from typing import Mapping

from .gateway import Gateway, Pad, RGBColor

TIME_UNIT = 0.2
DASH = TIME_UNIT * 3
DOT = TIME_UNIT
SPACE = TIME_UNIT * 3

MORSE_CODE_TABLE: Mapping[str, str] = {
    "a": ".-",
    "b": "-...",
    "c": "-.-.",
    "d": "-..",
    "e": ".",
    "f": "..-.",
    "g": "--.",
    "h": "....",
    "i": "..",
    "j": ".---",
    "k": "-.-",
    "l": ".-..",
    "m": "--",
    "n": "-.",
    "o": "---",
    "p": ".--.",
    "q": "--.-",
    "r": ".-.",
    "s": "...",
    "t": "-",
    "u": "..-",
    "v": "...-",
    "w": ".--",
    "x": "-..-",
    "y": "-.--",
    "z": "--..",
    "0": "-----",
    "1": ".----",
    "2": "..---",
    "3": "...--",
    "4": "....-",
    "5": ".....",
    "6": "-....",
    "7": "--...",
    "8": "---..",
    "9": "----.",
}


def send_character(gateway: Gateway, character: str) -> None:
    character = character.lower()
    if character == " ":
        time.sleep(SPACE)
        return
    code = MORSE_CODE_TABLE[character]
    for symbol in code:
        if symbol == ".":
            gateway.switch_pad(Pad.ALL, RGBColor(255, 0, 0))
            time.sleep(DOT)
        elif symbol == "-":
            gateway.switch_pad(Pad.ALL, RGBColor(0, 0, 255))
            time.sleep(DASH)
        gateway.blank_pads()
        time.sleep(TIME_UNIT)


def send_text(gateway: Gateway, text: str) -> None:
    clean_text = re.sub(r"[^a-z0-9 ]", "", text.lower())
    for character in clean_text:
        send_character(gateway, character)


def demo(text: str = "Lego Dimensions gateway morse code demonstration     ") -> None:
    with Gateway() as gateway:
        while True:
            send_text(gateway, text)


__all__ = ["send_character", "send_text", "demo"]
