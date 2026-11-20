# Content tool installation queue

Inventory checked 2026-11-20 UTC. **Next phase: after the current video production and local-agent work.** This document records requested work; it does not install tools, start providers, authorize paid usage, or enable publication.

## Scope and status

The current executor skill catalog was fully paginated and contained none of the five named packages below. Repository inspection found the existing limited OpenMontage adapter. These findings do not establish what is installed on the user's computer or VPN host. FFmpeg binaries, similarly named tools, and documentation are not proof that a requested skill is installed or has executed successfully.

| Requested tool | Verified upstream | Current installation/configuration evidence | Next execution evidence |
| --- | --- | --- | --- |
| last30days | [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill), README at head `bb2f1ed2b9f6d07b90557c5eebd736b566533fec` | Not found in executor catalog or inspected Money Factory/Content Control integrations. No source credentials verified. | Review pinned source, install in intended host, run preflight, then a bounded research task using explicitly selected free sources; retain source links and timestamps. |
| Humanizer | [blader/humanizer](https://github.com/blader/humanizer), head `a32f24407364c74c812b43c15926d638bee1e072` | Not found in catalog/integrations. A generic Novan humanizer route is unrelated evidence, not this package. | Register the reviewed skill and complete a before/after writing sample that preserves facts and meaning. |
| ffmpeg-skill | [kajisho5/ffmpeg-skill](https://github.com/kajisho5/ffmpeg-skill), head `f65df46953d62afb8e0a767f3f7ca5f4bb40fc36` | Skill not found. Existing FFmpeg/FFprobe usage does not establish installation of this skill or its MCP tools. | Record installed version and per-tool doctor results, execute a local edit, then inspect its media probe and contact sheet. |
| Stickman Video Director | [kaomei/stickman-video-director](https://github.com/kaomei/stickman-video-director), head `7fa6a9a543694cac95775200eb2f731b5594da0d` | Not found in catalog/integrations. Current stick-picture production is not evidence of this upstream skill. | Review/install the pinned skill; produce a short Code Engine sample with audio, captions, actual playback and output hashes before a full video. |
| OpenMontage | [OpenMontageInc/OpenMontage](https://github.com/OpenMontageInc/OpenMontage); the original calesthio URL redirects here | Content Control already has [a local adapter](https://github.com/wecreates/content-control/tree/main/integrations/openmontage) pinned to `9327439db69021ab4b0e2776729bf3b58fdb5a87`: reviewed FFprobe audio probe and FFmpeg concat only. This is not the full current application or provider setup. | Reuse and verify the existing adapter first. Historical short receipt dated 2026-10-13 records hash-bound probe PASS ([run38472504826](https://github.com/wecreates/content-control/actions/runs/38472504826)); historical long receipt dated 2026-10-23 is BLOCKED. Obtain fresh candidate-bound acceptance before claiming current execution. |
| SIM skill pack | [Creator reel](https://www.instagram.com/reel/DfqzrDSNS_x/) | Frame00:03 visibly says “SIM — A Claude skill pack”; the transcript describes11 skills for niche research, hooks, characters, episodes and monetization. No canonical download/repository was verified. Creator's public25-repository inventory and official library did not expose SIM; `Jakeschincariol/sim-skill` returned404. | Obtain the creator's actual source link, verify its identity and contents, then inspect dependencies before installation. Do not substitute unrelated SIM packages or send a comment/DM to unlock a link. |

## Dependencies and cost boundary

Upstream README claims are prerequisites to verify, not local execution evidence:

- last30days has a free-source subset plus optional paid APIs and authenticated browser sources. Review preflight before any credential/session use.
- Humanizer is a text instruction skill; it still uses the chosen agent's inference.
- ffmpeg-skill uses Python3.10+ and local FFmpeg/FFprobe; optional transcription requires a local ASR engine/model. Its setup command may install system packages, so inspect the selected installation route first.
- Stickman Code Engine renders locally but image/TTS services may cost money; Model Engine uses external generation credits.
- Full OpenMontage supports local and paid providers. Preserve its AGPL notices and retain the reviewed local-only adapter boundary; no provider activation follows from this queue.
- SIM dependencies remain unknown. The reel's Higgsfield workflow is not proof of free or configured execution.

No financial actions, sensitive credential handling, publishing, or new public network exposure are authorized by this document.

## Actual-host verification

Only the scratch Linux desktop and cloud browser were accessible during this check; no actual user PC/VPN execution surface was verified. Run the [capacity diagnostic](../integrations/AGENT_CAPACITY.md) on the intended host and record fresh CPU/RAM, measured model/render reserves, installed runtime versions, and a completed local inference receipt. A VPN supplies connectivity, not compute. Ruflo/OpenClaw share one per-user admission lock; their allowances must not be added together. OpenClaw requires Linux/WSL2 for its current runner.

Complete this queue with pinned source revisions, installation paths, actual execution receipts, and remaining blockers. Keep publication disabled throughout.
