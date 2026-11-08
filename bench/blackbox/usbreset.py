#!/usr/bin/env python3
"""Host-side USB port reset of the FC (VID 0x0483) through libusb, so macOS re-enumerates its VCP.

Betaflight 4.2 F4 re-runs usbVcpOpen() (D+ disconnect pulse + USBD_Init) whenever the VCP is reopened, i.e. when
blackbox takes the shared port on arm and when MSP gets it back on disarm. On this Mac the host does not notice and
the port stays silent until the device is reset. pyusb reports "Entity not found" but the device does re-enumerate.
Needs `brew install libusb` (or uhubctl, which pulls it in) and pyusb in the venv."""
import sys
import usb.core
import usb.backend.libusb1 as L

LIB = "/opt/homebrew/lib/libusb-1.0.dylib"


def reset(vid=0x0483):
    be = L.get_backend(find_library=lambda _: LIB)
    d = usb.core.find(idVendor=vid, backend=be)
    if d is None:
        return "no device"
    try:
        d.reset()
        return "reset ok"
    except usb.core.USBError as e:
        return "reset issued (%s)" % e


if __name__ == "__main__":
    print(reset())
