# REA in Money Factory

Money Factory pins official MIT-licensed `rea-agents@6.4.0` through its npm integrity lock. REA is an engineering inspection tool, separate from Remotion rendering, video quality comparison, and publication approval.

## Install and run

Use a free Ubuntu runner with functioning procps, Node 24.11 or later, Python 3, and GCC for the native verification fixture:

```sh
python integrations/setup.py rea --runtime /absolute/runtime
node /absolute/runtime/rea/node_modules/playwright/cli.js install-deps chromium
python integrations/hosted_job.py rea-source.job.json --runtime /absolute/runtime --output /new/results/source
```

Setup installs the locked package and optional native PTY dependency into an isolated runtime, plus Chromium for the dedicated local-page operation. It does not install Hopper, Ghidra, IDA, or paid providers. The workflow `.github/workflows/rea-offline-analysis.yml` installs the runtime, requires actual successful execution, and retains receipts in `rea-integrated-evidence`. `REA_REQUIRE_PASS=1` prevents the known local process-inspection limitation from counting as hosted acceptance.

## Integrated operations

Each job uses `tool: "rea"`, one operation below, an authorized input, and explicit `publication_enabled: false` and `paid_generation_enabled: false`. Hosted jobs resolve inputs under `integrations/jobs`; the generic worker also requires a new output path.

| Operation | Input | Operation scope |
|---|---|---|
| `analyze-javascript-application` | Local source directory | Upstream static module/import graph; does not execute source |
| `inspect-artifact` | Local binary/file | Artifact identity and native/header observations; not decompilation |
| `mcp-smoke` | Local source directory | Real stdio initialize, tool inventory, `binary_session`, and actual static-analysis call |
| `capture-owned-process` | Reviewed `.js`, `.mjs`, or `.cjs` file | Executes Node in a temporary working directory and records runtime evidence |
| `inspect-local-web-page` | Local directory containing `index.html` | Dedicated ephemeral Chromium, loopback CDP and actual page evidence |

Adapters bind input hashes before and after inspection. Outputs and receipts are never silently overwritten. Missing dependencies, upstream errors, incomplete validation, or failed calls remain blocked. A passing receipt proves its named operation, not every upstream REA capability.

Process capture executes the selected source with the current user's permissions. The temporary working directory and credential-stripped environment are not an OS sandbox. Browser inspection executes the authorized local page in a fresh browser profile; it does not attach to existing signed-in sessions.

## MCP client configuration

Register this repository's launcher with a trusted local MCP client using absolute paths:

```json
{
  "mcpServers": {
    "money-factory-rea": {
      "command": "python3",
      "args": [
        "/absolute/Money-factory/integrations/rea/mcp_server.py",
        "--runtime",
        "/absolute/runtime/rea"
      ]
    }
  }
}
```

The launcher verifies the package version, strips inherited provider credentials, creates temporary configuration, forwards shutdown signals, and exposes the upstream stdio server. It does not alter account settings or automatically register this running ChatGPT session. The upstream catalog contains 170 tools in this pin; availability in the catalog does not establish that every external dependency is installed. Only trusted authorized clients should receive it: upstream runtime tools can execute or interact with targets under the host user's permissions. Publication flags do not turn that upstream catalog into a security sandbox.

The genuine probe invokes this launcher and requires a real source-analysis response as well as transport health:

```sh
REA_RUNTIME=/absolute/runtime/rea REA_REQUIRE_PASS=1 python -m unittest discover -s integrations/rea -p 'test_*.py' -v
```

## Evidence and limitations

Current rollout status: `integration_pending_verification` until the expanded hosted workflow passes.

Historical free Ubuntu run [38474010468](https://github.com/wecreates/Money-factory/actions/runs/38474010468) verified the original static adapter. Its throw-containing source fixture was inspected without execution. That historical result does not prove the newer browser, process, artifact, or MCP operations; use their corresponding current hosted receipts.

Local workspace verification on October 14, 2026 established REA 6.4.0 stdio initialization, the 170-tool catalog, identity lookup, and an actual analysis request. Analysis correctly returned `capability_unavailable`: local `ps -axo pid=,ppid=,pgid=,uid=,stat=,command=` fails with `fatal library error, lookup self`. No ownership check is bypassed. This infrastructure limitation is distinct from a successful MCP handshake.

Deep native decompilation requires a separately installed supported Ghidra, Hopper, or IDA provider. Device, firmware, debugger, and other optional upstream capabilities require their own host tools, targets, permissions, and execution evidence. They are not claimed ready by this integration. `inspect-with-objdump` appears in newer upstream documentation but is absent from pinned 6.4.0. No claim of audiovisual review, competitor parity, production readiness, or publishing permission follows from REA evidence.

Official sources: [repository](https://github.com/morluto/rea), [installation](https://github.com/morluto/rea/blob/main/docs/installation.md), [MCP contracts](https://github.com/morluto/rea/blob/main/docs/mcp-contracts.md), [browser observation](https://github.com/morluto/rea/blob/main/docs/browser-observation.md), [process capture](https://github.com/morluto/rea/blob/main/docs/process-capture.md). Upstream main may describe a newer release; use the installed 6.4.0 catalog and command schemas as the integration contract.
