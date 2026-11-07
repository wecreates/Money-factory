# Hypit bridge for CYZOR

This is project-owned Python code used by Money Factory's canonical job runner and Content Control's existing private worker. It does not import Hypit or run downloaded Skills, launch a browser, install packages, connect accounts, generate media, or publish. It is not a new public app or an upstream hosted-service wrapper.

## What works

- `status`: reports the offline bridge and an unverified deployment runtime. A `BLOCKED` result and process exit 2 are intentional, not a false installation pass.
- `prepare-project`: validates 1–24 original/user-owned local PNG assets, their SHA-256 identities, dimensions and explicit rights attestations; produces a concrete Hypit Author Source, Run Source, style recipe, project boundary and asset-copy manifest. The source creates a frame-exact silent storyboard. Human notes remain data in JSON and are never inserted into executable markup.
- `validate-export`: validates an exported local MP4 against its SHA-256, preparation binding and a completed native `hypit.build-result@1` manifest. It reads the manifest's actual direct local `final.video` file and requires identical bytes. External-file and forwarded outputs are deliberately not followed. The original Hypit report is never modified or rebranded.

Output `PASS` means the named offline transformation or intake passed. It never means the video was decoded, rights were independently verified, the installed runtime was tested on the deployment host, or the content is production-ready. Runtime smoke evidence below is a separate dated experiment.

The initial prep subset is a silent image storyboard, not narration, lip sync, model generation or an Instagram downloader. Hypit may mux a silent audio stream; no audible narration is promised. Inputs must be original or user-owned. A caller's attestation is not legal verification. All imports still require full media decode, duration/dimension checks, source-to-render comparison, rights and creative review.

## Canonical usage

From the Money Factory root, put this in a new job JSON file, using new output paths:

```json
{
  "tool": "hypit",
  "operation": "prepare-project",
  "input": "/absolute/path/to/preparation.json",
  "output": "/absolute/path/to/new/prepared-result.json",
  "publication_enabled": false,
  "paid_generation_enabled": false
}
```

```sh
python integrations/run.py /absolute/path/to/job.json --runtime /absolute/path/to/private-runtime
```

Or use the existing Content Control entry point:

```sh
MONEY_FACTORY_ROOT=/absolute/path/to/Money-factory python /absolute/path/to/content-control/scripts/repository_tools.py /absolute/path/to/job.json --runtime /absolute/path/to/private-runtime
```

Example preparation data (replace the path and SHA-256 with an actual owned image):

```json
{
  "project_id": "cyzor-original-story",
  "title": "Original CYZOR storyboard",
  "intended_use": "own_organization",
  "frame_rate": 30,
  "width": 1080,
  "height": 1920,
  "scenes": [{
    "id": "opening",
    "duration_frames": 90,
    "image": {
      "path": "/absolute/path/to/owned.png",
      "sha256": "REPLACE_WITH_64_LOWERCASE_HEX_CHARACTERS",
      "rights_basis": "user_owned",
      "rights_attested": true
    }
  }],
  "publication_enabled": false,
  "paid_generation_enabled": false
}
```

The result carries `project_files` (UTF-8 content keyed by four fixed relative file names) and `asset_transfers` (source paths, safe project-relative paths, sizes and hashes). No files are copied or materialized by the adapter. An authorized private worker can materialize those reviewed artifacts into a new project and recheck every asset digest. Source hashes and the full preparation are bound by `request_sha256`. Do not treat this binding as proof that an imported render came from those sources.

`validate-export` input contains `preparation` with that exact original input, disabled flags, and:

```json
{
  "export": {
    "path": "/absolute/path/to/exported.mp4",
    "sha256": "ACTUAL_MP4_SHA256",
    "request_sha256": "ACTUAL_PREPARATION_BINDING",
    "result_path": "/absolute/path/to/build/result.json",
    "result_sha256": "ACTUAL_NATIVE_RESULT_SHA256"
  }
}
```

The native report must be complete, target `final.video`, identify that output as `@hypit/blob@1#Blob`, and name a direct, contained local `build-file` with its correct size and `video/mp4` media type. Its original files must still exist. An MP4 header and a matching native report are identity checks, not decode or provenance certification. Failed/cancelled/unfinished results fail closed.

## Reviewed source and installation distinction

