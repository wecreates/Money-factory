# Bring up one local text worker on an existing host

Run this from the **actual chosen host**, in a checked-out Money Factory repository.
Use Linux or WSL2 for the common Ruflo/OpenClaw path. Native Windows supports the
capacity diagnostic but not this OpenClaw runner; macOS capacity admission is not
implemented. A workspace/CI result is not evidence about your computer or VPS.

This runbook does not configure SSH/VPN, open ports, enable publishing, install a
service, or provision paid resources. Use an existing authenticated terminal on
the chosen machine; never paste keys, tokens or passwords into a report. Run both
frameworks under the same OS user so they share the admission lock. Stop if the
host identity or ownership of the local model server is uncertain.

## 1. Inventory before installation

From the repository root, in Bash:

```bash
git rev-parse --show-toplevel
git rev-parse HEAD
python3 --version
node --version
npm --version
command -v openclaw || true
command -v ollama || true
python3 integrations/ruflo/local_batch.py --help
python3 integrations/run.py --help
```

Require Python 3.10+. The pinned OpenClaw npm metadata requires Node
`>=24.16.0 <25 || >=26.1.0`; Node 24.16+ within major 24 satisfies both adapters
(Ruflo's package minimum is Node 20). Use the
existing package prefixes when known; the following directory is an example,
not a detected installation. These variables apply to this terminal only:

```bash
export CYZOR_AGENT_RUNTIME="$HOME/cyzor-agent-runtime"
export CYZOR_RUFLO_RUNTIME="$CYZOR_AGENT_RUNTIME/ruflo"
mkdir -p "$CYZOR_AGENT_RUNTIME/runs"
export CYZOR_RUN="$(mktemp -d "$CYZOR_AGENT_RUNTIME/runs/check-XXXXXXXX")"
export PATH="$CYZOR_AGENT_RUNTIME/openclaw/node_modules/.bin:$PATH"
date -u +%Y-%m-%dT%H:%M:%SZ > "$CYZOR_RUN/started-at.txt"
git rev-parse HEAD > "$CYZOR_RUN/repository-revision.txt"
python3 - <<'PY'
import json, os
from pathlib import Path
p = Path(os.environ['CYZOR_RUFLO_RUNTIME']) / 'node_modules/@claude-flow/cli/package.json'
print(json.dumps({'ruflo_core_version': json.loads(p.read_text())['version'] if p.is_file() else None,
                  'expected': '3.56.7'}))
PY
```

Detect OpenClaw through its isolated doctor rather than loading the user's
profile or starting a gateway:

```bash
python3 - <<'PY'
import json, os
from pathlib import Path
p = Path(os.environ['CYZOR_RUN'])
job = {'tool': 'openclaw', 'operation': 'doctor', 'publication_enabled': False,
       'paid_generation_enabled': False, 'output': str(p / 'openclaw-doctor.json')}
(p / 'doctor-job.json').write_text(json.dumps(job))
PY
python3 integrations/run.py "$CYZOR_RUN/doctor-job.json" --runtime "$CYZOR_AGENT_RUNTIME"
```

`BLOCKED` with `MODEL_EXECUTION_NOT_TESTED` and runtime version `2026.11.6` is
the expected installed-doctor result. `OPENCLAW_NOT_INSTALLED` or a version
mismatch needs repair before execution. This entry point can exit zero while
its JSON says `BLOCKED`; **inspect the receipt status, not just the exit code**.
Outputs are never overwritten; create a new run directory for another check.

Only if missing, install into the selected private prefixes; do not replace a
different global/user installation. These commands fetch public npm packages,
disable package lifecycle scripts, and do not download models or start services:

```bash
npm install --prefix "$CYZOR_RUFLO_RUNTIME" --ignore-scripts --no-audit --no-fund ruflo@3.56.7
npm install --prefix "$CYZOR_AGENT_RUNTIME/openclaw" --ignore-scripts --no-audit --no-fund openclaw@2026.11.6
```

Recheck the exact versions. Stop on engine/dependency errors rather than enabling
install hooks, changing pins or granting additional privileges automatically.

## 2. Check the existing local model and measure admission

Use an operator-owned Ollama server with an **already downloaded local model**.
Do not start a server, pull weights, add credentials or expose a port as part of
this diagnostic. Inspect the literal loopback endpoint without proxy routing:

```bash
curl --noproxy '*' --fail --silent --show-error --max-time 5 http://127.0.0.1:11434/api/tags
ss -ltnp '( sport = :11434 )'
```

On Linux/WSL, inspect the listener: it must be loopback, not `0.0.0.0` or `[::]`.
If `ss` is unavailable, obtain equivalent local socket evidence before proceeding.
No listener, no installed model, a remote relay, or uncertain server ownership
means stop here. The adapters additionally inspect `/api/show` and reject cloud
tags and remote-model metadata. A trusted server is still required; these checks
are not an OS egress firewall.

Set the exact installed local model ID and integer budgets. The numbers below
are **illustrations to replace with measured incremental peaks**, not a model
recommendation or proof that one worker fits:

```bash
export CYZOR_MODEL='REPLACE_WITH_INSTALLED_LOCAL_MODEL'
export CYZOR_WORKER_MB=512
export CYZOR_MODEL_EXTRA_MB=4096
export CYZOR_RENDER_MB=2048
export CYZOR_RENDER_CPU=2
python3 -m integrations.agent_capacity \
  --worker-memory-mb "$CYZOR_WORKER_MB" --requested-workers 1 \
  --shared-model-memory-mb "$CYZOR_MODEL_EXTRA_MB" \
  --render-memory-mb "$CYZOR_RENDER_MB" --render-cpu "$CYZOR_RENDER_CPU" \
  > "$CYZOR_RUN/capacity.json"
cat "$CYZOR_RUN/capacity.json"
```

Leave the default 2 CPU/2 GiB OS reserve intact. Already allocated model memory is
excluded from available RAM; reserve only additional model/context/concurrency
needs, without double-counting. Use zero render reserve only when rendering is
not overlapping. Unknown metrics or fewer than one admitted worker means stop;
never override failed admission with host-wide numbers. GPU/VRAM and live CPU
load are not measured here. Both adapters resample capacity inside the shared
lock immediately before execution, so this report is evidence, not a reservation.

## 3. Generate one bounded job for each adapter

The jobs use one worker, one short text request, no model tools and no publishing.
Keep outputs in the private run directory. This creates job files only:

```bash
python3 - <<'PY'
import json, os
from pathlib import Path
p = Path(os.environ['CYZOR_RUN'])
model = os.environ['CYZOR_MODEL']
assert model and model != 'REPLACE_WITH_INSTALLED_LOCAL_MODEL', 'Choose an installed local model first'
budgets = {key: int(os.environ[env]) for key, env in {
    'worker_memory_mb': 'CYZOR_WORKER_MB', 'shared_model_memory_mb': 'CYZOR_MODEL_EXTRA_MB',
    'render_memory_mb': 'CYZOR_RENDER_MB', 'render_cpu': 'CYZOR_RENDER_CPU'}.items()}
prompt = 'Write three numbered, short stick-figure storyboard shots about checking a packing list. Text only; do not claim to execute actions.'
ruflo = dict(budgets, publication_enabled=False, endpoint='http://127.0.0.1:11434',
             model=model, workers=1, max_tokens=128, timeout_seconds=120,
             tasks=[{'id': 'storyboard-check', 'prompt': prompt}])
openclaw = dict(budgets, tool='openclaw', operation='run-text', publication_enabled=False,
                paid_generation_enabled=False, model=model, model_url='http://127.0.0.1:11434',
                prompt=prompt, timeout_seconds=120, output=str(p / 'openclaw-result.json'))
(p / 'ruflo-job.json').write_text(json.dumps(ruflo, indent=2))
(p / 'openclaw-job.json').write_text(json.dumps(openclaw, indent=2))
PY
```

Run one foreground command at a time, initially without simultaneous rendering:

```bash
python3 integrations/ruflo/local_batch.py \
  --runtime "$CYZOR_RUFLO_RUNTIME" --batch "$CYZOR_RUN/ruflo-job.json" \
  > "$CYZOR_RUN/ruflo-result.json"
cat "$CYZOR_RUN/ruflo-result.json"
python3 integrations/run.py "$CYZOR_RUN/openclaw-job.json" --runtime "$CYZOR_AGENT_RUNTIME"
cat "$CYZOR_RUN/openclaw-result.json"
```

Require Ruflo `status=PASS`, `executed_tasks=1`, one inference request, positive
output tokens and task count 1. Require OpenClaw `status=PASS`,
`model_execution_verified=true`, `verified_agents=1`, positive input/output tokens
and the exact chosen local model. Inspect the actual text for relevance and errors.
All publication/paid/delivery/tool flags must remain false. Nonempty model output
alone does not prove useful quality; a small model may pass execution and fail the
storyboard task. A fixture-only test is not model inference.

Both frameworks serialize through one per-user OS lock. Do not add their worker
counts. Ruflo permits at most four workers/sixteen tasks, but increase beyond one
only after measured inference throughput and memory peaks justify it. The model
server's inference slots, orchestration workers and renderer jobs are separate
budgets. These adapters have no continuous task queue or service supervisor.

## 4. Status, stop, restart and soak evidence

While a command runs, inspect only process metadata from a second terminal:

```bash
ps -u "$(id -u)" -o pid,ppid,pgid,comm,etime,rss,pcpu
```

Record the adapter and its worker PIDs at launch; omit process arguments and
environment dumps from reports. Prefer letting the bounded 120-second request
finish. To interrupt a foreground run, press Ctrl-C once, then verify its worker
processes actually exit. On Linux/WSL2, the adapter guardian watches parent
liveness, stops its owned worker process group and retains admission until cleanup
finishes, including after parent SIGKILL. Ruflo foreground interruption also stops
pending tasks from starting. These paths have subprocess regression tests, but
still verify the actual host; no Windows process-tree or model-server inference
cancellation guarantee is made. If an owned child
remains, verify its PID, user and start time belong to this run before stopping
that exact process with `kill -TERM <verified-owned-PID>`; recheck afterward.
Never use broad `pkill node/python`, terminate an unrelated model server, or
delete `~/.cyzor/agent-admission.lock`. The OS releases lock ownership on exit;
the persistent file remains intentionally. The adapter does not manage or stop
the separately owned model server.

| Gate | Evidence required before calling it ready |
| --- | --- |
| First turn | Fresh actual-host capacity, pinned versions, installed local model, PASS receipt and useful reviewed text from each adapter. |
| Stop/restart | One controlled stop; no owned orphan workers; a new run directory; a fresh admitted PASS after restart. Do not reuse old output files or delete the lock. |
| Shared contention | In a supervised test, a second framework invocation while the first holds admission returns BLOCKED/busy and executes zero tasks; rerun succeeds after release. |
| One-hour calibration | Sequential bounded jobs with UTC start/end, elapsed time, token counts, PASS/BLOCKED/FAIL and peak worker/model/render RAM/CPU. Zero unexplained failures, orphan processes, swap thrashing or publication/paid activity. Review every output in this small sample. |
| 24-hour readiness | At least 24 hours of real host observations across the intended workload, a restart/recovery drill, an owned durable queue with duplicate protection, and an alert/stop path. Report actual measured completion/failure rates and quality samples; these adapters alone do not supply those service components. |

Do not install an unattended service or schedule a loop until the first-turn and
recovery gates pass. Keep the evidence under the host's private run directory and
share only sanitized receipts, not home/config files, prompts containing private
data, or credentials. On a second host, repeat all gates independently. A VPN
provides connectivity, not capacity or uptime.

## Minimum missing access decision

Choose **one existing host for the first run: the PC's Linux/WSL2 environment or
the existing Linux VPS**, and make an authenticated terminal on that host
available. No new server, public model port, credential disclosure, or purchase
is needed. Current workspace access and historical SSH claims cannot substitute
for this live host session. The reviewed GitHub workflows contain no existing
SSH/Tailscale worker route; the named Host Probe is only public DNS/TLS/HTTP.

Details: [capacity](../integrations/AGENT_CAPACITY.md),
[Ruflo](../integrations/ruflo/README.md),
[OpenClaw](../integrations/openclaw/README.md).
