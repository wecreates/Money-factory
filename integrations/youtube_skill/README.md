# YouTube agent skill operations

Runs the six actual dependency-free Python CLIs from `Jakeschincariol/youtube-agent-skill`, pinned to `a2feb2104981a375ffd4f87ee04f4f5344ac43c6` (MIT). `dispatch(job, upstream)` reads the JSON file at `job.input`, verifies the clean pinned upstream checkout, writes temporary input files, runs the selected upstream CLI with `--json`, and retains both parsed findings and original stdout/stderr.

Each job requires `publication_enabled: false` and `paid_generation_enabled: false`.

| Operation | JSON input fields |
|---|---|
| `hook-score` | `hook` |
| `package-lint` | `title`, `thumb` |
| `edit-plan` | `transcript_srt`, optional `floor` (default 0.45 seconds) |
| `chapters` | `transcript_srt`, optional `target` (default 7) |
| `retention` | `retention_csv`, `axis: "percent"`, `duration` in seconds; optional `transcript_srt` |
| `outliers` | `collected` video objects (`channel`, `title`, numeric `views`, optional `url`); optional `minimum_multiple` |

Retention CSV must contain exactly two columns: elapsed-video percentage and audience percentage, e.g. `0,100` through `100,45`, with at least eight increasing timeline points. Audience values may exceed 100% for repeat views. Raw YouTube ratios require conversion to percentage units first. The explicit axis avoids upstream's ambiguous short-duration seconds heuristic.

SRT timings must be increasing and non-overlapping. Inputs are bounded. No shell command strings, external URL fetches, account credentials, paid APIs, or publication actions are used. The inherited child environment is reduced; this process boundary is not an OS sandbox.

`status` and `execution_status` describe whether the actual CLI completed and returned JSON. They do **not** approve its findings. A weak hook, title issues, invalid chapter list, or insufficient channel samples remains explicit in `findings` even when execution succeeds. Hook scores are heuristics, not audience predictions. Edit plans do not modify media. Chapters remain draft labels. Outliers rank only the supplied sample; no market collection or popularity verification is implied.

```sh
YOUTUBE_SKILL_UPSTREAM=/absolute/youtube-agent-skill \
  python -m unittest discover -s integrations/youtube_skill -p 'test_*.py' -v
```

The eleven upstream skill documents are workflows for an agent; only the six executable tools listed here are claimed as deterministic integration operations. Analytical fixtures marked synthetic are test data, not actual audience analytics.
