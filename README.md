# Recipkg standard-library black-box samples

Small, reproducible black-box comparisons for selected contracts in the [Recipkg standard library](https://github.com/recipkg/standard-library). The tests run candidate executables on disposable input and assert user-visible results. They do **not** establish full compatibility, source provenance, secure isolation, or independent reconstruction.

These tests currently correspond to selected observations in `recipkg/jq` v0.1.1 (upstream jq 1.8.2), `recipkg/ripgrep` v0.1.0 (upstream ripgrep 15.2.0), `recipkg/ffmpeg` v0.1.3 (upstream FFmpeg 9.0.2), `recipkg/miniflux` v0.1.5 (upstream source commit `3945f3daa0a90040f761d79a5f62a678fe86ba4e`), `recipkg/syncthing` v0.1.1 (upstream source commit `ed38528d7fba3dd6a42c9c9fc6780af432dc15d2`), and `recipkg/openhands-agent-sdk` v0.1.5 (upstream source commit `46b1fa5cb91ada17e6ec938c7e8624a4fa19fa98`); upstream builds may differ in codecs or features. Git is required for ripgrep's repository filtering test; FFmpeg needs lavfi, Matroska and PCM support. jq/ripgrep/FFmpeg/ffprobe are not bundled dependencies.

Run locally with Python 3.11+:

```sh
python3 -m unittest discover -s tests -v
```

Set `RECIPKG_TEST_JQ`, `RECIPKG_TEST_RG`, `RECIPKG_TEST_GIT`, `RECIPKG_TEST_FFMPEG`, and `RECIPKG_TEST_FFPROBE` to executable paths to compare a reconstruction. Unavailable executables skip their test class and are reported as skipped: a skipped class is not a pass. The harness prints target version output; record executable provenance, build configuration and platform separately. Temporary fixtures are cleaned up after tests unless a test database fails to stop. It does not connect to a model or use the user's repositories.

When a case fails, compare the fixed upstream recipe, version, environment, and stderr before changing expected behavior. Add tests for newly observed cases and retain unresolved differences. The tests live outside Markdown-only recipe archives.

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

The OpenHands SDK sample accepts `RECIPKG_TEST_OPENHANDS_PYTHON`, a Python interpreter with the candidate Python SDK installed. It starts a disposable loopback OpenAI-compatible model fixture and checks a custom tool, invalid parameters, approval, rejection, event sequence and restored conversation. It runs with a temporary HOME and workspace, dummy credentials and a Python-level outbound connection guard; this is not a security sandbox or a general compatibility test for non-Python implementations. Without the variable, the sample is skipped.

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

In the browser, create a model profile using the printed model URL and a dummy key, select the printed workspace, send a message, then return to it from the sidebar. Check the actual conversation status and both messages; inspect errors instead of assuming the complete UI passed. The model fixture calls the Agent's `finish` tool and has no intelligence or external side effects. Verify the exact build's provenance separately; this manual sample is not an automated browser test, complete compatibility test, or reconstruction acceptance.
