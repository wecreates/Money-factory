# Content Control POD bridge

`readiness-grant.mjs` reads the existing CONTENT_READINESS.json object supplied by
the authoritative MF process, requires a scoped approval backed by an upstream
event, and signs a short-lived grant. It never changes a business max_mode.
Invoke with server-loaded data only; do not accept caller-supplied readiness or
approval objects at a public route.

`event-inbox.mjs` verifies Content Control event signatures and transactionally
deduplicates delivery. Apply `001_event_inbox.sql` through the existing migration
owner, then bind acceptPodEvent to an authenticated internal POST endpoint. This
module is not yet mounted in the deployed MF core: its runtime source is not in
this repository root. Downstream observations do not count as verified profit.

Tests: `node --test integrations/pod/readiness-grant.test.mjs`.
The corresponding Content Control change documents all twelve acceptance gates
in POD_IMPLEMENTATION_STATUS.md. Publishing stays disabled. Etsy pipelines are
outside this lane; their independent workflows are preserved.

Production-only approvals may now set `production_permission: true` and
`publication_permission: false`. Scope, expiry, evidence event and readiness
checks still apply. These grants authorize internal RESEARCH/PRELAUNCH work only;
LAUNCH requires explicit publication permission, healthy providers, launch
readiness and a bound package hash. The matching Content Control policy must be
deployed before using production-only grants. No grant adapter is mounted in a
live Money Factory service by this change.

## Python review production agent

Run a supplied review brief through the existing Content Control checkout:

```sh
python3 integrations/pod/production_agent.py --job reviewed-job.json \
  --content-control /path/to/content-control \
  --font /path/to/licensed-font.ttf --output /new/review-output
```

The job requires `publication_enabled: false`, `paid_generation_enabled: false`,
`platform`, `metadata`, `original_art`, `cover_template`, and for KDP an `interior`
containing a template and actual manuscript pages. `market_research` observations
are preserved as unassessed input, not invented market evidence. The test fixture
in `test_production_agent.py` demonstrates the schema with synthetic dimensions;
it must not be published as a product. Font selection belongs to the worker.

The agent invokes Content Control's Node coordinator and Python production modules,
checks the full manifest and each artifact, then writes a receipt. It creates real
art and PDFs, but deliberately reports REVIEW_REQUIRED. It does not provide a
live authorizing service, verified marketplace data, paid generation or publishing.

Cross-repository test:
`CONTENT_CONTROL_ROOT=/path/to/content-control python3 -m unittest discover -s integrations/pod -p 'test_*.py'`.
