# OpenSEO research bridge

Source reviewed: [every-app/open-seo at 2d8236a4fd5d799bf5c089187d0131f4dac4f38c](https://github.com/every-app/open-seo/tree/2d8236a4fd5d799bf5c089187d0131f4dac4f38c).
The upstream application is MIT licensed. This adapter is independently written project code; no upstream code is vendored or executed.

## Available through the existing Money Factory runner

- `readiness`: reports the exact offline boundary; no input file needed.
- `prepare-research`: validates the bounded shape of an OpenSEO MCP `get_serp_results` request and writes it as a review artifact. Input uses `projectId`, `queries` (1–10 objects with `keyword` and optional market/device fields), and optional `depth` (10–100 in steps of ten). Actual project access, market/language support and account billing remain subject to upstream server validation.
- `import-serp`: converts an exported OpenSEO `structuredContent.results` object (or its direct contents) into keyword research and source links for acquisition/content planning. Preserves query errors, organic rank separately from overall SERP rank, input SHA-256, and unverified evidence scope. All-query failure returns `BLOCKED`.

Example job, run from the Money Factory root:

```json
{"tool":"open-seo","operation":"import-serp","input":"integrations/open_seo/example-serp.json","output":"/tmp/open-seo-research.json","publication_enabled":false,"paid_generation_enabled":false}
```

Save this object to a job file and run `python integrations/run.py JOB.json --runtime /tmp/cyzor-offline`. Each output path must be new. The adjacent receipt proves this local import and its output hash; it does not prove fresh search rankings or hosted readiness.

## Cost and execution gate

OpenSEO's source explicitly calls DataForSEO for fresh SERP research and charges credits. Even a cache-enabled request cannot be assumed free in advance. This bridge has no network client and cannot enable paid services, no matter which job flags are supplied. Request preparation is not submission, and no account, API key, subscription, OAuth grant, or budget was created. Live use needs separate runtime installation/review, authorized credentials, a defined spending approval, and an actual service test.

Contract evidence: `src/shared/mcp-contracts.ts`, `src/server/mcp/tools/get-serp-results.ts`, `README.md`, `LICENSE` at the pinned revision. Synthetic fixture data in `example-serp.json` tests shape only and is not a real SEO finding.

Verification: `python -m unittest discover -s integrations -p test_search_knowledge.py -v` and `test_reel_bridges.py`.
