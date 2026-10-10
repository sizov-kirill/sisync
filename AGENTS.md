# Versioning and changelog

- Every delivered change must bump the version and update `CHANGELOG.md` in the same change, including fixes and documentation changes.
- Bump once per delivered task; intermediate edits and tests within that task share the same version.
- Use semantic versioning: patch for fixes and maintenance, minor for backward-compatible features, major for breaking changes.
- The version source is `lib/src/sisync/__init__.py`; package metadata reads it through Hatch. Keep `sisync version` and `sisync --version` consistent with the installed package version.
- Add a dated changelog entry describing user-visible changes. Do not invent historical release dates or versions.
- Run the relevant tests before reinstalling the local CLI or delivering the change.
