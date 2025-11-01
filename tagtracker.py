"""Legacy entry point for the RFID tag tracker demo."""

from lego_dimensions_protocol.rfid import TagTracker, watch_pads

__all__ = ["TagTracker", "watch_pads"]


def main() -> None:  # pragma: no cover - legacy wrapper
    watch_pads()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