- GitHub source: [hypit-ai/hypit at e26d9142fd8a6f78bf4f3cdb800d6205f4ecca16](https://github.com/hypit-ai/hypit/tree/e26d9142fd8a6f78bf4f3cdb800d6205f4ecca16)
- Archive SHA-256: `9a1e40cb9597b8c8a9008735b0561faaae663f33a1ccaff19016ca13abf2bd2d`
- Source version field: 0.3.1. The archive was statically inspected, never executed or vendored into the application. Two agent-Skill symlinks were not extracted.
- Separately installed official npm release for the isolated test: `@hypit/hypit@0.3.1`. The registry identifies the official GitHub repository. `runtime-evidence/npm-install-evidence.json` records its npm SHA-512, exact resolved dependency lock hash and disabled hooks. npm source-commit equivalence is not claimed merely because versions match.
- The Hypit Skill and executable are separate products. No global Skill, machine-wide package, provider credential, account, model, Python inference environment or new browser was installed.

The sandbox test used a workspace-local install, HOME, cache and Hypit state directory:

```sh
npm install --prefix /absolute/path/to/isolated-runtime --save-exact --ignore-scripts --no-audit --no-fund --registry=https://registry.npmjs.org @hypit/hypit@0.3.1
```

npm added 115 packages. Install hooks were disabled, including esbuild's postinstall and koffi's native build hook. Upstream prepare scripts were also not run. The installed CLI was successfully invoked. Reproduce an approved environment from the provided lockfile with scripts disabled; do not silently substitute latest versions or enable hooks.

## Real isolated runtime proof, 2026-10-23

A synthetic original PNG, one second at 24 fps and 160×160, was prepared with this adapter and materialized outside both repositories. Existing Node 24.19, ffmpeg/ffprobe and `/usr/bin/chromium` were selected explicitly. Only `media.local` and `html.local` were in the credential-free Runtime Profile.

1. Official CLI `--version`: 0.3.1, passed.
2. `hypit check build.svrun`: actual upstream Run/Author check passed.
3. `hypit plan build.svrun --runtime hypit.runtime.json`: actual plan and preflight passed. All three requests were local and reported no provider charge: visual rasterization, silent audio timeline, final mux.
4. Build `bld_20261023T194055870Z_F831B5231E`: terminal failure. Existing Chromium could not create its process socket: `socket() failed: Operation not permitted`. There was also a Crashpad diagnostic. No final MP4 was produced. The restriction was not bypassed, escalated or retried.
5. The private Runtime Worker was shut down and reported stopped. No managed program preparation or download was run.

This proves the generated fixture is accepted by the real published Hypit compiler/planner; it does not prove a completed render. An allowed browser-capable deployment remains necessary. The offline adapter stays usable independently of that blocker. The official renderer's inspected source launches Chromium with its own `--no-sandbox` flag; this bridge does not add flags or alter system security settings. Its broad renderer should only be activated in a reviewed, appropriately isolated runtime with approved inputs.

`runtime-evidence/` preserves the original CLI logs and native failed manifest with Hypit identity unchanged, a lockfile, the original source fixture, selected Runtime Profile and a summary. No credentials, generated provider media or installed node_modules are included.

## License and costs

The upstream license is modified Apache-2.0 with additional conditions, not unqualified Apache-2.0. See the pinned [LICENSE](https://github.com/hypit-ai/hypit/blob/e26d9142fd8a6f78bf4f3cdb800d6205f4ecca16/LICENSE) and unchanged `UPSTREAM_LICENSE.txt`:

- Own-organization commercial/internal work and client work are permitted under its stated conditions.
- Offering Hypit functionality as a third-party hosted/multi-tenant service or commercially redistributing Hypit/derivatives needs separate producer authorization.
- Preserve Hypit name, logo and copyright on its CLI, reports/manifests and relevant derived surfaces.
- Hypit claims no rights in outputs; input rights and third-party provider terms still matter.

The bridge makes zero provider calls. The tested plan reports local requests with no provider charge. This is not a promise of zero infrastructure cost or free model usage. Paid generation, credential configuration, uploads, publication, third-party hosted use and production activation are not enabled by this adapter.

## Tests

```sh
python -m unittest discover -s integrations -p test_reel_hypit.py -v
```

22 tests cover preparation, deterministic binding, timing, rights, scope, strict booleans, blocked paid/network paths, malformed/oversized inputs, symlinks, checksums, native result binding, traversal, uncompleted results, report preservation and no network/process execution. The cross-repository test requires a sibling Content Control checkout, a content-control-bridge checkout, or CONTENT_CONTROL_ROOT; it visibly skips that one test if none exists. Synthetic MP4-signature fixtures deliberately test that intake never turns header recognition into a full-decode or production claim. The existing Content Control bridge path was also exercised for all three operations with hash-bound receipts (export intake uses an explicitly synthetic unit-test fixture).
