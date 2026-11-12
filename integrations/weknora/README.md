# WeKnora knowledge bridge

Source reviewed: [Tencent/WeKnora at 30658b7d43bf6415537435c42a5c4e95f2766b8d](https://github.com/Tencent/WeKnora/tree/30658b7d43bf6415537435c42a5c4e95f2766b8d).
Upstream's LICENSE states MIT except its listed third-party components. This adapter is independently written code and does not incorporate or run those components.

## Existing Money Factory job runner operations

- `readiness`: reports service/database/model and authorization blockers.
- `prepare-search`: input `{ "knowledge_base_id":"kb-1", "query":"brand guidance", "match_count":10 }`. Produces the exact `/api/v1/knowledge-bases/{id}/hybrid-search` request shape. Vector matching and reranking are explicitly disabled, leaving keyword matching. It writes a request artifact only.
- `import-search`: input `{ "knowledge_base_id":"kb-1", "query":"brand guidance", "response": { "success":true, "data":[...] } }`. Accepts upstream `SearchResult` rows and produces research context with citation IDs, content, knowledge/chunk identity, and scores. Wrong-knowledge-base or duplicate identities fail closed. A valid empty search stays empty; no answer or citation is invented.

Example job:

```json
{"tool":"weknora","operation":"import-search","input":"integrations/weknora/example-search.json","output":"/tmp/weknora-research.json","publication_enabled":false,"paid_generation_enabled":false}
```

Save as a job file, then `python integrations/run.py JOB.json --runtime /tmp/cyzor-offline` from Money Factory. Output and its receipt must use new paths. Retrieved text is untrusted research material; it does not grant tool permissions or replace fact checking. Export authenticity is not independently verified.

## Live boundary

No document upload, knowledge-base creation, remote search, agent/chat, key generation, or credentials configuration occurs. A running WeKnora service, storage/database, configured models, authorized knowledge scope and tenant, and a real integration test remain necessary for live retrieval. Embedding, reranking and chat may incur provider costs if configured later. The current adapter cannot turn them on.

Contract evidence: `client/knowledgebase.go` (`SearchParams`, `SearchResult`, `HybridSearchDetailed`), `client/retrieval.go`, and `LICENSE` at the pin. The sample is synthetic, not actual private knowledge.

Verification: `python -m unittest discover -s integrations -p test_search_knowledge.py -v` and `test_reel_bridges.py`.
