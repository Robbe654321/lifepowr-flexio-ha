# Brand assets

These are the icons Home Assistant shows for this integration. They live inside
the integration directory because that is where the HACS action looks for them
(`custom_components/<domain>/brand/icon.png`); found there, it stops asking
whether the domain is in the brands repository yet.

Home Assistant itself does **not** read them from this repository — it loads them from
[brands.home-assistant.io](https://brands.home-assistant.io), which is fed by
the [home-assistant/brands](https://github.com/home-assistant/brands) repo.

Until they are merged there, Home Assistant shows a generic placeholder.

## Submitting them

1. Fork [home-assistant/brands](https://github.com/home-assistant/brands).
2. Copy both files to `custom_integrations/lifepowr/`, keeping the names.
3. Open a pull request.

The domain directory must match `manifest.json` — `lifepowr`, not
`lifepowr-flexio-ha`.

## Requirements these meet

| File | Required | This |
| --- | --- | --- |
| `icon.png` | 256×256 PNG | 256×256 RGBA |
| `icon@2x.png` | 512×512 PNG | 512×512 RGBA |

Both are trimmed to their content with no transparent border, have a
transparent background outside the rounded corners, and are saved optimised.

No `logo.png` is supplied, deliberately. A logo would normally be the vendor's
wordmark, and LIFEPOWR's is their trademark to use. Home Assistant falls back
to the icon wherever a logo would appear.

## About the design

An original mark: a battery with a lightning bolt knocked out of it, chosen
because it stays readable at the 24 px Home Assistant renders it at in the
integrations list. It is not derived from any LIFEPOWR artwork, and this
project is not affiliated with LIFEPOWR.

Regenerate with `python3 scripts/make_icon.py`.
