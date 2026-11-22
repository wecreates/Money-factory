# One hosted queued video proof

The **One queued unpublished video review** workflow runs one existing Episode1
production request through the real SQLite queue and resource admission gate.
It exists because a workspace without visible cgroup limits must remain blocked;
host totals or made-up telemetry are never a substitute.

The workflow uses only a standard `ubuntu-24.04` runner in this public repository,
read-only repository permissions, public dependency/model downloads, and an
artifact upload. GitHub documents standard public-repository runners as free:
[runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
No paid runner, credential changes, deployment, recurring schedule or publishing
is introduced. The production job runs only for an owner-triggered manual run on
main, or an owner-triggered same-repository PR touching its three implementation
files. Fork PRs cannot run production. Run concurrency is one.

Content Control is pinned to commit
`7a1caa4c6ffdc241681b2c69664c74e737784bd3`; changing the producer requires a reviewed
workflow pin update. Setup reuses its existing free CPU/picture dependencies.
The cached public speech model is fetched before production; production then
uses the existing offline, guarded stage runner. The adapter takes its own fresh
snapshot under shared admission and still reserves two CPU cores for the OS,
two for rendering, and the existing memory allowance. Unknown or insufficient
capacity remains a failed proof, with its receipts retained.

To execute, choose this workflow in GitHub Actions and run it on `main`. It has
no arbitrary commands, source branch input, retry loop or publishing input.
The 25-minute job contains a 900-second producer deadline and a one-attempt
queue envelope. A blocked or interrupted run must be reviewed before starting
another manual run; a new workflow run creates a new queue, not a cross-run
exactly-once guarantee.

The artifact `queued-unpublished-video-RUN_ID-RUN_ATTEMPT`, retained for 30 days,
contains:

- `host-observation.json`: actual runner telemetry, not an admission override.
- `source.json` and `job.json`: exact source manifest and immutable request.
- `queue/queue.sqlite3`: closed queue database with attempt and worker receipts.
- `queue/attempts/hosted-episode1-review/1/review/`: video, captions and stage receipts.
- `hosted-queue-verification.json`: a separate process reopens the database and
  rechecks source, candidate, pipeline and artifact identities after execution.

`QUEUED_PACKET_VERIFIED` means the queue completed one admitted job and the
unpublished packet passed technical identity checks. It does not mean creative
approval, final audiovisual approval, actual PC/VPS execution or 24/7 service.
The runner is ephemeral; only a successful artifact upload retains the archived
queue beyond it. A continuously available host, backup policy and restart/soak
evidence remain separate requirements. Publishing and paid generation stay off.

Local contract tests use explicitly synthetic packets, never pretend render
evidence. The hosted production job supplies actual rendering/inference evidence:

```bash
python -m unittest -v integrations.content_control.test_hosted_queue
```
