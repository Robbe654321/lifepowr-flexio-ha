#!/usr/bin/env python3
"""Generate the ready-made Lovelace dashboards in dashboards/.

The dashboard exists in English and Dutch. Keeping two hand-written YAML
files in step is a losing game, so both are generated from the one layout
below and only the strings differ. CI regenerates them and fails if the
committed files disagree, exactly as it does for the architecture diagram.

Everything here uses cards that ship with Home Assistant. A dashboard that
needs half of HACS installed before it renders is not one you can hand to
somebody who just wants to see their battery.

Run:  python3 scripts/make_dashboard.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# --- Entities --------------------------------------------------------------
# Entity IDs as a fresh install creates them. The integration names entities
# through translation keys, so these follow from the English names and are
# the same in every language.

PV = "sensor.flexio_solar_production"
LOAD = "sensor.flexio_household_consumption"
GRID = "sensor.flexio_grid_power"
BATTERY = "sensor.flexio_battery_power"
INVERTER = "sensor.flexio_inverter_power_total_ac"
SETPOINT = "sensor.flexio_inverter_setpoint"
GENERIC_LOAD = "sensor.flexio_generic_load_available_power"
SOC = "sensor.flexio_battery_state_of_charge"
SOH = "sensor.flexio_battery_state_of_health"
VOLTAGE = "sensor.flexio_battery_voltage"
CURRENT = "sensor.flexio_battery_current"
PRICE = "sensor.flexio_electricity_price"
CONVERTER = "sensor.flexio_converter"
LAST_SEEN = "sensor.flexio_last_measurement"
MAX_PRICE = "number.flexio_generic_load_maximum_price"

PV_KWH = "sensor.flexio_solar_production_energy"
LOAD_KWH = "sensor.flexio_household_consumption_energy"
IMPORT_KWH = "sensor.flexio_grid_import_energy"
EXPORT_KWH = "sensor.flexio_grid_export_energy"
CHARGE_KWH = "sensor.flexio_battery_charge_energy"
DISCHARGE_KWH = "sensor.flexio_battery_discharge_energy"

# --- Strings ---------------------------------------------------------------
# One key per piece of text. Both dictionaries carry the same keys; the
# generator asserts that, so a new string cannot be added to one language and
# forgotten in the other.

EN: dict[str, str] = {
    "title": "FlexiO Energy",
    "view_now": "Now",
    "view_energy": "Energy",
    "view_battery": "Battery",
    "view_system": "System",
    "h_live": "Live power",
    "h_flow": "The last three hours",
    "h_today": "So far today",
    "h_month": "Day by day",
    "h_energy_cards": "Energy dashboard",
    "h_battery_state": "State of the battery",
    "h_battery_flow": "Charging and discharging",
    "h_battery_history": "Day by day",
    "h_inverter": "Inverter and grid",
    "h_price": "Price and the generic load",
    "h_diagnostics": "Diagnostics",
    "solar": "Solar",
    "house": "House",
    "grid": "Grid",
    "battery": "Battery",
    "soc": "Charge",
    "soh": "Health",
    "voltage": "Voltage",
    "current": "Current",
    "inverter": "Inverter, total AC",
    "setpoint": "Inverter setpoint",
    "generic_load": "Generic load available",
    "price": "Electricity price",
    "max_price": "Generic load price cap",
    "converter": "Converter",
    "last_seen": "Last measurement",
    "produced": "Produced",
    "consumed": "Consumed",
    "imported": "Imported",
    "exported": "Exported",
    "charged": "Charged",
    "discharged": "Discharged",
    "power_flow": "Power",
    "battery_charge": "Battery charge",
    "note_energy": (
        "### Set this up once\n\n"
        "These cards read Home Assistant's own energy configuration, so they "
        "stay empty until you fill it in under **Settings → Dashboards → "
        "Energy**:\n\n"
        "| Slot | Entity |\n| --- | --- |\n"
        "| Grid consumption | `sensor.flexio_grid_import_energy` |\n"
        "| Return to grid | `sensor.flexio_grid_export_energy` |\n"
        "| Solar production | `sensor.flexio_solar_production_energy` |\n"
        "| Battery: energy in | `sensor.flexio_battery_charge_energy` |\n"
        "| Battery: energy out | `sensor.flexio_battery_discharge_energy` |\n\n"
        "The totals start at zero the day you install the integration — the "
        "box reports live values only, so there is no history to backfill. "
        "Statistics are compiled hourly, so give it until the next full hour "
        "before deciding something is broken."
    ),
    "note_inverter": (
        "### Why there are two of these\n\n"
        "**Inverter, total AC** is everything the inverter is moving, with "
        "the solar production already inside it. **Battery** is the "
        "battery's own flow, `inverter − solar`, which is the number the "  # noqa: RUF001
        "FlexiO app shows and the one the energy totals are built from.\n\n"
        "On a sunny afternoon the inverter reads strongly positive while the "
        "battery sits at nearly zero. Reading the inverter as the battery is "
        "what makes a battery appear to deliver several times more energy "
        "than it ever absorbed."
    ),
    "note_missing": (
        "Cards for a measurement your firmware does not report show as "
        "unavailable. The inverter setpoint, the generic load and the "
        "electricity price are the usual ones; the last measurement is "
        "disabled by default and can be enabled on the device page."
    ),
}

NL: dict[str, str] = {
    "title": "FlexiO Energie",
    "view_now": "Nu",
    "view_energy": "Energie",
    "view_battery": "Batterij",
    "view_system": "Systeem",
    "h_live": "Vermogen nu",
    "h_flow": "De afgelopen drie uur",
    "h_today": "Vandaag tot nu toe",
    "h_month": "Dag per dag",
    "h_energy_cards": "Energiedashboard",
    "h_battery_state": "Toestand van de batterij",
    "h_battery_flow": "Laden en ontladen",
    "h_battery_history": "Dag per dag",
    "h_inverter": "Omvormer en net",
    "h_price": "Prijs en de generieke last",
    "h_diagnostics": "Diagnostiek",
    "solar": "Zon",
    "house": "Huis",
    "grid": "Net",
    "battery": "Batterij",
    "soc": "Lading",
    "soh": "Gezondheid",
    "voltage": "Spanning",
    "current": "Stroom",
    "inverter": "Omvormer, totaal AC",
    "setpoint": "Setpoint omvormer",
    "generic_load": "Generieke last beschikbaar",
    "price": "Elektriciteitsprijs",
    "max_price": "Prijsplafond generieke last",
    "converter": "Omvormer",
    "last_seen": "Laatste meting",
    "produced": "Geproduceerd",
    "consumed": "Verbruikt",
    "imported": "Afgenomen",
    "exported": "Teruggeleverd",
    "charged": "Geladen",
    "discharged": "Ontladen",
    "power_flow": "Vermogen",
    "battery_charge": "Lading batterij",
    "note_energy": (
        "### Dit stel je één keer in\n\n"
        "Deze kaarten lezen de energie-instellingen van Home Assistant zelf, "
        "dus ze blijven leeg tot je die invult onder **Instellingen → "
        "Dashboards → Energie**:\n\n"
        "| Veld | Entiteit |\n| --- | --- |\n"
        "| Netafname | `sensor.flexio_grid_import_energy` |\n"
        "| Teruglevering | `sensor.flexio_grid_export_energy` |\n"
        "| Zonneproductie | `sensor.flexio_solar_production_energy` |\n"
        "| Batterij: energie in | `sensor.flexio_battery_charge_energy` |\n"
        "| Batterij: energie uit | `sensor.flexio_battery_discharge_energy` |\n\n"
        "De tellers beginnen op nul op de dag dat je de integratie "
        "installeert — de box geeft alleen live waarden, er valt geen "
        "geschiedenis in te halen. Statistieken worden per uur samengesteld, "
        "dus wacht tot het volgende hele uur voor je concludeert dat er iets "
        "stuk is."
    ),
    "note_inverter": (
        "### Waarom er hier twee staan\n\n"
        "**Omvormer, totaal AC** is alles wat de omvormer verplaatst, met de "
        "zonneproductie er al in. **Batterij** is de stroom van de batterij "
        "zelf, `omvormer − zon`, en dat is het getal dat de FlexiO-app toont "  # noqa: RUF001
        "en waarop de energietellers gebouwd zijn.\n\n"
        "Op een zonnige namiddag staat de omvormer flink positief terwijl de "
        "batterij bijna op nul zit. De omvormer voor de batterij aanzien is "
        "precies wat een batterij vele malen meer energie laat leveren dan ze "
        "ooit heeft opgenomen."
    ),
    "note_missing": (
        "Kaarten voor een meting die jouw firmware niet doorgeeft staan op "
        "niet beschikbaar. Het setpoint van de omvormer, de generieke last en "
        "de elektriciteitsprijs zijn de gebruikelijke; de laatste meting staat "
        "standaard uit en kun je op de apparaatpagina aanzetten."
    ),
}


# --- Card helpers ----------------------------------------------------------


def tile(
    entity: str,
    name: str,
    color: str,
    *,
    trend: bool = False,
    wide: bool = False,
) -> dict[str, Any]:
    """Return one measurement, shown as a tile.

    ``trend`` adds the sparkline feature, which draws the last 24 hours inside
    the tile. It only accepts numeric sensors, and it needs Home Assistant
    2025.10 or newer -- see the note in the generated header.

    ``wide`` spans the section without a sparkline, for a value that has no
    interesting shape to draw. It keeps a column of tiles the same width when
    only some of them carry a trend.
    """
    if trend:
        # A sparkline needs the full width of the section to be readable, and
        # its own row underneath the state rather than squeezed beside it.
        return {
            "type": "tile",
            "entity": entity,
            "name": name,
            "color": color,
            "features": [{"type": "trend-graph"}],
            "features_position": "bottom",
            "grid_options": {"columns": 12},
        }
    return {
        "type": "tile",
        "entity": entity,
        "name": name,
        "color": color,
        "vertical": not wide,
        "grid_options": {"columns": 12 if wide else 6, "rows": 1 if wide else 2},
    }


def only_if_present(card: dict[str, Any], entity: str) -> dict[str, Any]:
    """Hide a card when its entity is missing, rather than showing an error.

    Not every firmware reports the inverter setpoint, the generic load or the
    price, and the last-measurement sensor is disabled by default. A missing
    entity reads as ``unknown`` to the condition, and one that exists but is
    not answering reads as ``unavailable``, so both are listed.
    """
    card["visibility"] = [
        {
            "condition": "state",
            "entity": entity,
            "state_not": ["unavailable", "unknown"],
        }
    ]
    return card


def heading(text: str, icon: str) -> dict[str, Any]:
    """Return a section title."""
    return {
        "type": "heading",
        "heading": text,
        "heading_style": "title",
        "icon": icon,
    }


def today(entity: str, name: str) -> dict[str, Any]:
    """Return a kWh total's change over the current calendar day.

    ``stat_type: change`` is what makes this "today" rather than "since the
    integration was installed": it subtracts the value at midnight.
    """
    return {
        "type": "statistic",
        "entity": entity,
        "name": name,
        "stat_type": "change",
        "period": {"calendar": {"period": "day"}},
        "grid_options": {"columns": 6, "rows": 2},
    }


def daily_bars(entities: list[str], days: int = 30) -> dict[str, Any]:
    """Daily totals as stacked bars, straight from long-term statistics."""
    return {
        "type": "statistics-graph",
        "entities": entities,
        "days_to_show": days,
        "period": "day",
        "stat_types": ["change"],
        "chart_type": "bar",
        "grid_options": {"columns": "full"},
    }


def history(entities: list[str], hours: int, title: str) -> dict[str, Any]:
    """Recent history, at whatever resolution the recorder kept."""
    return {
        "type": "history-graph",
        "entities": entities,
        "hours_to_show": hours,
        "title": title,
        "grid_options": {"columns": "full"},
    }


def markdown(text: str) -> dict[str, Any]:
    """Return a block of explanatory prose."""
    return {"type": "markdown", "content": text, "grid_options": {"columns": "full"}}


def section(cards: list[dict[str, Any]], *, span: int = 1) -> dict[str, Any]:
    """Return a column of cards for a sections view."""
    return {"type": "grid", "column_span": span, "cards": cards}


# --- The dashboard ---------------------------------------------------------


def build(t: dict[str, str]) -> dict[str, Any]:
    """Assemble the whole dashboard for one set of strings."""
    return {
        "views": [
            _view_now(t),
            _view_energy(t),
            _view_battery(t),
            _view_system(t),
        ]
    }


def _view_now(t: dict[str, str]) -> dict[str, Any]:
    """Where the power is going, right now."""
    return {
        "type": "sections",
        "title": t["view_now"],
        "path": "now",
        "icon": "mdi:flash",
        "max_columns": 3,
        "sections": [
            section(
                [
                    heading(t["h_live"], "mdi:transmission-tower"),
                    tile(PV, t["solar"], "amber", trend=True),
                    tile(LOAD, t["house"], "blue", trend=True),
                    tile(GRID, t["grid"], "red", trend=True),
                    tile(BATTERY, t["battery"], "purple", trend=True),
                    {
                        "type": "gauge",
                        "entity": SOC,
                        "name": t["soc"],
                        "min": 0,
                        "max": 100,
                        "needle": True,
                        "segments": [
                            {"from": 0, "color": "var(--error-color)"},
                            {"from": 20, "color": "var(--warning-color)"},
                            {"from": 50, "color": "var(--success-color)"},
                        ],
                        "grid_options": {"columns": 12, "rows": 4},
                    },
                ]
            ),
            section(
                [
                    heading(t["h_today"], "mdi:calendar-today"),
                    today(PV_KWH, t["produced"]),
                    today(LOAD_KWH, t["consumed"]),
                    today(IMPORT_KWH, t["imported"]),
                    today(EXPORT_KWH, t["exported"]),
                    today(CHARGE_KWH, t["charged"]),
                    today(DISCHARGE_KWH, t["discharged"]),
                ]
            ),
            section(
                [
                    heading(t["h_flow"], "mdi:chart-line"),
                    history([PV, LOAD, GRID, BATTERY], 3, t["power_flow"]),
                    history([SOC], 3, t["battery_charge"]),
                ]
            ),
        ],
    }


def _view_energy(t: dict[str, str]) -> dict[str, Any]:
    """Home Assistant's own energy cards, plus the raw daily totals.

    The energy cards read the energy preferences rather than any entity given
    here, which is why the note card explains what to fill in.
    """
    return {
        "type": "sections",
        "title": t["view_energy"],
        "path": "energy",
        "icon": "mdi:lightning-bolt",
        "max_columns": 2,
        "sections": [
            section(
                [
                    heading(t["h_energy_cards"], "mdi:home-lightning-bolt"),
                    {"type": "energy-date-selection"},
                    {"type": "energy-distribution", "link_dashboard": True},
                    {"type": "energy-usage-graph"},
                    {"type": "energy-solar-graph"},
                    {"type": "energy-sources-table"},
                ]
            ),
            section(
                [
                    heading(t["h_month"], "mdi:chart-bar"),
                    daily_bars([PV_KWH, LOAD_KWH]),
                    daily_bars([IMPORT_KWH, EXPORT_KWH]),
                    daily_bars([CHARGE_KWH, DISCHARGE_KWH]),
                    markdown(t["note_energy"]),
                ]
            ),
        ],
    }


def _view_battery(t: dict[str, str]) -> dict[str, Any]:
    """Everything the box knows about the battery itself."""
    return {
        "type": "sections",
        "title": t["view_battery"],
        "path": "battery",
        "icon": "mdi:battery-high",
        "max_columns": 3,
        "sections": [
            section(
                [
                    heading(t["h_battery_state"], "mdi:battery-heart-variant"),
                    {
                        "type": "gauge",
                        "entity": SOC,
                        "name": t["soc"],
                        "min": 0,
                        "max": 100,
                        "needle": True,
                        "segments": [
                            {"from": 0, "color": "var(--error-color)"},
                            {"from": 20, "color": "var(--warning-color)"},
                            {"from": 50, "color": "var(--success-color)"},
                        ],
                        "grid_options": {"columns": 12, "rows": 4},
                    },
                    tile(SOH, t["soh"], "green", wide=True),
                    tile(VOLTAGE, t["voltage"], "cyan", trend=True),
                    tile(CURRENT, t["current"], "cyan", trend=True),
                    tile(BATTERY, t["battery"], "purple", trend=True),
                ]
            ),
            section(
                [
                    heading(t["h_battery_flow"], "mdi:battery-charging"),
                    today(CHARGE_KWH, t["charged"]),
                    today(DISCHARGE_KWH, t["discharged"]),
                    history([BATTERY], 12, t["power_flow"]),
                ]
            ),
            section(
                [
                    heading(t["h_battery_history"], "mdi:chart-bar"),
                    daily_bars([CHARGE_KWH, DISCHARGE_KWH]),
                    history([SOC], 24, t["battery_charge"]),
                ]
            ),
        ],
    }


def _view_system(t: dict[str, str]) -> dict[str, Any]:
    """Show the inverter reading, the writable price cap and the diagnostics."""
    return {
        "type": "sections",
        "title": t["view_system"],
        "path": "system",
        "icon": "mdi:cog",
        "max_columns": 2,
        "sections": [
            section(
                [
                    heading(t["h_inverter"], "mdi:solar-power-variant"),
                    tile(INVERTER, t["inverter"], "deep-orange", trend=True),
                    tile(BATTERY, t["battery"], "purple", trend=True),
                    tile(GRID, t["grid"], "red", trend=True),
                    only_if_present(tile(SETPOINT, t["setpoint"], "grey"), SETPOINT),
                    history([INVERTER, PV, BATTERY], 6, t["power_flow"]),
                    markdown(t["note_inverter"]),
                ]
            ),
            section(
                [
                    heading(t["h_price"], "mdi:currency-eur"),
                    only_if_present(
                        tile(PRICE, t["price"], "green", trend=True), PRICE
                    ),
                    only_if_present(
                        tile(GENERIC_LOAD, t["generic_load"], "teal"), GENERIC_LOAD
                    ),
                    only_if_present(
                        {
                            "type": "tile",
                            "entity": MAX_PRICE,
                            "name": t["max_price"],
                            "features": [{"type": "numeric-input", "style": "buttons"}],
                            "grid_options": {"columns": "full"},
                        },
                        MAX_PRICE,
                    ),
                    only_if_present(history([PRICE], 24, t["price"]), PRICE),
                    heading(t["h_diagnostics"], "mdi:information-outline"),
                    only_if_present(
                        tile(CONVERTER, t["converter"], "grey", wide=True),
                        CONVERTER,
                    ),
                    only_if_present(
                        tile(LAST_SEEN, t["last_seen"], "grey", wide=True),
                        LAST_SEEN,
                    ),
                    markdown(t["note_missing"]),
                ]
            ),
        ],
    }


# --- YAML ------------------------------------------------------------------
# Written by hand rather than with PyYAML, so the generator has no third-party
# dependency and CI needs nothing installed to check it -- the same reason
# scripts/check_box.py sticks to the standard library.

_SPECIAL = set("!&*{}[],#|>@`\"'%:")


def _scalar(value: Any) -> str:
    """Render one scalar, quoting only where YAML needs it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    needs_quotes = (
        not text
        or text[0] in _SPECIAL
        or ": " in text
        or text.endswith(":")
        or text.strip() != text
        or text.lower() in {"true", "false", "null", "yes", "no", "on", "off"}
    )
    if needs_quotes:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _block(text: str, indent: str) -> list[str]:
    """Render a multi-line string as a literal block, newlines intact."""
    return ["|-"] + [f"{indent}{line}".rstrip() for line in text.split("\n")]


