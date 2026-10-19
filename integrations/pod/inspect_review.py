"""Read-only reconciliation of an existing local review receipt and package."""
import argparse
import hashlib
import json
from pathlib import Path

from production_agent import (capture_job, output_chunks, parse_review_json, validate_result, review_directories,
                              validate_review_output, MAX_OUTPUT_JSON_BYTES, PLATFORMS)


def canonical(value):
    # Strict serialization also distinguishes booleans from JSON integers and
    # rejects nonfinite values that Python's permissive decoder can accept.
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def inspect_review(job, output):
    # Keep final path components unresolved: the shared readers reject symlinks
    # and nonregular files without blocking on FIFOs. Never rerender or write.
    body = capture_job(Path(job).absolute())
    spec = parse_review_json(body)
    if not isinstance(spec, dict):
        raise ValueError('JOB_INVALID')
    if spec.get('publication_enabled') is not False or spec.get('paid_generation_enabled') is not False:
        raise ValueError('REVIEW_ONLY_REQUIRED')
    platform = spec.get('platform')
    if not isinstance(platform, str) or platform not in PLATFORMS:
        raise ValueError('PLATFORM_BLOCKED')
    root = Path(output).absolute()
    with review_directories(root) as directories:
        receipt_body = b''.join(output_chunks('money-factory-receipt.json', MAX_OUTPUT_JSON_BYTES,
                                            dir_fd=directories[0]))
        receipt = parse_review_json(receipt_body)
        validate_result(receipt, platform)
        input_hash = hashlib.sha256(body).hexdigest()
        if receipt.get('input_sha256') != input_hash:
            raise ValueError('RECEIPT_INPUT_MISMATCH')
        result = validate_review_output(root, platform, directories=directories)
        result['input_sha256'] = input_hash
        if canonical(receipt) != canonical(result):
            raise ValueError('RECEIPT_RESULT_MISMATCH')
    return {'schema_version': 1, 'status': 'VERIFIED_REVIEW_FILES',
            'scope': 'local_files_only', 'review_status': 'REVIEW_REQUIRED',
            'input_sha256': input_hash, 'package_sha256': result['package_sha256'],
            'receipt_sha256': hashlib.sha256(receipt_body).hexdigest(),
            'publication_enabled': False, 'production_ready': False,
            'paid_generation_enabled': False, 'marketplace_ready': False,
            'durability_verified': False, 'approval_verified': False,
            'remaining_checks': result['remaining_checks']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(inspect_review(args.job, args.output), allow_nan=False))
