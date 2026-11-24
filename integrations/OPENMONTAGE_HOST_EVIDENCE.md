# Intended-host OpenMontage evidence gate

The current workspace cannot start ordinary Chromium because its process-singleton
socket is denied by policy. Do not weaken the sandbox. Run the existing
`browser_runtime_probe.py` on the authorized PC/VPN/VPS host, then retain that
receipt with one real full-application OpenMontage/Remotion render.

`openmontage_host_evidence.py` verifies the retained bundle against:

- the clean canonical OpenMontage checkout at `2e003e65fa99a0f329478a2c1cdcf26bc481933a`;
- a complete successful ordinary-browser probe receipt from the same hashed host,
  observed no more than one hour before the run (with at most five minutes of
  documented clock skew);
- the exact source entrypoint, input, output and bounded execution log hashes;
- zero provider calls, publishing and paid generation disabled, and no sandbox weakening;
- exact integer/boolean receipt fields and no evidence timestamp more than five minutes ahead;
- process success and an independent `ffprobe` observation of video plus audio.

The verifier copies the output and `ffprobe` executable into a private bounded
snapshot, hashes the same bytes it inspects, and re-hashes before returning. It
also checks the retained output before and after the probe. Subprocess output,
media bytes, execution time and clock skew all have hard ceilings. A mutation,
oversized artifact or noisy verifier executable fails closed.

The bundle must contain `consumer-receipt.json`, the browser receipt, input media,
output media and execution log. The consumer receipt schema is strict and is
defined by the required fields in `openmontage_host_evidence.verify`.

```bash
python integrations/openmontage_host_evidence.py \
  --bundle-root /absolute/path/to/evidence \
  --source-root /absolute/path/to/OpenMontage \
  --ffprobe /absolute/path/to/ffprobe
```

`OPENMONTAGE_HOST_EVIDENCE_BOUND` means the files and claims are consistently
bound. It does **not** independently observe the process, establish host ownership,
approve creative quality, replace complete audiovisual review, or prove 24-hour
operation. The C09/C10 acceptance items remain open until the real intended-host
run and all of their other requirements have independent evidence.
