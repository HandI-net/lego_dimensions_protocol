"""Typed helper utilities for speaking the LEGO Dimensions USB protocol."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import logging
from typing import TYPE_CHECKING, Any, Iterator, Optional, Sequence, Tuple

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing helper only
    import usb.core as _usb_core_mod  # type: ignore[import-not-found]
    import usb.util as _usb_util_mod  # type: ignore[import-not-found]

    USBDevice = _usb_core_mod.Device
else:  # pragma: no cover - runtime fallback
    USBDevice = Any

MAX_PACKET_LENGTH = 32
_CHECKSUM_LENGTH = 1
_DEFAULT_WRITE_ENDPOINT = 0x01
_DEFAULT_READ_ENDPOINT = 0x81
_DEFAULT_INTERFACE = 0

DEFAULT_VENDOR_ID = 0x0E6F
DEFAULT_PRODUCT_IDS: Tuple[int, ...] = (
    0x0241,
    0x0242,
    0x0243,
)

STARTUP_SEQUENCE: Tuple[int, ...] = (
    0x55,
    0x0F,
    0xB0,
    0x01,
    0x28,
    0x63,
    0x29,
    0x20,
    0x4C,
    0x45,
    0x47,
    0x4F,
    0x20,
    0x32,
    0x30,
    0x31,
    0x34,
    0xF7,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
)


class PortalNotFoundError(RuntimeError):
    """Raised when a connected LEGO Dimensions portal cannot be located."""


class Pad(IntEnum):
    """Identifier for the physical pads on the portal."""

    ALL = 0
    CENTRE = 1
    LEFT = 2
    RIGHT = 3


@dataclass(frozen=True)
class RGBColor:
    """Immutable representation of an RGB colour used by the portal."""

    red: int
    green: int
    blue: int

    def __post_init__(self) -> None:
        for value in (self.red, self.green, self.blue):
            _ensure_byte(value, "colour channel")

    def as_tuple(self) -> Tuple[int, int, int]:
        return (self.red, self.green, self.blue)

    @classmethod
    def from_iterable(cls, values: Sequence[int]) -> "RGBColor":
        if len(values) != 3:
            raise ValueError(
                "An RGB colour requires exactly three values (red, green, blue)."
            )
        red, green, blue = (int(v) for v in values)
        return cls(red=red, green=green, blue=blue)

    def __iter__(self) -> Iterator[int]:
        yield from (self.red, self.green, self.blue)


ColourLike = Sequence[int] | RGBColor


def _ensure_byte(value: int, description: str) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"{description} must be an integer") from exc
    if not 0 <= integer <= 0xFF:
        raise ValueError(f"{description} must fit in a single byte (0-255).")
    return integer


def _normalise_colour(colour: ColourLike) -> Tuple[int, int, int]:
    if isinstance(colour, RGBColor):
        return colour.as_tuple()
    return RGBColor.from_iterable(colour).as_tuple()


def _fill_to_packet(message: Sequence[int]) -> Tuple[int, ...]:
    if len(message) > MAX_PACKET_LENGTH:
        raise ValueError("Portal packets cannot exceed 32 bytes.")
    padded = list(message)
    while len(padded) < MAX_PACKET_LENGTH:
        padded.append(0)
    return tuple(padded)


def _require_usb() -> Tuple[Any, Any]:
    try:
        import usb.core  # type: ignore[import-not-found]
        import usb.util  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
        raise ModuleNotFoundError(
            "pyusb is required to talk to the LEGO Dimensions portal. "
            "Install it with 'pip install pyusb'."
        ) from exc
    return usb.core, usb.util


class Gateway:
    """High level API for issuing commands to the LEGO Dimensions portal."""

    def __init__(
        self,
        *,
        vendor_id: int = DEFAULT_VENDOR_ID,
        product_ids: Sequence[int] | None = DEFAULT_PRODUCT_IDS,
        interface: int = _DEFAULT_INTERFACE,
        endpoint: int = _DEFAULT_WRITE_ENDPOINT,
        read_endpoint: int = _DEFAULT_READ_ENDPOINT,
        timeout: int | None = 5000,
        initialize: bool = True,
        auto_detach: bool = True,
        startup_sequence: Sequence[int] = STARTUP_SEQUENCE,
    ) -> None:
        self.vendor_id = vendor_id
        self.product_ids = tuple(product_ids) if product_ids else ()
        self.interface = interface
        self.endpoint = endpoint
        self.read_endpoint = read_endpoint
        self.timeout = timeout
        self.auto_detach = auto_detach
        self._startup_sequence = tuple(startup_sequence)

        self.dev: Optional[USBDevice] = None
        self._usb_core: Any | None = None
        self._usb_util: Any | None = None
        self._reattach_driver = False
        self._reported_usb_messages: set[str] = set()

        self.connect()
        if initialize:
            self.initialise_portal()
            self.blank_pads()

    def connect(self) -> None:
        """Discover the portal and claim the USB interface."""

        if self.dev is not None:
            return

        usb_core, usb_util = _require_usb()
        self._usb_core = usb_core
        self._usb_util = usb_util

        device = self._find_device(usb_core)
        if device is None:
            raise PortalNotFoundError(
                "Unable to locate a LEGO Dimensions portal. "
                "Ensure the device is connected and accessible."
            )
        LOGGER.debug(
            "Connected to portal: vendor=%#04x product=%#04x", device.idVendor, device.idProduct
        )

        if self.auto_detach and device.is_kernel_driver_active(self.interface):
            LOGGER.info("Detaching kernel driver from interface %s", self.interface)
            device.detach_kernel_driver(self.interface)
            self._reattach_driver = True

        device.set_configuration()
        usb_util.claim_interface(device, self.interface)
        self.dev = device

    def initialise_portal(self) -> None:
        """Send the stock start-up packet to the portal."""

        self.send_packet(self._startup_sequence)

    def close(self) -> None:
        """Release USB resources and reattach the kernel driver if needed."""

        if self.dev is None or self._usb_util is None or self._usb_core is None:
            return

        try:
            self._usb_util.release_interface(self.dev, self.interface)
        except self._usb_core.USBError:  # pragma: no cover - best effort cleanup
            LOGGER.warning("Failed to release USB interface", exc_info=True)
        if self._reattach_driver:
            try:
                self.dev.attach_kernel_driver(self.interface)
            except self._usb_core.USBError:  # pragma: no cover - best effort cleanup
                LOGGER.warning("Failed to reattach kernel driver", exc_info=True)
        self._usb_util.dispose_resources(self.dev)
        self.dev = None
        self._usb_core = None
        self._usb_util = None
        self._reattach_driver = False

    def __enter__(self) -> "Gateway":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - destructor safety
        try:
            self.close()
        except Exception:  # pragma: no cover
            LOGGER.debug("Suppressing exception during Gateway.__del__", exc_info=True)

    def _find_device(self, usb_core: Any) -> Optional[USBDevice]:
        """Attempt to locate a compatible portal on the USB bus."""

        if self.product_ids:
            for product_id in self.product_ids:
                device = usb_core.find(idVendor=self.vendor_id, idProduct=product_id)
                if device is not None:
                    return device
        return usb_core.find(idVendor=self.vendor_id)

    @staticmethod
    def generate_checksum(command: Sequence[int]) -> int:
        result = 0
        for byte in command:
            result += _ensure_byte(byte, "command byte")
            result &= 0xFF
        return result

    def convert_command_to_packet(self, command: Sequence[int]) -> Tuple[int, ...]:
        if len(command) > MAX_PACKET_LENGTH - _CHECKSUM_LENGTH:
            raise ValueError("Command payloads may not exceed 31 bytes.")
        checksum = self.generate_checksum(command)
        return _fill_to_packet(tuple(command) + (checksum,))

    def send_packet(self, packet: Sequence[int]) -> None:
        if len(packet) != MAX_PACKET_LENGTH:
            raise ValueError("Packets sent to the portal must be exactly 32 bytes long.")
        if self.dev is None:
            raise RuntimeError("Gateway not connected. Call connect() before issuing commands.")
        data = bytes(_ensure_byte(b, "packet byte") for b in packet)
        LOGGER.debug("Sending packet: %s", " ".join(f"{value:02x}" for value in data))
        self.dev.write(self.endpoint, data, timeout=self.timeout)

    def send_command(self, command: Sequence[int]) -> None:
        packet = self.convert_command_to_packet(command)
        self.send_packet(packet)

    def read_packet(self, *, timeout: int | None = None) -> Optional[Tuple[int, ...]]:
        """Read a single 32-byte packet from the portal.

        Parameters
        ----------
        timeout:
            Override the default gateway timeout for this read in milliseconds.

        Returns
        -------
        Optional[Tuple[int, ...]]
            A tuple containing the packet bytes when data is available. ``None``
            is returned when the call times out without receiving data.
        """

        if self.dev is None or self._usb_core is None:
            raise RuntimeError("Gateway not connected. Call connect() before reading packets.")

        read_timeout = self.timeout if timeout is None else timeout
        usb_timeout_type = getattr(self._usb_core, "USBTimeoutError", None)
        try:
            data = self.dev.read(
                self.read_endpoint,
                MAX_PACKET_LENGTH,
                timeout=read_timeout,
            )
        except Exception as exc:  # pragma: no cover - USB backend specific
            if usb_timeout_type and isinstance(exc, usb_timeout_type):
                self._log_usb_exception(
                    "Timed out waiting for data from the LEGO Dimensions portal; still waiting",
                    exc,
                    level=logging.INFO,
                )
                return None
            if isinstance(exc, self._usb_core.USBError):
                timeout_codes = {
                    value
                    for value in (
                        getattr(self._usb_core, "LIBUSB_ERROR_TIMEOUT", None),
                        60,
                        110,
                    )
                    if value is not None
                }
                timeout_codes.add(None)
                if getattr(exc, "errno", None) in timeout_codes:
                    self._log_usb_exception(
                        "Timed out waiting for data from the LEGO Dimensions portal; still waiting",
                        exc,
                        level=logging.INFO,
                    )
                    return None
                self._log_usb_exception(
                    "USB error while reading from the LEGO Dimensions portal",
                    exc,
                )
            raise

        return tuple(int(byte) & 0xFF for byte in data)

    def _log_usb_exception(
        self,
        message: str,
        exc: BaseException,
        *,
        level: int = logging.WARNING,
    ) -> None:
        if message in self._reported_usb_messages:
            return
        self._reported_usb_messages.add(message)
        LOGGER.log(
            level,
            "%s: %s",
            message,
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    def iter_packets(self, *, timeout: int | None = None) -> Iterator[Tuple[int, ...]]:
        """Yield packets from the portal as they arrive."""

        while True:
            packet = self.read_packet(timeout=timeout)
            if packet is None:
                continue
            yield packet

    def blank_pads(self) -> None:
        self.switch_pad(Pad.ALL, RGBColor(0, 0, 0))

    def switch_pad(self, pad: Pad | int, colour: ColourLike) -> None:
        pad_value = _ensure_byte(int(Pad(pad)), "pad selector")
        red, green, blue = _normalise_colour(colour)
        command = [0x55, 0x06, 0xC0, 0x02, pad_value, red, green, blue]
        self.send_command(command)

    def flash_pad(
        self,
        pad: Pad | int,
        *,
        on_length: int,
        off_length: int,
        pulse_count: int,
        colour: ColourLike,
    ) -> None:
        pad_value = _ensure_byte(int(Pad(pad)), "pad selector")
        on_byte = _ensure_byte(on_length, "flash on length")
        off_byte = _ensure_byte(off_length, "flash off length")
        pulse_byte = _ensure_byte(pulse_count, "flash pulse count")
        red, green, blue = _normalise_colour(colour)
        command = [
            0x55,
            0x09,
            0xC3,
            0x1F,
            pad_value,
            on_byte,
            off_byte,
            pulse_byte,
            red,
            green,
            blue,
        ]
        self.send_command(command)

    def fade_pad(
        self,
        pad: Pad | int,
        *,
        pulse_time: int,
        pulse_count: int,
        colour: ColourLike,
    ) -> None:
        pad_value = _ensure_byte(int(Pad(pad)), "pad selector")
        pulse_time_byte = _ensure_byte(pulse_time, "fade pulse time")
        pulse_count_byte = _ensure_byte(pulse_count, "fade pulse count")
        red, green, blue = _normalise_colour(colour)
        command = [
            0x55,
            0x08,
            0xC2,
            0x0F,
            pad_value,
            pulse_time_byte,
            pulse_count_byte,
            red,
            green,
            blue,
        ]
        self.send_command(command)

    def switch_pads(self, colours: Sequence[Optional[ColourLike]]) -> None:
        if len(colours) != 3:
            raise ValueError("switch_pads expects exactly three colour entries.")
        command = [0x55, 0x0E, 0xC8, 0x06]
        for colour in colours:
            if colour is None:
                command.extend((0, 0, 0, 0))
                continue
            red, green, blue = _normalise_colour(colour)
            command.extend((1, red, green, blue))
        self.send_command(command)

    def fade_pads(
        self,
        pads: Sequence[Optional[Tuple[int, int, ColourLike]]],
    ) -> None:
        if len(pads) != 3:
            raise ValueError("fade_pads expects exactly three pad entries.")
        command = [0x55, 0x14, 0xC6, 0x26]
        for pad in pads:
            if pad is None:
                command.extend((0, 0, 0, 0, 0, 0))
                continue
            fade_time, pulse_count, colour = pad
            fade_time_byte = _ensure_byte(fade_time, "fade time")
            pulse_count_byte = _ensure_byte(pulse_count, "pulse count")
            red, green, blue = _normalise_colour(colour)
            command.extend((1, fade_time_byte, pulse_count_byte, red, green, blue))
        self.send_command(command)

    def flash_pads(
        self,
        pads: Sequence[Optional[Tuple[int, int, int, ColourLike]]],
    ) -> None:
        if len(pads) != 3:
            raise ValueError("flash_pads expects exactly three pad entries.")
        command = [0x55, 0x17, 0xC7, 0x3E]
        for pad in pads:
            if pad is None:
                command.extend((0, 0, 0, 0, 0, 0, 0))
                continue
            on_length, off_length, pulse_count, colour = pad
            on_length_byte = _ensure_byte(on_length, "on length")
            off_length_byte = _ensure_byte(off_length, "off length")
            pulse_count_byte = _ensure_byte(pulse_count, "pulse count")
            red, green, blue = _normalise_colour(colour)
            command.extend(
                (
                    1,
                    on_length_byte,
                    off_length_byte,
                    pulse_count_byte,
                    red,
                    green,
                    blue,
                )
            )
        self.send_command(command)


__all__ = [
    "Gateway",
    "Pad",
    "PortalNotFoundError",
    "RGBColor",
    "DEFAULT_VENDOR_ID",
    "DEFAULT_PRODUCT_IDS",
]
