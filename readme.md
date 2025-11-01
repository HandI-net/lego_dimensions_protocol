# LEGO Dimensions Protocol

Modern Python 3 tools for controlling the LEGO Dimensions USB portal.  The
original reverse engineering notes from 2015 have been consolidated into a
maintained Python package that exposes a typed, well documented API suitable
for integrating the portal with contemporary automation projects.

## Features

- Python 3.10+ compatible package published via `pyproject.toml`.
- High level :class:`lego_dimensions_protocol.gateway.Gateway` abstraction that
  handles USB discovery, checksum generation and packet construction.
- Convenience helpers for the common lighting commands: switching, fading and
  flashing pads individually or as a group.
- RFID tag tracking utilities with event callbacks and a backwards compatible
  `tagtracker.py` wrapper.
- Morse code helpers for quickly prototyping light-based messaging demos.
- Optional command line demo (`lego-dimensions-demo`) showcasing the API and
  providing a quick smoke test for new installations.
- Interactive RFID light-show demo (`lego-dimensions-rfid-demo`) that maps tag
  identifiers to repeatable lighting sequences.
- Type hints and a `py.typed` marker for seamless integration with static type
  checkers.

## Installation

The project uses modern packaging standards and targets Python 3.10 or newer.
To install the package directly from this repository clone it and install with
`pip`:

```bash
python -m pip install .
```

The only runtime dependency is `pyusb`.  Ensure the underlying `libusb` shared
library is available on your platform (Linux distributions typically ship it,
for Windows install [libusb](https://libusb.info/)).

## Quickstart

```python
from lego_dimensions_protocol import Gateway, Pad, RGBColor, TagTracker

with Gateway() as portal:
    portal.switch_pad(Pad.CENTRE, RGBColor(255, 0, 0))

with TagTracker() as tracker:
    for event in tracker.iter_events():
        if event.removed:
            print(f"Tag {event.uid} removed")
        else:
            print(f"Tag {event.uid} placed on {event.pad.name}")
```

The gateway automatically disconnects and reattaches the kernel driver when
used as a context manager.  The tracker builds on the same gateway and provides
high level events for the RFID reader.

## Command Line Demo

After installation the `lego-dimensions-demo` command becomes available.  It
can be used to run the bundled demonstrations:

```bash
lego-dimensions-demo --tests switch fade --pause 1.5 --log-level DEBUG
```

Use `--vendor-id` and `--product-id` if you need to target a specific hardware
revision.

To explore the RFID helper functionality, launch the dedicated light show:

```bash
lego-dimensions-rfid-demo --log-level DEBUG
```

The script cycles through the pads while initialising, then waits for tags.  As
soon as a tag is detected the UID is converted into a deterministic colour and
timing pattern that loops until the tag is removed, at which point the pad is
blanked again.

## Development

The source tree follows the standard `src` layout.  The legacy scripts from the
original repository are still available for historical reference, but new
projects should import the `lego_dimensions_protocol` package instead.

Contributions are welcome!  Please open issues or pull requests describing the
hardware variant you are working with and any new commands you discover.
