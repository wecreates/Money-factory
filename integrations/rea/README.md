# REA offline source analysis

Pinned official `rea-agents@6.4.0` (MIT), with npm dependency integrity lock. Uses upstream `analyze-javascript-application` to inspect an authorized local JavaScript directory without executing the target. This is a supplemental engineering evidence tool, not an Instagram downloader or renderer. The existing seven-provider registry remains unchanged.

Install in an isolated runtime using this directory's package.json and package-lock.json:

```
npm ci --prefix integrations/rea --ignore-scripts --omit=optional --no-audit --no-fund
python3 integrations/rea/adapter.py --runtime integrations/rea --target /authorized/source --output /new/evidence.json
REA_RUNTIME="$PWD/integrations/rea" python3 -m unittest discover -s integrations/rea -p 'test_*.py' -v
```

The adapter uses only a fixed offline analysis command, strips inherited provider credentials, uses temporary isolated configuration, refuses linked targets and output overwrite, and binds evidence to before/after file hashes. It does not register an MCP server or change account settings. Publication and paid generation remain false. Partial upstream observations are preserved as BLOCKED, never promoted to complete analysis. The process boundary is not an OS network sandbox.

Actual execution on 2026-10-13: upstream inventoried both fixture files but refused the parsing subprocess because this workspace's `ps -axo pid=,ppid=,pgid=,uid=,stat=,command=` fails with `fatal library error, lookup self`. REA requires functioning Linux procps process-ownership inspection. No check was bypassed. Full module/import analysis remains unverified here; a normal free Ubuntu runner is the next execution environment, not a paid provider. The real runtime test checks this exact BLOCKED condition when encountered, and must not be described as successful source analysis.

Official references: https://github.com/morluto/rea and its README CLI/static-JavaScript instructions. Native analyzers and browser/runtime capture are outside this adapter.
