# Shin Context Engine for Homebrew

The project-owned tap for the complete macOS preview of
[Shin Context Engine](https://github.com/toseek-samurai/shin-context-engine).
Includes Core, Observer, CLI, MCP, usage collector, Sand TUI and Shin Monitor.
The formula pins a published preview. `brew info toseek-samurai/tap/shin-context-engine`
shows the currently selected version.

```sh
brew install toseek-samurai/tap/shin-context-engine

cd /path/to/project
shin-ce init
shin-monitor
```

Requires macOS 15 or newer. The package compiles pinned sources locally, so the
first installation takes several minutes and needs Homebrew's build tools.
Use current Apple Command Line Tools (Xcode 26 or newer) with C++20 thread support.
The full Xcode application is optional when the selected Command Line Tools provide
that support; update macOS first if the required tools are unavailable.
If Homebrew asks for full Xcode because older CLT are installed, updating the CLT
to version 26 or newer also satisfies the build requirements.
The local build needs no Apple Developer ID. The tap supplies source archives
with pinned checksums. No Python or Node runtime is needed afterward.

`shin-monitor` opens the tray application; `shin-ce stats` opens the terminal
monitor. Both support English and Russian. Monitor's project setup detects
supported agents and lets you connect them while preserving existing settings.
Installation itself does not start services or change agent configuration.

## Background startup

`shin-ce init` starts a session service. To run the background service at login:

```sh
shin-ce service-stop
brew services start toseek-samurai/tap/shin-context-engine
```

This starts the service, not the GUI. Open Monitor with `shin-monitor`.
The Homebrew package does not register Monitor as a native-kit login item.

## Upgrade and remove

Quit Monitor and TUI before upgrading. If using a session service, stop it with
`shin-ce service-stop` first.

```sh
brew update
brew upgrade toseek-samurai/tap/shin-context-engine
```

Restart a login service with `brew services restart
toseek-samurai/tap/shin-context-engine`, or a session service with
`shin-ce service-start`. Open `shin-monitor` again. Reconnect an older MCP
integration if it reports a version mismatch. Saved executable paths use the
stable Homebrew opt prefix.

Homebrew owns the package. Shin's native installer and Updater are disabled in
this build; Monitor and TUI show the appropriate Homebrew command instead.

To remove the package, quit Monitor/TUI and stop its session service, or run
`brew services stop toseek-samurai/tap/shin-context-engine` for a login service.
Then run:

```sh
brew uninstall toseek-samurai/tap/shin-context-engine
```

Project files, agent settings and the private data home (`~/.shin-ce` by default)
are preserved. Disconnect projects through Shin before removal if you also want
to detach their integrations.

## Existing native installation

This formula does not migrate or replace a native preview kit. Do not run two
installations against the same data home or managed indexes. Existing
`~/.local/bin` commands may precede Homebrew on `PATH`; inspect `command -v
shin-ce` and use `"$(brew --prefix shin-context-engine)/bin/shin-ce" --version`
to identify this package. A handover of an existing kit needs a separate review
of its services, project bindings and retained history.

See the [installation guide](https://github.com/toseek-samurai/shin-context-engine/blob/main/docs/homebrew.md)
for the full lifecycle and ownership rules.

## Maintaining the recipe

The [Update preview formula workflow](https://github.com/toseek-samurai/homebrew-tap/actions/workflows/sync-preview.yml)
checks upstream hourly. Maintainers can also run it from **main** with an optional
preview tag. Normal releases need no manual Ruby edits or additional personal token.

The workflow selects a public preview only after its macOS qualification receipt
and complete platform assets are present. It checks the immutable source commit,
derives the source checksum and dependency resources from that tag's CMake files,
and tests the exact candidate formula on Apple Silicon and Intel. The existing
installation workflow covers style, audit, linkage, query/MCP, EN/RU terminal
startup, reinstall and preservation of source, client settings and history after
uninstall. Its projects, service and data are disposable.

Only after both platforms pass does the tap's own `GITHUB_TOKEN` advance the
formula on `main`. The publish step rechecks source qualification and the tap base;
a concurrent maintainer change is preserved and requires a fresh run. A pending
upstream tag, failed installation or malformed dependency pin leaves the current
formula intact. No token is copied from a developer's machine or stored as a new secret.

Version and resource updates are automatic; changes to the installer, toolchain
requirements or a new dependency declaration layout still need maintainer review.
SQLite is staged from the official amalgamation archive pinned by the source.
Synchronization verifies its SHA3-256 before deriving Homebrew's SHA-256; the
formula does not use system SQLite. The retired Server's `shin_httplib` resource
is removed from new recipes; unknown maintained resources still require review.
Do not point the recipe at a moving branch or a locally built binary. For manual
changes, run `brew style`, `brew audit --strict`, `brew test` and the complete
installation workflow before merging.

The CI workflow tests Apple Silicon and Intel from source. It does not publish
bottles, create release assets or change production client settings.

Apache-2.0. Copyright 2026 Anton Petropavlovskiy.
