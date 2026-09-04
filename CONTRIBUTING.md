# Contributing

## The most useful contribution

**A reading from a FlexiObox that is not firmware 1.148.10.** This integration
was written against one box, and the vendor documentation has already been
wrong about six things. Every other firmware is an unknown.

Run this and paste the output into an issue:

```console
$ python3 scripts/check_box.py
```

It needs nothing installed — standard library only. If it warns about an
unmapped field, or the energy balances do not close, that is a real finding.

## Development

```console
$ python3 -m venv .venv && source .venv/bin/activate
$ pip install -r requirements_test.txt
$ pytest --cov=custom_components.lifepowr --cov-report=term-missing
$ ruff check . && ruff format --check .
```

CI runs `pytest`, `ruff`, Home Assistant's `hassfest`, and HACS validation on
every push. All four must pass.

## Testing against a live box without touching your real setup

Point a scratch Home Assistant at it, or just run `check_box.py`. Do not use
`--set-max-price` on a box you depend on without knowing what the generic load
controller will do with the new cap.

## Code layout

| File | Responsibility |
| --- | --- |
| `parsing.py` | Field names, aliases, endpoint paths, value coercion. **No third-party imports** — this is what makes `check_box.py` work without Home Assistant. Keep it that way. |
| `api.py` | HTTP, endpoint selection, error translation. Re-exports `parsing` for the platforms. |
| `coordinator.py` | Polling, `UpdateFailed` translation. |
| `sensor.py` / `number.py` | Entity descriptions. Unit and sign conversion live here, in `value_fn`. |
| `scripts/check_box.py` | Hardware verification. |
| `scripts/make_diagram.py` | Regenerates the README diagram in both themes. |

## Adding a field

1. Add a `KEY_*` constant and its raw spellings to `FIELD_ALIASES` in
   `parsing.py`. Matching is case- and separator-insensitive, so only add
   genuinely different spellings.
2. Add an entity description in `sensor.py` with the right `device_class` and
   `state_class`.
3. Add the `translation_key` to `strings.json`, `translations/en.json` and
   `translations/nl.json` — all three, or hassfest fails.
4. Add the field to the sample in `tests/conftest.py` and assert its unit in
   `tests/test_sensor.py`.

## Style

Home Assistant core conventions: `ruff` with the settings in `pyproject.toml`,
full type annotations, docstrings on every public callable. The integration is
written so a core submission is mostly a directory move —
`custom_components/lifepowr/quality_scale.yaml` tracks what is still missing.

## Commit messages

Say what changed and why it matters, in prose. The reason a change exists is
usually more valuable than the diff — especially here, where most changes come
from the documentation being wrong about something.
