# Getting this into HACS

Two different things go by "on HACS", and only the first is needed to install
it:

1. **As a custom repository.** Anyone can add this repository to their own HACS
   and install from it today. Nothing further is required.
2. **In the HACS default store.** Listed by default, searchable without adding
   a URL first. That needs a pull request against
   [hacs/default](https://github.com/hacs/default), and the checklist below.

## Installing it as a custom repository

HACS → three-dot menu → **Custom repositories** → add
`https://github.com/Robbe654321/lifepowr-flexio-ha`, category **Integration**.
Install **LIFEPOWR FlexiO** and restart Home Assistant.

## Checklist for the default store

HACS's [inclusion requirements](https://www.hacs.xyz/docs/publish/include/) and
[integration requirements](https://www.hacs.xyz/docs/publish/integration/), as
they stand against this repository:

| Requirement | State |
| --- | --- |
| Public GitHub repository | ✅ |
| Repository description set | ✅ |
| Issues enabled | ✅ |
| Repository topics set | ✅ |
| One integration under `custom_components/` | ✅ `custom_components/lifepowr/` |
| `hacs.json` present | ✅ |
| `manifest.json` with `domain`, `name`, `documentation`, `issue_tracker`, `codeowners`, `version` | ✅ |
| `custom_components/lifepowr/brand/icon.png` present | ✅ 256×256, with `icon@2x.png` at 512×512 |
| **HACS Action** passing | ✅ in `.github/workflows/validate.yml` |
| **Hassfest** passing | ✅ same workflow |
| A published GitHub **release** | ⬜ **the one thing still to do** |
| Submitted from the owner's own account, not an organisation | — yours to do |

### Cutting the release

`manifest.json` is already at `0.2.0` and the changelog has its section. The
release workflow refuses to publish if the tag and the manifest disagree, so
the tag has to match exactly:

```console
$ git checkout main && git pull
$ git tag v0.2.0
$ git push origin v0.2.0
```

That triggers `.github/workflows/release.yml`, which builds `lifepowr.zip` from
`custom_components/lifepowr/` and publishes a GitHub release with generated
notes. A tag alone is not enough for HACS — it wants a full release, which the
workflow creates.

### Submitting

Fork [hacs/default](https://github.com/hacs/default), add
`Robbe654321/lifepowr-flexio-ha` to the `integration` file **in alphabetical
order**, and open a pull request from a branch off `master`, following its
template. The submission has to come from your own account.

Their automated checks re-run the manifest, JSON formatting, sort order and
ownership validation. Once merged, the repository is picked up by the next
scheduled HACS scan.

## Brand icons are a separate pull request

Home Assistant loads integration icons from
[brands.home-assistant.io](https://brands.home-assistant.io), not from this
repository, so until the icons in `custom_components/lifepowr/brand/` are
merged into
[home-assistant/brands](https://github.com/home-assistant/brands) the
integrations list shows a placeholder. HACS accepts the repository either way —
`custom_components/lifepowr/brand/icon.png` here is what satisfies its own
requirement.

[`custom_components/lifepowr/brand/README.md`](../custom_components/lifepowr/brand/README.md)
covers that submission.
