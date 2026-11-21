# Durable local agent queue

This foreground queue wraps the existing guarded OpenClaw `dispatch` and Ruflo
`run_batch` adapters. It handles local text tasks only: no shell/computer tools,
publication, paid generation, network listener, system service, or autostart.
Both adapters retain their shared host admission lock, real capacity checks,
local-model metadata checks, pinned runtime checks, and execution bounds.

The existing `integrations/queue.json` tracks requested repository integrations;
the browser-farm queue owns browser jobs. Neither is a local model execution
journal, so this queue does not repurpose their tasks or configuration.

## Run from the repository root

Use an operator-owned local directory on a local disk, outside the repository.
Do not use a shared/network filesystem or a folder writable by other users.
Execution requires Linux/macOS or WSL2; no native Windows service is installed.

```sh
python -m integrations.local_agent_queue --queue /path/to/local-agent-queue enqueue integrations/local_queue/ruflo-example.json
python -m integrations.local_agent_queue --queue /path/to/local-agent-queue status
python -m integrations.local_agent_queue --queue /path/to/local-agent-queue work --ruflo-runtime /path/to/pinned/ruflo
python -m integrations.local_agent_queue --queue /path/to/local-agent-queue status --id storyboard-example
```

Adjust the example to an actually installed local model and measured host
budgets first. Do not invent capacity values to override unknown host limits.
The model endpoint must remain explicit HTTP loopback. A privately established
VPN/SSH tunnel may expose a permitted local-model endpoint on loopback, but this
queue creates no tunnel and cannot verify the remote machine's availability.
The runtime path is operator-supplied at execution, never accepted from a job.

`work` executes one queued job and exits by default. A Ruflo job is one bounded
batch, with at most four workers/sixteen tasks under its existing host budget.
For a bounded foreground drain, use `--max-jobs 16`. Optional
`--watch-seconds 3600 --max-jobs 1000` waits for incoming jobs up to one hour;
the watch deadline bounds waiting for work, not an already-running adapter.
Each adapter still enforces its own execution timeout. Stop with Ctrl+C.
Nothing installs a service or continues after the foreground process exits.

For OpenClaw, enqueue `openclaw-example.json`. The pinned OpenClaw executable
must be available in PATH. Queue-owned unique attempt paths replace the usual
`output` field; jobs may not supply an output path. `--openclaw-runtime` is an
optional operator-owned runtime directory, not an executable or model override.

## Recovery and retries

SQLite uses full synchronous transactions for claim and final receipt updates.
A persistent OS lock permits only one foreground consumer per queue. It is
released by the OS on process death; no PID or age guessing can steal a live
consumer's claim. Existing cross-framework admission remains inside the adapters.

Job IDs are immutable idempotency keys. Re-enqueuing an identical document
returns its current state; changing any payload under that ID is rejected.
Completed jobs are not rerun. These guarantees prevent duplicate queued dispatch,
**not exactly-once model inference** across a crash.

On the next `work`, a previously running attempt becomes `interrupted`. Its
inference may have completed without a committed receipt, and backend model
cancellation is not guaranteed. The queue does **not** automatically replay it.
Review the attempt receipt and any raw files first, then explicitly request:

```sh
python -m integrations.local_agent_queue --queue /path/to/local-agent-queue retry storyboard-example
python -m integrations.local_agent_queue --queue /path/to/local-agent-queue work --ruflo-runtime /path/to/pinned/ruflo
```

`max_attempts` is fixed when enqueued, defaults in examples to one, and may be
1–3. Every claimed attempt counts, including a blocked capacity probe. Only
blocked, failed, or interrupted jobs can be retried, and earlier receipts are
retained. Use a new job ID only for a genuinely new task; do not bypass the bound
by automatically generating new IDs. There is no retry loop or automatic retry.
A failed or partially completed Ruflo batch may contain successful individual
results; review those before deliberately retrying the entire batch.

The SQLite `attempts.receipt` is authoritative. Raw OpenClaw artifacts, if written,
remain in `attempts/JOB_ID/ATTEMPT/`; a crash can leave a partial raw file. The
queue never overwrites/reuses attempt directories. A crash before the durable
receipt commit remains unknown even if the backend finished generating text.
Prompts and results are local plaintext; do not enqueue credentials or secrets.
Back up a stopped queue directory if durable host storage/backups are needed.

## Verified scope and remaining host work

`python -m unittest integrations.test_local_agent_queue -v` uses real separate
processes and SIGKILL to exercise live-lock contention, interrupted recovery,
committed receipt retention, and rollback of a partial transaction. Model calls
in those tests are fixtures; they do not prove model inference or host uptime.
The adapter boundary tests verify that the guarded public entry points are used.

This implementation does not establish 24/7 readiness on an unavailable user
machine, validate VPN reachability, install a stronger model, approve output,
or perform a 24-hour soak. Actual host capacity, local runtime/model health,
termination cleanup, disk availability, and a sustained foreground run must be
verified on the intended machine. Publishing and paid generation stay false.
