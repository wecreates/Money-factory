# OpenHiggsfield offline handoff and export intake

Original Python integration code connects generation briefs and existing local
exports to CYZOR's private repository worker. No OpenHiggsfield implementation is
copied, installed, imported, bundled or executed. Reviewed source revision:
`b16a0efe4d7e2707b56f8ccb02387fd2a9d2eddf`.

## What works

All jobs require `tool: open-higgsfield`, an `operation`, and literal false
`publication_enabled` / `paid_generation_enabled`. Non-status operations read
the local JSON path in `input`. The common worker writes the returned JSON.

- `status` reports exact source pin, supported offline operations and unconfigured
  generation. Its PASS means the query succeeded, not live provider health.
- `prepare-generation` validates a brief and emits the reviewed upstream
  `GenerationPlane` shape: `model`, `prompt.text`, empty `media`, `settings`.
  Supported subset: `soul-2`, `soul-cinema` and text-only `kling-3-turbo`. Ratios
  are 9:16, 16:9 or 1:1; resolution 720p/1080p; video duration 3–15 seconds.
  Image handoffs are one result, prompt enhancement off. This subset is
  intentionally smaller than the upstream catalog. Unknown settings, credentials,
  media URLs, uploads and additional fields are rejected.
- `validate-export` accepts a supplied local artifact with its expected SHA-256
  and preparation hash. It checks a bounded regular-file snapshot, container
  signature and request identity, returning PENDING_MEDIA_DECODE_AND_REVIEW.
  It does not claim full media decoding, image dimensions, video duration,
  generation provenance, creative approval or commercial rights.

Preparation input:

```json
{
  "project_id":"product-demo",
  "scene_id":"hook",
  "model":"kling-3-turbo",
  "prompt":"An original pencil drawing of a growing plant.",
  "settings":{"aspectRatio":"9:16","resolution":"720p","duration":5},
  "publication_enabled":false,
  "paid_generation_enabled":false
}
```

Export-intake input:

```json
{
  "preparation":{"project_id":"product-demo","scene_id":"hook","model":"kling-3-turbo","prompt":"An original pencil drawing of a growing plant.","settings":{"aspectRatio":"9:16","resolution":"720p","duration":5},"publication_enabled":false,"paid_generation_enabled":false},
  "export":{"path":"/private/export.mp4","sha256":"<64 lowercase hex characters>","request_sha256":"<prepare-generation result request_sha256>","media_type":"video/mp4"},
  "publication_enabled":false,
  "paid_generation_enabled":false
}
```

Image intake accepts PNG/JPEG/WebP signatures, video intake MP4, maximum 64 MiB.
The local path is a locator; downstream Content Control must rehash and fully
decode before use, then apply its existing creative/rights/publication gates.
Caller-supplied export provenance is explicitly not authenticated. Files must
remain private and quiescent during intake; do not expose the worker as a public
arbitrary-file API. No artifact is automatically made current or approved.

## Source/security findings and remaining blockers

- No LICENSE was present in the pinned source; GitHub license metadata was null.
  A marketing description as open source is not sufficient reuse permission.
- The studio calls an external generation platform requiring `id:secret` keys;
  studio access being free does not establish free provider generation.
- Its blob-token route explicitly lacks authentication and gives callers upload
  tokens when a Vercel read/write token is configured. Uploaded media become
  public URLs. No credentials, uploads or public deployment are configured here.
- Its platform client logs request bodies. The original adapter emits no prompt
  logs and makes no network request.
- Next.js/React/Zustand and Vercel Blob dependencies were statically inspected,
  not installed. No vulnerability scan or runtime security certification is claimed.

There is intentionally no submit/poll transport. Live generation requires resolved
source/service rights, provider configuration through an approved secure route,
any required spending approval, and a separate real smoke test. Downloaded source,
offline preparation, and an export hash do not establish those conditions.

Sources:
- https://github.com/wide-trace/open-higgsfield/tree/b16a0efe4d7e2707b56f8ccb02387fd2a9d2eddf
- https://github.com/wide-trace/open-higgsfield/blob/b16a0efe4d7e2707b56f8ccb02387fd2a9d2eddf/src/generation/catalog/types.ts
- https://github.com/wide-trace/open-higgsfield/blob/b16a0efe4d7e2707b56f8ccb02387fd2a9d2eddf/src/app/api/blob/route.ts
- https://github.com/wide-trace/open-higgsfield/blob/b16a0efe4d7e2707b56f8ccb02387fd2a9d2eddf/src/generation/platform.ts

Tests: from `integrations`, run `python -m unittest -v test_reel_voice_video`.
The test MP4 is intentionally header-only; tests prove it stays pending full decode.
