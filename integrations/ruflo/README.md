# Local Ruflo text agents

The existing `remember-project` integration proves SQLite memory only. This adapter
uses pinned `@claude-flow/cli` 3.56.7's actual `agent_spawn` and `executeAgentTask`
functions. Success requires a completed local inference request, nonempty output,
and an updated Ruflo task counter; registration alone never passes.

## Run on the actual worker computer

1. Install Node 22+ and the existing pinned runtime:
   `npm install --prefix /absolute/runtime --ignore-scripts ruflo@3.56.7`
2. Start a local Ollama-compatible OpenAI chat endpoint with an already installed
   model. No model download, cloud model, paid API or credentials are provisioned
   by this adapter. The endpoint must bind loopback. For a VPN host, forward its
   private service to loopback through an existing authenticated tunnel; do not
   expose the unauthenticated model port publicly.
3. Choose measured memory budgets for each Node worker and the shared model.
   Include model context/KV-cache and concurrent-request overhead in that reserve.
   Explicitly budget overlapping video renders via `render_memory_mb` and `render_cpu`;
   use zero only when no renderer overlaps the batch.
4. Run `python integrations/ruflo/local_batch.py --runtime /absolute/runtime --batch /private/batch.json`.

Example batch (model name and memory budgets are examples, not readiness claims):

```json
{
  "publication_enabled": false,
  "endpoint": "http://127.0.0.1:11434",
  "model": "qwen3:1.7b",
  "workers": 2,
  "worker_memory_mb": 512,
  "shared_model_memory_mb": 4096,
  "render_memory_mb": 2048,
  "render_cpu": 2,
  "max_tokens": 128,
  "timeout_seconds": 120,
  "tasks": [
    {"id": "hook", "prompt": "Draft three short hooks for an educational video about comparing benefits with an annual fee. No named products."},
    {"id": "storyboard", "prompt": "Describe three simple stick-figure pictures illustrating checking a bill. Do not make financial claims."}
  ]
}
```

Admission uses `integrations/agent_capacity.py` (PR #523), fails closed on unknown
host limits, and allows at most four workers / sixteen tasks per batch. Ruflo and
OpenClaw share one fixed per-user OS admission lock across runtime directories.
One framework batch can execute at a time. On Linux/WSL2, an independent guardian
retains the lease until owned process-group cleanup completes, including after
parent SIGKILL. Foreground SIGINT/SIGTERM stops active workers and prevents queued
tasks from starting before the batch unwinds. Timeout and excessive-output paths
use the same cleanup. Native Windows retains direct-child cleanup only; no
Windows parent-death/process-tree guarantee is made. The local model server is
separately owned: client cleanup does not prove server-side inference cancellation.
Interrupted tasks must not be automatically replayed as if their outcome were
known. This is not containment against malicious children escaping their group.
Local Ollama `/api/show` metadata must confirm an installed model and contain no
remote-model/remote-host fields; IDs containing `cloud` are rejected. A trusted
local model server is required: this is not an OS network-egress firewall.
The memory recommendation is **not** an OS-enforced memory cap.

Each task has a private temporary working directory/home, strips ambient provider
keys and proxies, forces local provider/model selection, and permits only one
loopback chat request through the execution core's fetch path. There are no model
shell/file/browser tools, automatic output execution, or publishing routes. This
is configuration isolation for a trusted pinned package, not an OS sandbox against
malicious installed code. Nonempty text verifies execution, not factual accuracy,
creative quality, or readiness for unsupervised content production. Review results.

Readiness from a scratch machine does not prove installation or capacity on the
user's desktop/VPS. A VPN connects machines; it does not add compute capacity.

Tests: `python -m unittest discover -s integrations/ruflo -p 'test*.py' -v`.
Fixture tests explicitly do not count as real model execution.
