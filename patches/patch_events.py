#!/usr/bin/env python3
"""Patch minuitwrp/events.cpp to blacklist conflicting sensor/cover-touch inputs on b6q."""
import pathlib
import sys

BLACKLIST = [
    "bma250",
    "bma150",
    "hbtp_vm",
    "als_rear",
    "akm-digital-hall",
    "certify_hall",
    "flip",
    "meta_event",
    "sec_touchpad",
    "sec_touchproximity",
    "sec_touchproximity2",
    "sec_touchscreen2",
    "sec_vibrator_inputff",
]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <path/to/events.cpp>")
    events_path = pathlib.Path(sys.argv[1])
    src = events_path.read_text(encoding="utf-8")
    target = '    if (strcmp(e->deviceName, "bma250") == 0 || strcmp(e->deviceName, "bma150") == 0)'
    if target not in src:
        if "sec_touchscreen2" in src:
            print(f"{events_path} already patched.")
            return
        raise SystemExit(f"ERROR: expected blacklist line not found in {events_path}")

    cond = " || ".join(f'strcmp(e->deviceName, "{name}") == 0' for name in BLACKLIST)
    events_path.write_text(src.replace(target, f"    if ({cond})", 1), encoding="utf-8")
    print(f"Patched {events_path} with {len(BLACKLIST)} blacklisted input devices.")


if __name__ == "__main__":
    main()
