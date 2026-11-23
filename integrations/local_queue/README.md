# Durable local agent queue

This foreground queue wraps the existing guarded OpenClaw `dispatch`, Ruflo
`run_batch`, and source-pinned Content Control picture-review adapters. It handles
bounded local text tasks and unpublished video review jobs: no arbitrary shell
commands, computer actions, publication, paid generation, network listener,
system service, or autostart.
The adapters retain shared host admission, real capacity checks, pinned runtime
checks, and execution bounds. Text adapters also verify local-model metadata;
the video adapter verifies its pinned source and review artifacts.

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

Use `enqueue-batch /path/to/batch.json` to submit a JSON array of one to 16
existing job envelopes in one SQLite transaction. Use distinct immutable IDs.
A malformed entry, unsupported visual shape in a new cycle, or conflicting
existing ID rejects the entire submission. Resubmitting identical jobs returns
their current state without resetting attempts. Batch output follows input order
and omits prior attempt receipts. Use `status --id` for the full history of an
individual job. Worker claims still use creation time and ID order.

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
the watch deadline stops new claims and waiting, not an already-running adapter.
The deadline is rechecked after acquiring the SQLite write transaction, so
database contention cannot silently claim a job after that deadline.
Each adapter still enforces its own execution timeout. Stop with Ctrl+C, or use
the graceful run-specific stop command below.
Nothing installs a service or continues after the foreground process exits.

For OpenClaw, enqueue `openclaw-example.json`. The pinned OpenClaw executable
must be available in PATH. Queue-owned unique attempt paths replace the usual
`output` field; jobs may not supply an output path. `--openclaw-runtime` is an
optional operator-owned runtime directory, not an executable or model override.

## Source-bound video review jobs

`adapter: "content-control-video"` uses the existing picture producer through
`integrations.content_control.video_job`. The request contains only:
`operation: "produce-episode1-review"`, exact `source_commit` (40 lowercase hex),
`source_manifest_sha256` (64 lowercase hex), `timeout_seconds` (30–1800), and
explicit false publication/paid flags. The same immutable queue envelope and
attempt bound apply. Generate source identities with the runtime doctor; do not
invent them or use a moving branch name as a commit.

Operator paths are supplied only when starting the worker:

```sh
python -m integrations.local_agent_queue --queue /path/to/local-agent-queue work --content-control-root /path/to/content-control --video-python /path/to/asr/bin/python --picture-python /path/to/picture/bin/python
```

Jobs cannot supply executable paths, checkout paths, commands, or output paths.
The adapter receives a fresh queue-owned attempt directory, applies its existing
source/runtime/capacity checks and process guardian, and retains its technical
review receipt. A successful queue job means the adapter completed a technical
review packet; `review_status: AWAITING_REVIEW`, `full_av_review: false`, and
`production_ready: false` remain intact. Queue success never grants creative,
audiovisual, canonical promotion, or publishing approval.

## Foreground health and graceful stop

```sh
python -m integrations.local_agent_queue --queue /path/to/local-agent-queue work --ruflo-runtime /path/to/pinned/ruflo --watch-seconds 3600 --max-jobs 1000 --poll-seconds 2
# In another terminal, inspect the exact run ID:
python -m integrations.local_agent_queue --queue /path/to/local-agent-queue health
python -m integrations.local_agent_queue --queue /path/to/local-agent-queue stop --run-id RUN_ID_FROM_HEALTH
```

`--poll-seconds` defaults to 1 and accepts finite values from 0.2 to 60. A
separate bounded-rate heartbeat persists while the main thread is inside a
bounded adapter. `health` reports the run ID, phase, active job, processed count,
last heartbeat, consumer-lock observation, queue counts, and final exit reason.
This verifies process liveness only, not model availability, VPN reachability,
video quality, or production readiness. A free consumer lock with an unfinished
run is reported as `interrupted_unrecovered`, never as a live running worker.

`stop` requests a graceful stop; it does **not** claim that the worker has already
stopped. The current bounded attempt finishes and its receipt is retained. The
stop check and next claim are serialized in one transaction, so the worker cannot
claim another job after the request commits. Idle response latency is up to the
configured poll interval; active-job latency includes the adapter’s bounded prerequisite checks and
execution deadlines. A video job’s production timeout does not include its
separate prerequisite probes.
Inspect `health` for `finished` and its exit reason. A stale run ID cannot stop a
later run. Omitting `--run-id` targets the latest unfinished run at request time.
Ctrl+C interrupts immediately through the existing cleanup and unknown-outcome
recovery path; it is different from a graceful stop.

Run receipts remain in SQLite across restarts. The final `work` output contains
compact job summaries to keep a long foreground drain from retaining all model
outputs in memory; use `status --id` to retrieve full preserved job receipts.
A failed heartbeat stops new work once the active bounded attempt returns.

The actual CLI smoke in [operator-smoke.json](operator-smoke.json) observed a live
worker, a persisted capacity-blocked job, a run-specific stop request, and a final
released consumer lock with `stop_requested`. Zero model tasks ran because this
scratch environment still could not establish effective host capacity. This is
not an actual-computer, VPN, or 24-hour availability test.

## Recovery and retries

SQLite uses full synchronous transactions for claim and final receipt updates.
A persistent OS lock permits only one foreground consumer per queue. It is
released by the OS on process death; no PID or age guessing can steal a live
consumer's claim. Existing cross-framework admission remains inside the adapters.

Job IDs are immutable idempotency keys. Re-enqueuing an identical document
returns its current state; changing any payload under that ID is rejected.
Completed jobs are not rerun. These guarantees prevent duplicate queued dispatch,
**not exactly-once adapter execution** across a crash.

On the next `work`, a previously running attempt becomes `interrupted`. Its
execution may have completed without a committed receipt, and backend model
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

`python -m unittest integrations.test_local_agent_queue integrations.test_local_queue_process_recovery integrations.test_local_agent_operator -v` uses real separate
processes and SIGKILL to exercise live-lock contention, interrupted recovery,
committed receipt retention, and rollback of a partial transaction. Model calls
in those tests are fixtures; they do not prove model inference or host uptime.
The adapter boundary tests verify that the guarded public entry points are used.
The combined Linux regression freezes the process guardian, kills the queue
consumer, verifies interrupted recovery without replay while admission remains
held, resumes cleanup, and explicitly retries with both attempt receipts retained.
That regression requires the owned-process guardian; missing implementation fails
the CI import rather than silently skipping the dependency.

This implementation does not establish 24/7 readiness on an unavailable user
machine, validate VPN reachability, install a stronger model, approve output,
or perform a 24-hour soak. Actual host capacity, local runtime/model health,
termination cleanup, disk availability, and a sustained foreground run must be
verified on the intended machine. Publishing and paid generation stay false.
