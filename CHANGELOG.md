# Changelog

## 0.8.1 — 2026-10-10

### Changed

- Unknown commands now print `такой команда нет, вот такие есть:` followed by the same command list as `sisync list`, including for unknown `cron` and `files` subcommands. Keep exit code 2 and report the error without requiring a valid configuration.

## 0.8.0 — 2026-10-10

### Added

- `sisync files list` prints configured files as `name -> machine-path`, one per line in configuration order, with `~/` expanded to the current home directory.
- List files locally without synchronizing or contacting Git. An empty file configuration produces no output; missing or invalid configurations report an error.

## 0.7.0 — 2026-10-10

### Added

- `sisync cron stop` removes the managed SISYNC block from crontab while preserving unrelated jobs, comments, and environment settings.
- Allow stopping cron with a missing or invalid configuration. Repeated stops succeed without rewriting the crontab; malformed SISYNC blocks are rejected without changes.

## 0.6.0 — 2026-10-10

### Added

- Automatically clear `~/.sisync/sisync.log` when logged output reaches 1 MB (1,000,000 bytes), checking before logging and after each line, including errors.
- Keep the same log file and continue appending without backups. Existing cron entries need no changes after upgrading sisync; terminal output and unrelated redirected files are unaffected.

## 0.5.0 — 2026-10-10

### Added

- `sisync from <repo-link>` downloads `sisync.config.yaml` from the root of the repository's default branch into `~/.sisync`, creating the directory when needed.
- Validate the downloaded configuration before atomically replacing any existing config, preserve its contents and Git timestamp, and share the synchronization lock with `sisync update`.
- Support SSH and HTTPS Git access without requiring a local config. Import only the config; run `sisync update` separately to synchronize files.

## 0.4.0 — 2026-10-10

### Added

- `sisync config` opens `~/.sisync/sisync.config.yaml` in Vim with the current terminal and returns the editor's exit code.
- Allow editing a missing or invalid configuration, creating `~/.sisync` if needed, and report a clear error when Vim is unavailable.

## 0.3.1 — 2026-10-10

### Fixed

- Resolve the SSH agent from the current user's GUI launchd domain when macOS cron cannot obtain it through `launchctl getenv`. Cron runs outside the login session, so clearing environment variables in a terminal was insufficient to reproduce the failure.
- Preserve explicitly configured agents and allow identity-file authentication when no GUI agent is available. No key passwords are stored or requested by sisync.

## 0.3.0 — 2026-10-10

### Added

- `sisync log` prints `~/.sisync/sisync.log` without requiring a valid configuration, preserving existing timestamps and line breaks.
- If no log exists yet, report its path without creating a file.

### Changed

- Unknown commands, including unknown cron subcommands, print `такой команды нет, run sisync list` and exit with code 2, even when the configuration is missing or invalid.

## 0.2.0 — 2026-10-10

### Added

- `sisync version` prints the installed version without requiring a configuration file.
- Sync messages and errors include local timestamps with a UTC offset on every line.

### Fixed

- macOS cron runs discover the login session's SSH agent through launchd when `SSH_AUTH_SOCK` is missing, allowing Git to use keys already loaded in the agent.
- `sisync --version` works with a missing or invalid configuration file.
- Log output is flushed immediately to preserve the order of sync messages and errors.

### Maintenance

- Package metadata and CLI output share one version source.
- Start this changelog and require a version bump and changelog entry for each future delivered change.

## 0.1.0 — Previous baseline

- Synchronize configuration and selected files through Git, choosing the newer file version by timestamp.
- Install and inspect scheduled synchronization with `sisync cron start` and `sisync cron status`.
- Discover commands with `sisync list`.
- Provide a shell installer for macOS.
