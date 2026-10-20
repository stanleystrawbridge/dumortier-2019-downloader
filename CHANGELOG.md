# Changelog

## 0.2.0 — prepared 20 October 2026

Initial repository-ready pre-release package.

The default invocation now asks for a destination and offers to download after confirmation.
Use `--inventory-only` for the earlier metadata-only behaviour.
`--download` remains available for compatibility.

Added a portable reference inventory and reuse of local metadata.
All known nested listings are checked on normal runs, with automatic full refresh on detected listing changes and an explicit `--refresh-inventory` option.
The missing original HTML fingerprints in the bundled reference are documented rather than represented as verified hashes.

Added Windows and Bash launchers using an isolated local environment.
Removed the earlier machine-specific destination.
Added GPL-3.0-only licensing, manuscript and team attribution, citation metadata, tests, and cross-platform test workflow configuration.

Retained sequential downloads, source scoping, retry/range handling, local checksum records and existing-file protection.
Added completed-partial recovery, destination validation, manifest validation and additional path-safety checks.

The revised package does not yet have a confirmed end-to-end live-repository download.
See TESTING.md before treating it as a validated public release.