def _dump(node: Any, indent: int = 0) -> list[str]:
    """Render a dict/list/scalar tree as YAML lines."""
    pad = "  " * indent
    out: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, (dict, list)) and value:
                out.append(f"{pad}{key}:")
                out.extend(_dump(value, indent + 1))
            elif isinstance(value, str) and "\n" in value:
                head, *rest = _block(value, "  " * (indent + 1))
                out.append(f"{pad}{key}: {head}")
                out.extend(rest)
            else:
                out.append(f"{pad}{key}: {_scalar(value)}")
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, dict):
                rendered = _dump(item, indent + 1)
                first = rendered[0].lstrip()
                out.append(f"{pad}- {first}")
                out.extend(rendered[1:])
            else:
                out.append(f"{pad}- {_scalar(item)}")
    else:
        out.append(f"{pad}{_scalar(node)}")
    return out


HEADER = """# {title}
#
# Generated by scripts/make_dashboard.py -- edit that, not this file.
#
# Settings -> Dashboards -> Add dashboard -> New dashboard from scratch,
# then open it, three-dot menu -> Edit -> three-dot menu -> Raw configuration
# editor, and replace everything there with this file.
#
# Every card here ships with Home Assistant; nothing extra to install.
# Needs Home Assistant 2025.10 or newer for the sparklines inside the tiles.
# On anything older those tiles show an unknown-feature error and the rest of
# the dashboard still works; delete the two "features" lines to silence them.
# Entity IDs are the ones a fresh install creates. If yours differ -- a second
# FlexiObox, or an install predating the inverter rename -- adjust them here.
"""


def main() -> None:
    """Write both languages into dashboards/."""
    out = Path(__file__).resolve().parent.parent / "dashboards"
    out.mkdir(exist_ok=True)
    assert EN.keys() == NL.keys(), "the two languages have drifted apart"
    for name, strings in (("energy", EN), ("energy-nl", NL)):
        body = "\n".join(_dump(build(strings)))
        header = HEADER.format(title=strings["title"])
        (out / f"{name}.yaml").write_text(f"{header}\n{body}\n")
    print(f"wrote {out}/energy.yaml and {out}/energy-nl.yaml")


if __name__ == "__main__":
    main()
