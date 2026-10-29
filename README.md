# Recipkg standard-library black-box samples

**Run repeatable behavior checks against an upstream program or a reconstruction.**

[Recipkg](https://github.com/recipkg/recipkg) · [Standard library](https://github.com/recipkg/standard-library) · [Package specification](https://github.com/recipkg/recipkg/blob/main/docs/SPEC.en.md)

![Software and dependencies become a recipe for rebuilding software](https://raw.githubusercontent.com/recipkg/recipkg/main/assets/recipkg-cover.png)

Small, reproducible black-box comparisons for selected contracts in the [Recipkg standard library](https://github.com/recipkg/standard-library). The tests run candidate executables on disposable input and assert user-visible results. They do **not** establish full compatibility, source provenance, secure isolation, or independent reconstruction.

These tests currently correspond to selected observations in `recipkg/jq` v0.1.20 (upstream jq 1.8.2), `recipkg/ripgrep` v0.1.5 (upstream ripgrep 15.2.0), `recipkg/ffmpeg` v0.1.7 (upstream FFmpeg 9.0.2), `recipkg/miniflux` v0.1.7 (upstream source commit `3945f3daa0a90040f761d79a5f62a678fe86ba4e`), `recipkg/syncthing` v0.1.3 (upstream source commit `ed38528d7fba3dd6a42c9c9fc6780af432dc15d2`), and `recipkg/openhands-agent-sdk` v0.1.9 (upstream source commit `46b1fa5cb91ada17e6ec938c7e8624a4fa19fa98`); upstream builds may differ in codecs or features. The jq decnum precision sample explicitly skips targets reporting `have_decnum == false`; a skip is not a pass. Git is required for ripgrep's repository filtering test; FFmpeg needs lavfi, Matroska, WAV, PCM, volume, amix, asplit, rawvideo, RGB24, crop, scale, fps and FFV1 support. jq/ripgrep/FFmpeg/ffprobe are not bundled dependencies.

The `recipkg/valkey` v0.1.3 samples were observed on the CachyOS Valkey 9.1.2-1.1 binary; its reported source prefix is `7f1dffed`, but its complete build provenance is not independently established. Set an explicit executable to run ten finite RESP2 samples using fresh processes, disposable directories and Unix sockets. The replication sample additionally opens a temporary TCP listener on loopback:

```sh
RECIPKG_TEST_VALKEY_SERVER=/absolute/path/to/valkey-server python3 -m unittest discover -s tests -p test_valkey.py -v
```

They check selected binary values, conditional expiration, transaction errors and conflicts, scoped ACL, normal RDB/AOF restart, acknowledged AOF writes after a process kill, and local replication including replica restart and manual promotion. These cases do not validate all commands, power-loss recovery, network partition, automatic failover, security or an independent reconstruction. An unspecified target is skipped; an explicitly missing target fails.

For the opt-in real Git pin integration test, supply the Recipkg CLI and allow network access:

```sh
RECIPKG_TEST_CLI="$(command -v recipkg)" RECIPKG_TEST_GIT_PIN_NETWORK=1 python3 -m unittest discover -s tests -p test_git_pin_package.py -v
```

It fetches two fixed published Valkey recipe commits, checks their nested quality dependency and lock revisions, compares repeated archives byte for byte, and installs/builds both versions in a temporary store with Git absent from `PATH` and proxy endpoints disabled. This tests package context and version selection, not the correctness or reconstruction of Valkey.

The Vikunja API sample corresponds to `recipkg/vikunja` v0.1.3 and upstream commit `e37ebc0d10db366ff111bc4bb74a696d7cfc912e`.

The OpenClaw Gateway sample was observed with npm `openclaw@2026.10.8` (`dc2523e`), a different commit from the current `recipkg/openclaw` recipe. See that recipe's `GATEWAY-RELEASE-OBSERVED.md` for its provenance and limitations.

The optional regex samples correspond to `recipkg/regex` v0.1.1 and the upstream `regex` 1.13.0 crate. Set `RECIPKG_TEST_REGEX_ADAPTER` to an adapter for the engine being tested. It accepts `PATTERN TEXT` for UTF-8 strings, or `--bytes PATTERN HEX` for raw bytes, and emits `{"matches":[[start,end],...]}` using byte offsets (exit 0), or `{"error":"compile"}` for invalid patterns (exit 2); `--version` identifies the adapter. This adapter protocol is only for testing and does not prescribe the engine's implementation language or product API. An absent variable skips the class; an explicitly invalid target fails.

For comparison with the upstream crate, build the included reference adapter with Rust and Cargo, using a disposable output directory:

```sh
regex_target="$(mktemp -d)"
CARGO_TARGET_DIR="$regex_target" cargo build --locked --manifest-path fixtures/regex-reference/Cargo.toml
RECIPKG_TEST_REGEX_ADAPTER="$regex_target/debug/recipkg-regex-probe" python3 -m unittest discover -s tests -p test_regex.py -v
```

The reference calls the upstream package; its passing results do not demonstrate a reconstructed engine. Remove the disposable target directory after use. Cargo may download packages to its configured cache.

Run locally with Python 3.11+:

```sh
python3 -m unittest discover -s tests -v
```

Set `RECIPKG_TEST_JQ`, `RECIPKG_TEST_RG`, `RECIPKG_TEST_GIT`, `RECIPKG_TEST_FFMPEG`, and `RECIPKG_TEST_FFPROBE` to executable paths to compare a reconstruction. For FFmpeg candidate testing, set both FFmpeg and ffprobe explicitly; this prevents silently combining the candidate with a host executable. An explicitly specified missing executable fails the run. When testing a selected ripgrep, a missing Git helper also fails; otherwise an unavailable default executable skips its class, and a skipped class is not a pass. The harness prints target version output; record executable provenance, build configuration and platform separately. Temporary fixtures are cleaned up after tests unless a test database fails to stop. It does not connect to a model or use the user's repositories.

When a case fails, compare the fixed upstream recipe, version, environment, and stderr before changing expected behavior. Add tests for newly observed cases and retain unresolved differences. The tests live outside Markdown-only recipe archives.

For selected jq collection filters, set `RECIPKG_TEST_JQ` to the executable and run `python3 -m unittest discover -s tests -p test_jq_collections.py -v`. The example cases check mapping, empty and multiple results, keys, membership, and error behavior. Set `RECIPKG_TEST_JQ_REFERENCE` to a distinct upstream executable to also compare 1,400 fixed-seed input/filter combinations; the differential method is explicitly skipped without a reference. This is a finite sample, not full jq compatibility.

For jq ordering and aggregation, set `RECIPKG_TEST_JQ` and run `python3 -m unittest discover -s tests -p test_jq_aggregation.py -v`. The examples cover multi-value keys, equal-key tie handling, empty results, `add`, and errors. Set `RECIPKG_TEST_JQ_REFERENCE` to a distinct upstream executable to additionally compare 1,200 fixed-seed input/filter combinations. Without a reference the differential method is skipped; this is not complete compatibility coverage.

For a deterministic jq differential sample of nested JSON equality, ordering, sorting, conditionals, bindings, reductions, function scope, JSON streaming, sequence recovery, relaxed literal boundaries, exact numeric output, and decimal rounding boundaries, set both `RECIPKG_TEST_JQ` and `RECIPKG_TEST_JQ_REFERENCE` to different executables and run `python3 -m unittest discover -s tests -p test_jq_differential.py -v`. The reference must be the intended jq version; the sample is not exhaustive.

To exercise the actual Canvas recipe's pinned recursive dependencies and tamper detection, set `RECIPKG_TEST_CANVAS_RECIPE` to its checkout and `RECIPKG_TEST_CLI` to the selected Recipkg executable, then run `python3 -m unittest discover -s tests -p test_canvas_package.py -v`. Packing fetches the fixed Git dependencies; the temporary archives are removed afterward. This checks package context and integrity, not a rebuilt Canvas or SDK.

For the OpenClaw Gateway sample, provide `RECIPKG_TEST_OPENCLAW` pointing to a disposable executable. It runs a loopback fake OpenAI-compatible model and a Gateway with temporary configuration, workspace, HOME, state, dummy credentials, channels and mDNS disabled, then checks two turns, history and normal restart. It does not request tool execution and is not a network or OS sandbox; startup can attempt external access. It does not verify a complete release, fixed-source build, sandbox or reconstruction. Without the variable, the test is skipped.

```sh
RECIPKG_TEST_OPENCLAW=/absolute/path/to/openclaw python3 -m unittest discover -s tests -p test_openclaw.py -v
```

Vikunja samples require an explicitly supplied `RECIPKG_TEST_VIKUNJA` executable. The harness starts a temporary SQLite-backed instance on loopback with a temporary HOME, files directory, secret and disposable accounts, disables email, reminders, Redis and Sentry, restarts it, and shuts it down. It checks selected v1 and v2 API and direct-user-sharing behavior; it does not test the frontend, network sandboxing or complete compatibility. Do not use a production binary with side effects outside its configured temporary root. Without the variable, the sample is skipped.

```sh
RECIPKG_TEST_VIKUNJA=/absolute/path/to/vikunja python3 -m unittest discover -s tests -p test_vikunja.py -v
```

Miniflux samples require an explicitly supplied `RECIPKG_TEST_MINIFLUX` binary plus local PostgreSQL `initdb` and `pg_ctl`. They initialize a temporary trust-auth database accessible only via its private Unix socket, start Miniflux and a fixture RSS server on loopback, and create disposable accounts. The test explicitly enables private-network fetching only for the fixture. It shuts down only those processes; temporary database files are preserved if shutdown cannot be verified. Do not point these tests at a real server or production database. Without the variable, the Miniflux tests are skipped.

```sh
RECIPKG_TEST_MINIFLUX=/absolute/path/to/miniflux python3 -m unittest discover -s tests -p test_miniflux.py -v
```

For the optional real-browser sample, install Playwright CLI and its Chromium browser separately, and set `RECIPKG_PLAYWRIGHT_CLI` to the executable (or a CLI wrapper `.sh`). It runs a uniquely named headless browser session and closes it afterward. It verifies a small login, read, star, feed-add and mobile-menu sequence; it is not complete UI or accessibility acceptance. Without this variable, the browser case is explicitly skipped.

```sh
RECIPKG_TEST_MINIFLUX=/absolute/path/to/miniflux RECIPKG_PLAYWRIGHT_CLI=/absolute/path/to/playwright-cli python3 -m unittest discover -s tests -p test_miniflux.py -v
```

Syncthing samples require an explicitly supplied `RECIPKG_TEST_SYNCTHING` binary. They create separate temporary configuration and data directories, keys, and shared folders for two loopback-only processes. Discovery, relays, NAT, reporting, automatic upgrades and browser launching are disabled in test configuration. The test stops both processes and removes the temporary directory only after shutdown; if process termination cannot be confirmed it preserves the data. It never reads an existing Syncthing configuration or connects to the user's devices. Without the variable, this class is skipped.

```sh
RECIPKG_TEST_SYNCTHING=/absolute/path/to/syncthing python3 -m unittest discover -s tests -p test_syncthing.py -v
```

The Gitea sample accepts `RECIPKG_TEST_GITEA`, a candidate executable. It starts a server with a temporary HOME, SQLite database, dummy accounts, SSH and registration disabled, and a loopback HTTP listener. It checks private Git push/clone, read-only collaboration, issue authorization and content-version conflicts, then normal restart. Git and the SQLite-capable candidate are required; set `RECIPKG_TEST_GITEA_STATIC_ROOT` when the candidate uses non-embedded templates/assets. The fixture does not enforce an OS/network sandbox, test a full browser frontend, or use real credentials or repositories. It removes its disposable data only after the server stops; without the executable the sample is skipped.

```sh
RECIPKG_TEST_GITEA=/absolute/path/to/gitea RECIPKG_TEST_GITEA_STATIC_ROOT=/absolute/path/to/source python3 -m unittest discover -s tests -p test_gitea.py -v
```

The OpenHands SDK sample accepts `RECIPKG_TEST_OPENHANDS_PYTHON`, a Python interpreter with the candidate Python SDK installed. It starts a disposable loopback OpenAI-compatible model fixture and checks a custom tool, invalid parameters, approval, rejection, event sequence, restored conversation, and simulated authentication failure before and after a side effect. It runs with a temporary HOME and workspace, dummy credentials and a Python-level outbound connection guard; this is not a security sandbox or a general compatibility test for non-Python implementations. Without the variable, the sample is skipped.

The same test file also checks project skill discovery and direct invocation using a temporary Git repository and local skill submodule. It uses the SDK's test LLM, blocks Python sockets, and invokes a harmless shell command from a fixture skill in its temporary workspace; this is not an OS sandbox or a model-driven tool-call test. Git must be available.

```sh
RECIPKG_TEST_OPENHANDS_PYTHON=/absolute/path/to/python python3 -m unittest discover -s tests -p test_openhands_sdk.py -v
```

For the separate real-editor and subprocess-terminal sample, set `RECIPKG_TEST_OPENHANDS_TOOLS_PYTHON` to a Python with the SDK and candidate tools installed. It exercises disposable files, a persistent Bash session, a loopback simulated model and the real Agent tool-call path; it explicitly uses the subprocess backend, not the user's tmux server. It is not a sandbox or a complete tool or backend test.

```sh
RECIPKG_TEST_OPENHANDS_TOOLS_PYTHON=/absolute/path/to/python python3 -m unittest discover -s tests -p test_openhands_tools.py -v
```

To run the real agent-server process sample, set `RECIPKG_TEST_OPENHANDS_SERVER_PYTHON` to a Python with the candidate server, SDK, tools and `websockets` client installed. The harness binds the server and fake model to loopback, uses a temporary HOME, workspace, conversation directory and tmux directory, disables VS Code, preloading and telemetry, and shuts down its processes. It tests specific HTTP and both legacy-event and session-WebSocket authentication, run, normal-restart, event replay and live-message cases; it is not a security sandbox, browser interaction or full protocol acceptance.

```sh
RECIPKG_TEST_OPENHANDS_SERVER_PYTHON=/absolute/path/to/python python3 -m unittest discover -s tests -p test_openhands_server.py -v
```

For manual Canvas integration observations, `tools/openhands_canvas_fixture.py` serves an explicitly supplied prebuilt static Canvas, launches the candidate Agent Server, and supplies a loopback OpenAI-compatible model fixture with both streaming and non-streaming replies. Use a Python environment with the candidate server, tools and `aiohttp` installed. The program prints the local Canvas URL, mock model URL, disposable workspace and dummy session key. It disables telemetry in its test configuration; automation service and external resources are not provided. Use a disposable browser and block its non-loopback requests. The fixture is not a security sandbox and must never be used with real credentials or repositories. Stop it with Ctrl-C; it terminates its server and removes its own temporary data.

```sh
/absolute/path/to/server-python tools/openhands_canvas_fixture.py --build-dir /absolute/path/to/canvas/build
```

In the browser, create a model profile using the printed model URL and a dummy key, select the printed workspace, send a message, then return to it from the sidebar. Check the actual conversation status and both messages; inspect errors instead of assuming the complete UI passed. The model fixture calls the Agent's `finish` tool by default and has no intelligence. To exercise the observed failure path, set `fixture_root` to the printed disposable root path, then set its `model-mode` file to `tool-then-auth` before sending a message: `printf 'tool-then-auth\n' > "$fixture_root/model-mode"`. The fixture instructs the terminal to append `executed` to `fixture-marker.txt` in the disposable workspace, then returns a synthetic HTTP 401 on later model requests. Reload the conversation, expand the tool result, check the file, set the mode to `success`, and send a follow-up. The fixture assumes terminal access in that disposable workspace and does not enforce an OS sandbox. A mode of `auth` returns the synthetic 401 immediately; use it only after a profile has been saved if the UI validates profiles on creation. Never use this mode in a real workspace. Verify the exact build's provenance separately; this manual sample is not an automated browser test, complete compatibility test, or reconstruction acceptance.
