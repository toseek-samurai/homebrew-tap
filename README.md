# Shin Context Engine for Homebrew

The project-owned tap for the complete macOS preview of
[Shin Context Engine](https://github.com/toseek-samurai/shin-context-engine).
Includes Core, Observer, CLI, MCP, usage collector, Sand TUI and Shin Monitor.

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
Apple Developer ID is not required for this local build. There are no prebuilt
bottles in this first tap. No Python or Node runtime is needed afterward.
Homebrew may ask you to trust the formula from this third-party tap.

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
`shin-ce service-start`. Open `shin-monitor` again and reconnect persistent MCP
clients. Their saved executable paths use the stable Homebrew opt prefix.

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

1. Wait for a qualified upstream release to finish publication. Do not point the
   formula at a pending tag, moving branch or a locally built binary.
2. Update the source URL, version and SHA-256 together. Keep dependency resources
   aligned with the upstream CMake declarations and pin every archive checksum.
3. Run `brew style Formula/shin-context-engine.rb`, `brew audit --strict
   toseek-samurai/tap/shin-context-engine`, a source installation and `brew test`.
4. Use `tests/installation_smoke.py --prefix "$(brew --prefix shin-context-engine)"
   --workspace /new/disposable/directory --phase seed`, reinstall the package,
   then run the same script with `--phase verify`. It checks query/MCP, EN/RU TUI,
   package update ownership and preservation of client settings, source and history.
   Its fixtures and service are isolated from existing projects.
5. Check uninstall preservation. Submit the recipe change and require the macOS
   installation workflow to pass before merging it.

The CI workflow tests Apple Silicon and Intel from source. It does not publish
bottles, create release assets or change production client settings.

Apache-2.0. Copyright 2026 Anton Petropavlovskiy.
