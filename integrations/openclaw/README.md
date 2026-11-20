# Local OpenClaw text worker

This extends the existing `integrations/run.py` entry point with one isolated text
turn for script, title, and storyboard drafts. It does not publish, send messages,
launch a gateway, modify a user's OpenClaw settings, or grant shell/file tools to
the model. It is not a 24/7 service, a video renderer, or proof of host capacity.

Use Python 3.10+, POSIX (Linux, macOS, or WSL2), Node compatible with OpenClaw,
and a separately installed, trusted `openclaw@2026.11.6` executable on PATH.
Other versions fail closed until their CLI and schema are checked. No packages
or model weights are automatically installed by this adapter.

The operator must provide an already running, operator-owned local Ollama server
and a downloaded local model. Only literal loopback HTTP URLs with explicit
ports are accepted. Before generation, a bounded `/api/show` metadata request must identify a local
model and contain no `remote_model` or `remote_host`. Cloud model tags, remote URLs, inherited credentials,
proxies, runtime hooks, and arbitrary CLI options are rejected. Loopback alone
cannot prove a provider is local: the provider must not forward to a paid/cloud
backend. No OS/network sandbox is claimed.

Create a job JSON (choose a new output path for each run):

```json
{
  "tool": "openclaw",
  "operation": "run-text",
  "publication_enabled": false,
  "paid_generation_enabled": false,
  "model": "qwen2.5:3b",
  "model_url": "http://127.0.0.1:11434",
  "prompt": "Draft a 30-second stick-figure storyboard about saving a small amount each week. Avoid promises of investment returns.",
  "timeout_seconds": 120,
  "worker_memory_mb": 512,
  "shared_model_memory_mb": 2048,
  "render_memory_mb": 1024,
  "render_cpu": 1,
  "output": "/tmp/cyzor-storyboard-001.json"
}
```

```sh
python integrations/run.py /path/to/job.json --runtime /path/to/shared-agent-runtime
```

Both Ruflo and OpenClaw acquire the same OS-backed per-user host lock at
`~/.cyzor/agent-admission.lock`, across checkouts and runtime roots. It admits one
batch/turn at a time; the OS releases ownership after a crash. The persistent lock
file is never deleted. Do not delete it to bypass contention. This is a
conservative shared lane, not additive capacity, and is not a machine-wide lock
across different user accounts.

OpenClaw samples host capacity **inside the lock**, then admits one worker only
if CPU/RAM headroom remains after OS, renderer, and shared-model reserves. All
four job budget fields are required. The example numbers are illustrative, not
measurements of your computer. Set `shared_model_memory_mb` to additional model
memory not already reflected in available RAM (zero if already loaded); measure
peak worker and renderer usage. Use `python -m integrations.agent_capacity` on
the actual host. Unknown/stale resource signals fail closed.

A `doctor` job needs only `tool`, `operation`, both false flags, and `output`.
It checks the installed CLI version, makes no model call, and deliberately returns
`BLOCKED` with `MODEL_EXECUTION_NOT_TESTED`; installed software is not a verified
worker. A successful `run-text` receipt requires the exact local provider/model, embedded
route, positive input/output token usage, no fallback/abort/successful tool call,
and nonempty text. It records only the completed turn, not an
always-running agent or production readiness. Failures are sanitized and output
files are never overwritten. Review the actual generated text before using it.

Each run uses a fresh private temporary home/config/state/workspace, only the
Ollama provider plugin, disabled memory plugins, no model fallback, wildcard
tool denial, disabled tool-search bridges, and `agent --local` without `--deliver`.
Bootstrap files are disabled. The child process group is terminated on timeout;
response output is bounded to 1 MiB. State is removed after the turn. The model
server is separately managed and is not started or stopped by the adapter.

For a VPN host, run the worker on that host against its local model server. A VPN
provides connectivity, not CPU/RAM, model weights, uptime, or credentials. This
adapter does not open ports or configure a VPN. Native Windows execution is not
supported in this first version; use WSL2 for process-group cleanup guarantees.

## Verification

```sh
python -m unittest discover -s integrations/openclaw -p 'test_*.py' -v
```

The unit tests use fixtures, not model inference. To test the installed runtime
against a deterministic loopback Ollama transport fixture, set
`OPENCLAW_TEST_CLI=/absolute/path/to/openclaw` and run the optional contract test.
A fixture result must never be presented as model inference or installed host
capacity. Real local inference requires the explicit run job above.

Official references checked for pinned version 2026.11.6:

- https://docs.openclaw.ai/cli/agent
- https://docs.openclaw.ai/providers/ollama/configuration
- https://docs.openclaw.ai/gateway/config-tools/tool-policy
- https://docs.openclaw.ai/tools/tool-search
- https://docs.openclaw.ai/tools/plugin
- https://docs.openclaw.ai/help/environment
- https://docs.openclaw.ai/gateway/config-agents/workspace-and-bootstrap
