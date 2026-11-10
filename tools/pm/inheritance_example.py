#!/usr/bin/env python3
"""Create a synthetic, self-contained inheritance example in a new directory."""
import argparse
import hashlib
import json
from pathlib import Path


def save(root, name, value):
    raw = json.dumps(value, indent=2).encode() if not isinstance(value, bytes) else value
    (root / name).write_bytes(raw)
    return {'path': name, 'sha256': hashlib.sha256(raw).hexdigest()}


def create(root):
    root.mkdir(parents=True, exist_ok=False)
    source = dict(save(root, 'source.txt', b'unchanged synthetic source\n'), name='source')
    cond = {'runtime': 'synthetic macOS arm64; Python3; limits not measured',
            'command': 'synthetic check (not executed)', 'suite': 'synthetic source checks'}
    run = {'schema_version': 1, 'run_id': 'old-1', 'head': '1' * 40, 'base': '0' * 40,
           'verdict': 'pass', 'provenance': {'kind': 'reconstructed', 'source': 'synthetic example only'},
           'conditions': cond, 'targets': [source],
           'evidence': [save(root, 'old-proof.txt', b'Synthetic old observation, no real execution\n')],
           'unverified': []}
    prior = save(root, 'old.json', run)
    data = {'schema_version': 1, 'head': '2' * 40, 'base': '0' * 40,
            'requirements': [{'id': 'source', 'conditions': cond, 'targets': [source]}],
            'prior_runs': [prior], 'new_runs': [],
            'inherited': [{'requirement': 'source', 'run_id': 'old-1'}]}
    save(root, 'input.json', data)
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='directory must not exist')
    create(parser.parse_args().output)
