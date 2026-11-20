# Local agent capacity

For ordered host inventory, bounded runs, stopping and restart/soak evidence, use
the [actual-host runbook](../docs/LOCAL_AGENT_HOST_RUNBOOK.md).

`agent_capacity.py` measures only the machine running it. It does not connect to a
PC, VPS, VPN, model provider, or gateway. It reads no credentials and changes no
settings. Run it on the actual Windows PC or Linux host before choosing worker
concurrency; a result from a CI runner is not a measurement of that host.

From the Money Factory repository root (Python 3.10+; no extra packages):

```sh
python -m integrations.agent_capacity --worker-memory-mb 512 --requested-workers 4 --shared-model-memory-mb 4096 --render-memory-mb 2048 --render-cpu 2
```

These numbers illustrate the inputs, not verified requirements for your model.
Use observed peak worker memory and the selected model's additional memory need.
Defaults reserve 2 CPU cores and 2 GiB for the OS and foreground applications, and
cap a batch recommendation at eight workers. The tool prints JSON and exits 2
when no worker fits or measurement is unavailable. It does not start any agents.

Three different counts matter:

- **Orchestration workers** perform waiting, file, browser, and tool tasks. The
  recommendation bounds this pool using per-worker memory/CPU requirements.
- **Model inference slots** depend on model size, quantization, context length,
  GPU/VRAM, and observed throughput. The tool does not measure GPU memory or claim
  any model slot is ready. Start one actual inference at a time until a measured
  provider limit is established. Use `--shared-model-memory-mb` for a model that
  has not yet loaded; already allocated model memory is excluded from measured
  available RAM and should not be counted twice.
- **Rendering jobs** compete for CPU and memory. Reserve their measured incremental
  needs using `--render-cpu` and `--render-memory-mb`, or pause render admission
  while calibrating model throughput.

A VPN provides connectivity, not extra compute. A remote worker needs its own
fresh report and resource budget. This utility neither configures VPN access nor
opens a listener. Do not add together PC/VPS slots unless an existing coordinator
actually enforces independent host budgets and task ownership.

## Python integration

```python
from integrations.agent_capacity import collect_snapshot, recommend_capacity, shared_admission_lock

with shared_admission_lock():
    snapshot = collect_snapshot()
    budget = recommend_capacity(
        snapshot,
        worker_memory_mb=512,       # replace with measured worker peak
        requested_workers=4,
        shared_model_memory_mb=4096,  # only additional/unallocated model memory
        render_memory_mb=2048,
        render_cpu=2,
    )
    workers = budget['admitted_workers']
    # Execute and join the entire admitted batch INSIDE this context.
```

The caller must enforce `workers` as a **shared limit across Ruflo and OpenClaw**,
not create that many workers independently in each framework. The
`shared_admission_lock()` context uses one fixed per-user host lock across all
checkouts: `~/.cyzor/agent-admission.lock`. It serializes framework batches while
allowing internal workers inside the admitted batch. It raises `AdmissionBusy`
immediately if another batch holds the budget. The persistent file is never
unlinked; POSIX flock/Windows byte-range OS locks release on process exit,
including crashes. Both adapters must use it before sampling capacity and hold
it until every worker has joined. Different OS accounts are not coordinated.
The standalone diagnostic CLI does not acquire or create this lock. A numeric
recommendation alone is not a reservation. Reports older than 60 seconds, future-dated reports, unknown
metrics, and nonfinite values are rejected. No success implies model execution,
VPN reachability, creative approval, or publication permission.

Linux collection respects CPU affinity plus cgroup-v2 CPU and memory limits at
the current group and its ancestors. Unavailable or unreadable cgroup constraints
block admission rather than borrowing host-wide values. Legacy cgroup-v1 and
macOS collection are currently unsupported. Windows uses native available physical
memory and logical CPU count; this does not benchmark the computer or account for
CPU load from other apps, so explicit headroom and supervised calibration remain
necessary.

Tests: `python -m unittest -v integrations.test_agent_capacity`.
