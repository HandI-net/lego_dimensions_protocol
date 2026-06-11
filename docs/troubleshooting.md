# Troubleshooting LEGO Dimensions USB access

Start with:

```bash
lego-dimensions-doctor --verbose
lego-dimensions-doctor --json > doctor-report.json
```

Attach `doctor-report.json` to issue reports when possible.

## Common errors

### `ModuleNotFoundError: No module named 'usb'`

PyUSB is not installed in the active Python environment. Install this package or
PyUSB into the same environment used to run the command:

```bash
python -m pip install pyusb
```

### `NoBackendError`

PyUSB is installed, but it cannot load libusb. Install libusb for your platform:
Linux distribution packages, `brew install libusb` on macOS, or a suitable
Windows USB backend/driver.

### `PortalNotFoundError` or no portal candidates

The portal is not connected, is using an unexpected product ID, or the current
user cannot see it. Replug the portal, verify the USB cable, and run the doctor
with the known IDs:

```bash
lego-dimensions-doctor --vendor-id 0x0E6F --product-id 0x0241
```

### Permission denied or interface claim failures

On Linux, install udev rules from `docs/platform-setup.md`, reload them, and
replug the portal. On Windows, verify the portal interface has a compatible
WinUSB/libusb driver. Close other programs that might have claimed the device.

### Kernel driver active

The gateway attempts to detach and reattach kernel drivers when supported by the
backend. If that fails, check permissions or run the command from a session that
has device-management rights.

### Read endpoint silence or RFID timeout warnings

No RFID activity during the doctor command is a warning, not a hard failure. It
usually means no tag was placed on the portal during the read window. Try:

```bash
lego-dimensions-doctor --rfid-timeout 3000
```

### Lights stay on after an interrupted command

Most new diagnostics and presets blank pads in `finally` cleanup. You can always
run a blank preset once USB access works:

```bash
pad preset blank
```

## One portal vs. three pad zones

A single portal has three pad zones: centre, left, and right. Future multi-unit
support means multiple physical USB portals at the same time. Current commands
usually target one physical portal unless explicitly documented otherwise.
