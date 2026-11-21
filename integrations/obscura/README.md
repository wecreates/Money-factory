# Obscura connection

The official `h4ckf0r0day/obscura` v0.2.7 normal-render Linux x86_64 release is
pinned to upstream revision `0ecc41770da5c5300227dd83a15bfa1e5100d5d4`.
`release-pin.json` records the exact archive URL, SHA-256, byte size and both
executable identities. The runtime verifier checks both binaries before each
connection. Upstream is Apache-2.0; its license is retained here. This is the
actual upstream browser engine, not a renamed Chromium wrapper.

## Install the isolated runtime

Python 3.11+ and Linux x86_64/WSL2 with compatible glibc are required. The
upstream release targets glibc 2.35+. No Rust build, browser account, model,
subscription, global PATH edit, service or startup task is required.

```sh
python integrations/setup.py obscura --runtime /local/cyzor-runtime
```

This explicit setup downloads the pinned public release and installs only its
verified `obscura` and `obscura-worker` into `/local/cyzor-runtime/obscura`.
An existing matching runtime is reused; mismatched files are not overwritten.
To use an already downloaded archive instead:

```sh
python -m integrations.obscura.runtime --runtime /local/cyzor-runtime/obscura --archive /local/obscura-x86_64-linux.tar.gz
```

Installation honors the host's ordinary network route. No paid proxy/provider
is configured, and no network credentials are written or reported.

## Existing Money Factory and Content Control job interface

Two operations are registered in `repositories.json`, `setup.py`, `run.py`,
`hosted_job.py` and the direct-engine persistence path. Content Control's existing
repository-tools bridge delegates to this same runner without a second adapter.

```sh
python integrations/hosted_job.py obscura-local-page.job.json --runtime /local/cyzor-runtime --output /local/new-local-inspection
python integrations/hosted_job.py obscura-public-page.job.json --runtime /local/cyzor-runtime --output /local/new-public-inspection
```

`inspect-local-web-page` checks the exact reviewed self-contained fixture via a
`data:` URL. It verifies title/text, page JavaScript, button-driven DOM mutation
and a valid 1280×720 PNG. It opens no listener, needs no private-network flag and
loads no external assets. This operation is a health probe, not arbitrary local
file browsing.

`inspect-public-page` accepts a bounded JSON input containing only `url`, on
reviewed HTTPS hosts `example.com`, `cyzorcreations.com`, `www.cyzorcreations.com`
and `content-control-render-worker.onrender.com`. Credentials, explicit ports,
queries, fragments, raw JavaScript, proxy arguments and unknown fields are
rejected. It returns bounded title/text/location plus a PNG. Native private-network
restrictions stay enabled; final navigation must remain on the allowlist. The
normal host transport/TLS environment is retained for this public operation,
while API keys, browser profiles and execution hooks are omitted. No stealth,
login, cookies export, form submission or access-control bypass is used.

Outputs must be new `.json` paths. The worker retains a sibling PNG and hash-bound
result receipt. Source/input/binary/screenshot identities and disabled publishing
and paid-generation flags are explicit. The public operation does **not** attest
HTTP status or full website compatibility. It reads the document at navigation completion without an additional settling
delay, under bounded navigation and process deadlines; this is not media-playback verification.
The reviewed public example is a one-off operation, not a monitoring schedule.

Every adapter run uses the shared local admission lock and existing owned-process
guardian through cleanup. This serializes operations; it is not a new capacity
admission, 24/7 service or proof that the user's PC/VPN can run it. Diagnostics
are one bounded process, with limited captured output and isolated XDG storage.

## Native MCP connection for a local agent client

```sh
python integrations/obscura/mcp_launcher.py --runtime /local/cyzor-runtime/obscura
```

This verifies the binaries and starts the real upstream stdio MCP server. No TCP
listener or imported login session is started. Its 38 discovered native tools
include navigation, DOM snapshots, click/fill and screenshots. Native MCP tools
are broader than the two registered jobs: the calling agent must still follow
user authorization. Environment flags are declarations, not a security sandbox
that prevents a browser from submitting a form.

For the locally installed Codex CLI, the project client supplies just this MCP
server configuration for one invocation:

```sh
python integrations/obscura/codex_client.py --runtime /local/cyzor-runtime/obscura -- mcp get cyzor-obscura --json
python integrations/obscura/codex_client.py --runtime /local/cyzor-runtime/obscura --
```

The first command verifies enabled connection configuration without starting model
inference. The second starts the user's ordinary local Codex session with the
connection available and preserves its existing sandbox/approval settings; any
model-provider cost requires separate financial authorization. Global registration
was not written because this workspace's managed configuration is read-only.
This does not modify the current ChatGPT session's tool inventory or make existing
Ruflo/OpenClaw queues automatically choose Obscura.

## Evidence and checks

`cli-runtime-proof.json` records the actual installed release executing the
reviewed registered local job. `public-runtime-proof.json` records one real public
inspection; page text is hashed rather than republished. `mcp-connection-proof-20261121.json`
records initialization, tool discovery, navigation, form input, click, snapshots
and PNG through the verified launcher. These are workspace operation proofs, not
an upstream benchmark, full Chromium parity, full audiovisual review or uptime.

```sh
OBSCURA_RUNTIME=/local/cyzor-runtime/obscura python -m unittest integrations.obscura.test_integration -v
```

Tests cover strict jobs, invalid URLs, modified fixtures, runtime/manifest
mismatches, no-overwrite paths, dropped secrets/hooks and actual local CLI execution
when the explicit runtime is supplied. The dedicated workflow uses the local
fixture and native MCP, never repeated external-site polling. PNG files remain in
retention-bound artifacts; persistence verifies their identity before retaining
small JSON evidence.
