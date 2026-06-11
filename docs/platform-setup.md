# Platform setup for LEGO Dimensions portals

The Python package talks to a physical LEGO Dimensions USB portal through
PyUSB. Importing the package does not require hardware, but demos, diagnostics,
RFID tracking, tag operations, and light commands require a connected portal and
a working libusb-compatible backend.

A **portal** is the physical USB toy pad. A **pad zone** is one of the three
areas on that portal: centre, left, or right. Current commands primarily target
one physical portal, but new file formats and diagnostics include `portal_id`
fields so future multi-unit support can identify several USB portals.

## First diagnostic command

After installing, run the doctor command before trying demos:

```bash
lego-dimensions-doctor
lego-dimensions-doctor --json > doctor-report.json
lego-dimensions-doctor --verbose
```

Use the JSON output in bug reports because it distinguishes missing PyUSB,
missing libusb/backend support, no portal, permission/interface errors, write
errors, and read timeouts.

Known portal IDs use vendor ID `0x0E6F` and product IDs `0x0241`, `0x0242`, and
`0x0243`.

## Linux

Install PyUSB with the package and ensure `libusb-1.0` is installed through your
distribution package manager. Common package names include `libusb-1.0-0` and
`libusb-1.0-0-dev`.

Most Linux systems also need udev permissions for non-root access. Create a file
such as `/etc/udev/rules.d/60-lego-dimensions.rules`:

```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="0e6f", ATTR{idProduct}=="0241", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0e6f", ATTR{idProduct}=="0242", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0e6f", ATTR{idProduct}=="0243", MODE="0660", GROUP="plugdev", TAG+="uaccess"
```

Then reload rules and replug the portal:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

If your distribution does not use `plugdev`, replace it with a group used for
USB device access on your system, or rely on `TAG+="uaccess"` for desktop
sessions.

## macOS

Install libusb through Homebrew:

```bash
brew install libusb
python -m pip install .
lego-dimensions-doctor
```

If the doctor reports `NoBackendError`, verify Homebrew's library path is
visible to the Python interpreter you are using.

## Windows

PyUSB needs a libusb-compatible driver for the portal. Many users install a
WinUSB/libusb driver for the LEGO Dimensions portal interface with a tool such
as Zadig. Choose only the portal device, not unrelated USB devices, and keep a
note of the original driver so you can roll back if needed.

After changing the driver, unplug/replug the portal and run:

```powershell
lego-dimensions-doctor --verbose
```

## Safety notes

Lighting diagnostics and presets briefly change portal pad lights and then blank
them in cleanup. Tag write/restore style workflows should remain dry-run by
default and require an explicit apply/confirmation option before writing.
