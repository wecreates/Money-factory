#!/usr/bin/env python3
"""Verify actual hosted operations through the canonical Content Control bridge."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from run import ROOT
from smoke import smoke


def verify(runtime, content_control):
    bridge = content_control / 'scripts/repository_tools.py'
    if not bridge.is_file():
        raise ValueError('Content Control bridge is missing')

    def execute(job, worker_runtime):
        with tempfile.TemporaryDirectory(prefix='cyzor-bridge-') as directory:
            job_file = Path(directory) / 'job.json'
            job_file.write_text(json.dumps(job))
            result = subprocess.run(
                [sys.executable, str(bridge), str(job_file), '--runtime', str(worker_runtime)],
                env=dict(os.environ, MONEY_FACTORY_ROOT=str(ROOT), PUBLICATION_ENABLED='false'),
                capture_output=True, text=True, timeout=1900,
            )
            if result.returncode:
                try:
                    reason = json.loads(result.stderr)['error']
                except (ValueError, KeyError):
                    raise RuntimeError('Content Control bridge failed without a valid receipt')
                if reason in (
                    'Output or receipt already exists; use a new job output path',
                    'This worker does not support publication or paid generation',
                ):
                    raise ValueError(reason)
                raise RuntimeError(reason)
            return json.loads(result.stdout)

    report = smoke(runtime, executor=execute)
    report.update(
        schema_version=1,
        scope='Eight CPU operations executed through Content Control on a hosted runner; not full production readiness',
        production_ready=False,
        paid_generation_enabled=False,
        verified_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        money_factory_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        content_control_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=content_control, text=True).strip(),
        workflow_run_id=os.environ.get('GITHUB_RUN_ID'),
        workflow_run_attempt=os.environ.get('GITHUB_RUN_ATTEMPT'),
        blockers=['Wan CUDA host and model weights unavailable',
                  'Provider-backed generation and persistent hosted project state not verified'],
    )
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--content-control', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.runtime.resolve(), args.content_control.resolve())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
