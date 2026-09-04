# What and why

<!-- What changes, and what problem it solves. If it comes from the vendor
documentation being wrong about something, say what the box actually does. -->

## Verified how

<!-- Tick what applies. Hardware evidence beats everything else here. -->

- [ ] `pytest` passes
- [ ] `ruff check .` passes
- [ ] Tested against a real FlexiObox (firmware: `…`, converter: `…`)
- [ ] `scripts/check_box.py` output attached below

## If this adds or changes a field

- [ ] `KEY_*` and aliases added to `parsing.py`
- [ ] Entity description added with the right `device_class` / `state_class`
- [ ] `translation_key` added to `strings.json`, `translations/en.json` **and**
      `translations/nl.json`
- [ ] Sample updated in `tests/conftest.py`, unit asserted in
      `tests/test_sensor.py`

## Anything reviewers should look at closely

<!-- Units, signs, and anything you were unsure about. -->
