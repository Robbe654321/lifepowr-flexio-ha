# FlexiO Device API — field notes

What the box actually does, versus what
[docs.lifepowr.io](https://docs.lifepowr.io/user/v1/flexio-api) says it does.
Recorded against **firmware 1.148.10**, driving a Goodwe GW12K-ET-20.

The on-device OpenAPI document at `http://myio.local/api/docs` is closer to the
truth than the website, but still silent on units and sign convention.

## Discrepancies

| The website says | The box does |
| --- | --- |
| `GET /api/ems` | `GET /api/ems/measurements` |
| `GET`/`PUT` `/api/ems/load_control` | `GET`/`POST` `/api/ems/generic-load` |
| Write with `PUT` | Write with `POST`, body `{"newMaxPrice": n}` |
| `totalInvPowerFiltered` | `TotalInvPowerFiltered` — leading capital |
| `powetSetpoint` | Does not exist (typo for `powerSetpoint`, also absent) |
| `consumptionElectrictyPrice` | `consumptionElectricityPrice` |
| **kW for every power field** | **watts** |

The OpenAPI document has one of its own: it declares `builtTime`, the box sends
`buildTime`.

Neither source mentions that `/api/ems/measurements` and
`/api/ems/generic-load` both carry a `timestamp`, that it is in
**milliseconds**, or that the two are a second or so apart.

## The complete API

Five operations. There is nothing else.

| Method | Path | Response |
| --- | --- | --- |
| GET | `/api/info/version` | `{"version": "1.148.10", "buildTime": 1788366289701}` |
| GET | `/api/info/converter` | `{"converter": "Goodwe GW12K-ET-20"}` |
| GET | `/api/ems/measurements` | 10 fields, below |
| GET | `/api/ems/generic-load` | `genericLoadMaximumElectricityPrice`, `powerSetpointGeneric`, `timestamp` |
| POST | `/api/ems/generic-load` | `{"genericLoadMaximumElectricityPrice": n}` |

`POST` returns **400** for a negative price and **500** when no values are
available. `GET /api/ems/measurements` returns **500** when no measurements are
available. Unknown paths return an nginx/Express **404 as HTML**, not JSON —
worth knowing if you write your own client.

There is no authentication of any kind.

## Measurement fields

Sample taken while the house drew 3 kW and the battery charged at 3.5 kW:

| Field | Sample | Unit | Sign |
| --- | --- | --- | --- |
| `totalPVPowerFiltered` | 1160.6 | W | positive = producing |
| `LoadPowerFiltered` | −3002.1 | W | negative = consuming |
| `MeterPowerFiltered` | −5341.3 | W | negative = importing |
| `TotalInvPowerFiltered` | −2456.2 | W | negative = charging |
| `batteryVoltageInvFiltered` | 421.4 | V | |
| `batteryCurrentInvFiltered` | −8.31 | A | negative = charging |
| `stateOfChargeFiltered` | 18.68 | % | |
| `stateOfHealthFiltered` | 100.0 | % | |
| `consumptionElectricityPrice` | 0.168 | €/kWh | |
| `timestamp` | 1788521155668 | ms | |

Values are unrounded floats; `stateOfHealthFiltered` came back as
`100.00000000029866`.

## Deriving the units and signs

The API states neither. Two identities settle both at once:

```
grid       ≈ load + inverter        -5341 ≈ -5458   (2.2%, filter lag)
battery DC ≈ inverter - PV          -3500 ≈ -3617   (3.3%, conversion loss)
```

where `battery DC = 421.4 V × -8.31 A = -3500 W`.

The battery is absorbing 3.5 kW. The inverter supplies it from 2456 W of grid
power plus 1161 W of solar, and the 117 W shortfall is the conversion loss —
the same 117 W that appears in the grid identity. Both close only if the values
are watts and consumption is negative.

A useful sanity check in the other direction: at 5341 *kilowatts* the house
would be drawing more than a small town.

`scripts/check_box.py` runs both identities against a live box.

## What the integration does with this

- Reports watts.
- Negates `MeterPowerFiltered` and `LoadPowerFiltered` so grid import and
  household consumption are positive, matching Home Assistant convention.
- Leaves `TotalInvPowerFiltered` alone — positive already means discharging,
  which is what Home Assistant's battery handling expects.
- Matches field names case- and separator-insensitively, so a firmware that
  renames `TotalInvPowerFiltered` to `total_inv_power_filtered` still works.
- Treats a timestamp above 1e11 as milliseconds and below it as seconds.

## Still unknown

- The upper bound the box accepts for `newMaxPrice`. The integration caps the
  `number` entity at 5 €/kWh as a sanity limit; the API documents no maximum.
- Whether any firmware reports kilowatts after all. Nothing detects this yet.
- What mDNS service type the box advertises, which would allow zeroconf
  discovery instead of asking for a hostname.
- Whether `powerSetpoint` exists on any firmware. It is documented on the
  website, absent from the OpenAPI spec, and absent from 1.148.10. The alias is
  kept in case it turns up.
