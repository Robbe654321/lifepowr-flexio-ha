#!/usr/bin/env python3
"""Check a real FlexiObox against the integration's field mapping.

Standard library only -- no Home Assistant, no pip install. Run it from the
repository root on any machine that can reach the box:

    python3 scripts/check_box.py                # uses myio.local
    python3 scripts/check_box.py 192.168.1.20

It reports which endpoints answer, which fields the integration recognises,
and flags the three things the API documentation does not settle: the units of
the battery voltage/current, the unit of the timestamp, and the sign
convention of the grid and inverter power.

Nothing is written to the box unless you pass --set-max-price.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import importlib.util
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Load parsing.py by path: importing the package would pull in Home Assistant.
_SPEC = importlib.util.spec_from_file_location(
    "lifepowr_parsing",
    Path(__file__).resolve().parent.parent
    / "custom_components/lifepowr/parsing.py",
)
_P = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_P)

FIELD_NEW_MAX_PRICE = _P.FIELD_NEW_MAX_PRICE
KEY_BATTERY_CURRENT = _P.KEY_BATTERY_CURRENT
KEY_BATTERY_VOLTAGE = _P.KEY_BATTERY_VOLTAGE
KEY_GRID_POWER = _P.KEY_GRID_POWER
KEY_INVERTER_POWER = _P.KEY_INVERTER_POWER
KEY_LOAD_POWER = _P.KEY_LOAD_POWER
KEY_PV_POWER = _P.KEY_PV_POWER
KEY_TIMESTAMP = _P.KEY_TIMESTAMP
PATH_CONVERTER = _P.PATH_CONVERTER
PATH_GENERIC_LOAD = _P.PATH_GENERIC_LOAD
PATH_LEGACY_EMS = _P.PATH_LEGACY_EMS
PATH_LEGACY_LOAD_CONTROL = _P.PATH_LEGACY_LOAD_CONTROL
PATH_MEASUREMENTS = _P.PATH_MEASUREMENTS
PATH_VERSION = _P.PATH_VERSION
normalise_timestamp = _P.normalise_timestamp
parse_payload = _P.parse_payload

TIMEOUT = 10
OK = "\033[32m✓\033[0m"
BAD = "\033[31m✗\033[0m"
WARN = "\033[33m!\033[0m"


def fetch(base: str, path: str, body: dict[str, float] | None = None):
    """GET or POST a path; return (payload, error_string)."""
    url = f"{base}/{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=TIMEOUT) as r:
            raw = r.read().decode()
    except HTTPError as err:
        return None, f"HTTP {err.code}"
    except URLError as err:
        return None, f"unreachable ({err.reason})"
    except TimeoutError:
        return None, "timeout"
    try:
        return json.loads(raw), None
    except json.JSONDecodeError:
        return None, f"not JSON: {raw[:60].strip()!r}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", nargs="?", default="myio.local")
    parser.add_argument(
        "--set-max-price",
        type=float,
        metavar="EUR",
        help="write this price cap to the box (the only write this script does)",
    )
    args = parser.parse_args()

    host = args.host
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    base = f"{host}/api"
    print(f"Checking {base}\n")

    # --- Endpoints -------------------------------------------------------
    print("Endpoints")
    found = {}
    for path in (
        PATH_VERSION,
        PATH_CONVERTER,
        PATH_MEASUREMENTS,
        PATH_GENERIC_LOAD,
        PATH_LEGACY_EMS,
        PATH_LEGACY_LOAD_CONTROL,
    ):
        payload, error = fetch(base, path)
        legacy = path in (PATH_LEGACY_EMS, PATH_LEGACY_LOAD_CONTROL)
        if error:
            # The legacy paths are expected to 404 on current firmware, but an
            # unreachable host is a failure everywhere.
            expected = legacy and error.startswith("HTTP")
            print(f"  {OK if expected else BAD} /api/{path:<20} {error}")
            continue
        found[path] = payload
        print(f"  {OK} /api/{path:<20} {json.dumps(payload)[:70]}")

    if PATH_MEASUREMENTS not in found and PATH_LEGACY_EMS not in found:
        print("\nNo measurements endpoint answered. Is this a FlexiObox?")
        return 1

    measurements = found.get(PATH_MEASUREMENTS) or found.get(PATH_LEGACY_EMS)
    data = parse_payload(measurements)
    if generic := found.get(PATH_GENERIC_LOAD) or found.get(PATH_LEGACY_LOAD_CONTROL):
        load = parse_payload(generic)
        load.pop(KEY_TIMESTAMP, None)
        data |= load

    # --- Field mapping ---------------------------------------------------
    print("\nRecognised fields")
    for key, value in sorted(data.items()):
        print(f"  {OK} {key:<26} {value}")

    unknown = [
        name
        for doc in (measurements, generic or {})
        for name in doc
        if not parse_payload({name: doc[name]})
    ]
    for name in sorted(set(unknown)):
        print(f"  {WARN} {name:<26} not mapped -- please report this field")

    # --- The three open questions ---------------------------------------
    print("\nSanity checks")

    voltage = data.get(KEY_BATTERY_VOLTAGE)
    if voltage is None:
        print(f"  {WARN} battery voltage not reported")
    elif voltage > 20:
        print(f"  {OK} battery voltage {voltage} -- volts, as assumed")
    else:
        print(
            f"  {BAD} battery voltage {voltage} -- too low for volts;"
            " the sensor's unit is wrong, please report"
        )

    current = data.get(KEY_BATTERY_CURRENT)
    if current is None:
        print(f"  {WARN} battery current not reported")
    elif abs(current) > 5:
        print(f"  {OK} battery current {current} -- amperes, as assumed")
    else:
        print(
            f"  {WARN} battery current {current} -- could be amps at low load"
            " or kW; check again while the battery is charging hard"
        )

    stamp = data.get(KEY_TIMESTAMP)
    if stamp is None:
        print(f"  {WARN} no timestamp reported")
    elif (seconds := normalise_timestamp(stamp)) is None:
        print(f"  {WARN} timestamp is {stamp} -- treated as 'never set'")
    else:
        when = datetime.fromtimestamp(seconds).astimezone()
        age = (datetime.now().astimezone() - when).total_seconds()
        unit = "ms" if stamp > 1e11 else "s"
        mark = OK if -60 < age < 3600 else BAD
        print(f"  {mark} timestamp {stamp} ({unit}) -> {when:%Y-%m-%d %H:%M:%S}"
              f", {age:.0f}s old")

    grid = data.get(KEY_GRID_POWER)
    inverter = data.get(KEY_INVERTER_POWER)
    load = data.get(KEY_LOAD_POWER)
    pv = data.get(KEY_PV_POWER)

    # Units: the website documentation claims kW; real firmware reports W.
    magnitudes = [abs(v) for v in (grid, load, pv, inverter) if v]
    if not magnitudes:
        print(f"  {WARN} no power readings to check the unit against")
    elif max(magnitudes) > 100:
        print(f"  {OK} power values up to {max(magnitudes):.0f} -- watts, as assumed")
    else:
        print(
            f"  {WARN} all power values below 100 ({max(magnitudes):.2f} max)."
            " Either the house is idle, or this firmware reports kW."
            " Re-run while something heavy is on."
        )

    # Energy balance: two independent identities that should close to a few
    # percent. They confirm both the unit and the sign convention.
    if None not in (grid, load, inverter):
        drift = abs(grid - (load + inverter))
        scale = max(abs(grid), 1)
        mark = OK if drift / scale < 0.10 else BAD
        print(
            f"  {mark} balance: grid {grid:.0f} vs load+inverter"
            f" {load + inverter:.0f} ({drift / scale * 100:.1f}% off)"
        )
    if None not in (data.get(KEY_BATTERY_VOLTAGE), current, inverter, pv):
        battery_dc = data[KEY_BATTERY_VOLTAGE] * current
        ac_side = inverter - pv
        drift = abs(battery_dc - ac_side)
        scale = max(abs(battery_dc), 1)
        mark = OK if drift / scale < 0.15 else WARN
        print(
            f"  {mark} balance: battery {battery_dc:.0f} W vs inverter-PV"
            f" {ac_side:.0f} W ({drift / scale * 100:.1f}% -- conversion loss)"
        )

    # Sign convention.
    if load is not None:
        if load < 0:
            print(
                f"  {OK} load convention: consumption is negative ({load:.0f}),"
                " as expected -- the integration flips grid and load"
            )
        else:
            print(
                f"  {WARN} household consumption is positive ({load:.0f})."
                " This firmware may not use the load convention;"
                " please report it, the sensors will read inverted."
            )
    print(
        f"\n  After conversion Home Assistant will show: grid"
        f" {-grid:.0f} W ({'importing' if grid and grid < 0 else 'exporting'}),"
        f" consumption {-load:.0f} W, solar {pv:.0f} W, battery"
        f" {inverter:.0f} W ({'charging' if inverter and inverter < 0 else 'discharging'})."
    )

    # --- Optional write --------------------------------------------------
    if args.set_max_price is not None:
        print(f"\nWriting {FIELD_NEW_MAX_PRICE}={args.set_max_price}")
        payload, error = fetch(
            base, PATH_GENERIC_LOAD, {FIELD_NEW_MAX_PRICE: args.set_max_price}
        )
        if error:
            print(f"  {BAD} {error}")
            return 1
        print(f"  {OK} box confirmed {json.dumps(payload)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
