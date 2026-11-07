# OpenProject task interoperability

Candidate adapter in Money Factory's existing repository worker. Content Control
uses the existing `scripts/repository_tools.py` bridge via `MONEY_FACTORY_ROOT`.
It converts actual existing queue formats instead of creating a second task app.
The implementation is file-only Python standard library code, with no HTTP
client, credential storage, account creation, server startup or upstream execution.

## Operations

`export-work-packages` accepts a JSON wrapper containing:

- `queue_kind`: `content-control` or `money-factory`
- `queue`: the corresponding existing `capability-queue.json` (`queue` array) or
  `integrations/queue.json` (`items` array) snapshot
- `selected_ids`: 1–100 explicitly selected queue IDs
- `project_id` and `type_id`: positive integer IDs supplied for the intended
  OpenProject instance; synthetic fixture IDs are not live configuration
- Optional `mappings`: `{queue_id, work_package_id, lock_version}` for existing
  remote work packages. Updates require the observed lock version.

It emits API-v3 request plans with subject, bounded task description and type
links. New tasks use the project-scoped create route; existing mappings use
PATCH with optimistic locking. Every plan includes a form-validation step,
`notify=false`, and `sent: false`. Only selected allowlisted task fields enter the
request body. Source account details, arbitrary metadata and unselected tasks
are not included. Subject text is bounded to the API's 255-character limit.

The stable `client_reference` is an external deduplication hint, **not an
OpenProject idempotency guarantee**. Before creating a task, reconcile that
reference with existing work packages and persist a reviewed mapping. An
uncertain create must be investigated before any retry. The adapter never sends
these requests. A plan is not server acceptance or permission to share its data.

`import-work-packages` accepts `{queue_kind, queue, mappings, collection}`. Each
mapping contains `queue_id` and `work_package_id`; `collection` is a supplied
API-v3 HAL collection with WorkPackage elements. The result is a copy of the
existing queue enriched with `openproject_observation` for explicitly mapped IDs.
It does not change local status, publication flags or production gates, and it
does not overwrite the canonical queue. A remote "Closed" status cannot turn a
local `BLOCKED` task into `VERIFIED` or `DONE`. Missing rows are unresolved, never
treated as deletion. Single-page inputs are never asserted to be full snapshots.

`readiness` returns `BLOCKED / OPENPROJECT_NOT_CONFIGURED`: no stable server,
authenticated connection, project/type schema or live round-trip is verified.

All jobs require `publication_enabled: false` and `paid_generation_enabled: false`.
Example offline executions after applying the central runner wiring:

```sh
python integrations/run.py integrations/openproject/fixtures/export-work-packages.job.json --runtime /tmp/cyzor-interop-runtime
python integrations/run.py integrations/openproject/fixtures/import-work-packages.job.json --runtime /tmp/cyzor-interop-runtime
```

Fixtures are synthetic. Outputs must be new paths. Keep real private queues,
exports and mappings outside public repository job files.

## Source and security review

Inspected source: `opf/openproject@b2f981098776c3c1522833273bc77158d71d5ccb` from
the development branch, with GPLv3 licensing. This source archive is not a stable
installer. `source-inspection.json` records exact read paths and hashes. No GPL
implementation is vendored into this independent protocol adapter. Any later
upstream distribution/modification needs its own applicable license review.

The pinned API documentation still supports project routes but marks them
deprecated in favor of workspace routes. This adapter explicitly selects the
project API-v3 compatibility profile; validate it against the stable version
chosen for the actual instance. Server form schemas can require custom fields,
different types or permissions. `server_schema_validated` therefore stays false.

The upstream project has a Rails/backend/database and separate frontend setup;
its root `postinstall` invokes frontend installation. No hooks, server code,
packages, ports or infrastructure were run/provisioned. Live activation needs a
chosen stable instance, approved destination and data-sharing scope, a securely
configured authorized connection, project/type/permission discovery, form
validation, and a real create/read/update round-trip with conflict handling.
Generating or configuring persistent credentials requires a separate approval.

## Tests

```sh
python -m unittest -v integrations/openproject/test_adapter.py
```

Tests cover both existing queue formats, selection/data minimization, duplicate
and injection guards, explicit mapping, optimistic locking, partial collections,
closed-status isolation, malformed HAL, file limits, no upstream/network execution
and honest blocked readiness. Input reads reject parent traversal and symlinks at
every ancestor, using descriptor-anchored no-follow traversal to resist path
replacement races. They do not prove a live OpenProject connection.
