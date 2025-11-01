#-------------------------------------------------------------------------------
# Name:        morse
"""Legacy entry point for Morse code demo."""

from lego_dimensions_protocol.morse import demo, send_character, send_text


def main() -> None:  # pragma: no cover - legacy wrapper
    demo()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
