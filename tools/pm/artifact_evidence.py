#!/usr/bin/env python3
"""Inspect explicit PM artifacts manually, without inferring historical progress."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat

MAX_JSON = 1024 * 1024
MAX_FILES = 256
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
ROLES = {'script', 'raw', 'log', 'report'}


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def load(path):
    require(path.is_file(), 'input must be an explicit regular JSON file')
    with path.open('rb') as source:
        data = source.read(MAX_JSON + 1)
    require(len(data) <= MAX_JSON, 'JSON byte limit exceeded; input incomplete for inspection')
    return json.loads(data, object_pairs_hook=pairs)


def text(value):
    require(isinstance(value, str) and 0 < len(value) <= 1024 and value.strip() == value,
            'expected nonempty bounded string')
    require(not any(ord(c) < 32 for c in value), 'control characters are unsupported')
    return value


def path_value(value, base):
    value = text(value)
    require(not any(c in value for c in '*?[]'), 'glob paths are unsupported')
    path = Path(value)
    return (base / path).resolve()


def timestamp(value):
    value = text(value)
    require('T' in value, 'deadline must be an ISO8601 datetime')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'deadline must include a timezone')
    return parsed


def rows(value):
    require(isinstance(value, list) and len(value) > 0, 'file list must be nonempty')
    require(len(value) <= MAX_FILES, 'file count limit exceeded; no complete inspection')
    require(all(isinstance(row, dict) for row in value), 'file rows must be objects')
    return value


def contract(path):
    value = load(path)
    require(isinstance(value, dict), 'contract must be an object')
    task = text(value.get('task_id'))
    root = path_value(value.get('artifact_root'), path.parent)
    require(not root.exists() or root.is_dir(), 'artifact_root must be a directory')
    first = path_value(value.get('first_artifact'), path.parent)
    deadline = timestamp(value.get('deadline'))
    required = {}
    for row in rows(value.get('required_files')):
        target = path_value(row.get('path'), path.parent)
        role = row.get('role')
        require(isinstance(role, str) and role in ROLES, 'unsupported or missing evidence role')
        require(target not in required, 'duplicate required file')
        required[target] = role
    require(set(required.values()) == ROLES, 'required roles are script, raw, log, report')
    require(all(p.is_relative_to(root) and p != root for p in [first, *required]),
            'contract files must be inside artifact_root')
    require(all(not p.exists() or p.is_file() for p in [first, *required]),
            'contract evidence must be explicit regular files')
    return task, first, deadline, required


def progress(first, deadline):
    present = first.is_file()
    return {'first_artifact': str(first), 'first_present_now': present,
            'first_state': 'present_now' if present else (
                'overdue_missing' if datetime.now(timezone.utc) > deadline else 'pending_missing'),
            'historical_saved_at': 'unknown', 'completed_by_deadline': 'unknown',
            'continuous_progress': 'unknown'}


def manifest(path):
    value = load(path)
    if isinstance(value, dict):
        require(not ('files' in value and 'artifacts' in value), 'ambiguous manifest wrapper')
        require('files' in value or 'artifacts' in value, 'unsupported manifest wrapper')
        require(value.get('complete', True) is True and value.get('truncated', False) is False,
                'manifest declares incomplete or truncated evidence')
        value = value.get('files', value.get('artifacts'))
    result = {}
    total = 0
    for row in rows(value):
        target = path_value(row.get('path'), path.parent)
        require(target != path.resolve(), 'manifest cannot include itself')
        require(target not in result, 'duplicate resolved file path')
        size, digest = row.get('bytes'), row.get('sha256')
        require(type(size) is int and 0 <= size <= MAX_FILE, 'invalid bytes or per-file limit exceeded')
        require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest) is not None,
                'sha256 must be 64 lowercase hexadecimal characters')
        total += size
        require(total <= MAX_TOTAL, 'total byte limit exceeded')
        result[target] = (size, digest)
    return result


def fingerprint(path, budget):
    require(path.is_file(), 'missing file or non-regular file')
    with path.open('rb') as source:
        require(stat.S_ISREG(os.fstat(source.fileno()).st_mode), 'expected regular file')
        digest, size = hashlib.sha256(), 0
        while True:
            chunk = source.read(min(65536, MAX_FILE + 1 - size, budget + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            require(size <= MAX_FILE and size <= budget, 'actual file byte limit exceeded')
            digest.update(chunk)
    return size, digest.hexdigest()


def run(args):
    if args.command == 'progress':
        task, first, deadline, _ = contract(args.contract)
        observation = progress(first, deadline)
        return {'task_id': task, 'observation': observation, 'evidence': 'not_assessed'}, (
            0 if observation['first_present_now'] else 1)
    if args.command == 'generate':
        task, first, deadline, required = contract(args.contract)
        require(args.output.resolve() not in required and args.output.resolve() != first,
                'final manifest must be separate from first and required evidence')
        files, total = [], 0
        for path in required:
            path_value(str(path), args.output.parent)
            size, digest = fingerprint(path, MAX_TOTAL - total)
            total += size
            files.append({'path': str(path), 'bytes': size, 'sha256': digest})
        serialized = json.dumps({'schema_version': 1, 'complete': True, 'files': files}, indent=2) + '\n'
        require(len(serialized.encode('utf-8')) <= MAX_JSON, 'generated manifest JSON byte limit exceeded')
        with args.output.open('x', encoding='utf-8', newline='\n') as output:
            output.write(serialized)
        return {'task_id': task, 'generated_files': len(files), 'evidence': 'not_assessed',
                'observation': progress(first, deadline)}, 0
    expected = manifest(args.manifest)
    total = 0
    for path, recorded in expected.items():
        actual = fingerprint(path, MAX_TOTAL - total)
        total += actual[0]
        require(actual == recorded, 'file bytes or SHA256 mismatch')
    result = {'integrity': 'matched_now', 'checked_files': len(expected),
              'checked_bytes': total, 'evidence': 'not_assessed', 'historical_completion': 'unknown'}
    if args.contract:
        task, first, deadline, required = contract(args.contract)
        require(args.manifest.resolve() not in required and args.manifest.resolve() != first,
                'final manifest must be separate from first and required evidence')
        observation = progress(first, deadline)
        complete = set(expected) == set(required)
        result.update(task_id=task, observation=observation,
                      checklist='matched' if complete else 'mismatch',
                      evidence='satisfied_now' if complete and observation['first_present_now'] else 'incomplete')
        return result, 0 if result['evidence'] == 'satisfied_now' else 1
    return result, 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('progress', 'generate', 'verify'):
        sub = commands.add_parser(name)
        if name == 'verify':
            sub.add_argument('manifest', type=Path)
            sub.add_argument('--contract', type=Path)
        else:
            sub.add_argument('contract', type=Path)
        if name == 'generate':
            sub.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result, code = run(args)
    except (OSError, ValueError, RuntimeError) as error:
        result, code = {'error': str(error)[:400], 'integrity': 'not_established',
                        'evidence': 'not_established', 'inspection_complete': False}, 2
    print(json.dumps(result, ensure_ascii=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
