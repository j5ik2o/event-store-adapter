#!/usr/bin/env python3
"""Check recorded run inheritance against explicit local bytes; never execute runs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

LIMIT = 1024 * 1024


class Invalid(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise Invalid(message)


def keys(value, fields):
    require(isinstance(value, dict) and set(value) == set(fields.split()),
            'invalid object fields: ' + fields)


def text(value):
    require(isinstance(value, str) and 0 < len(value) <= 2048 and value.strip() == value,
            'expected bounded nonempty text')
    return value


def digest(value, length=64):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{%d}' % length, value),
            'invalid hash')


def rows(value, nonempty=False):
    require(isinstance(value, list) and len(value) <= 128 and (value or not nonempty),
            'expected bounded array')
    return value


def unique(items):
    require(len(items) == len(set(items)), 'duplicate identity')


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def read(path):
    require(path.is_file(), 'missing or nonregular file: ' + str(path))
    with path.open('rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode),
                'nonregular file')
        data = stream.read(LIMIT + 1)
    require(len(data) <= LIMIT, 'file exceeds 1 MiB')
    return data


def parse(data):
    return json.loads(data.decode('utf-8'), object_pairs_hook=pairs)


def reference(row, directory, verified, named=False):
    keys(row, 'name path sha256' if named else 'path sha256')
    if named:
        text(row['name'])
    text(row['path'])
    digest(row['sha256'])
    path = directory / row['path']
    data = read(path)
    require(hashlib.sha256(data).hexdigest() == row['sha256'], 'artifact hash mismatch: ' + str(path))
    verified.append({'path': str(path), 'sha256': row['sha256'], 'bytes': len(data)})
    return data


def targets(value, directory, verified):
    rows(value, True)
    result = {}
    for row in value:
        reference(row, directory, verified, True)
        require(row['name'] not in result, 'duplicate target name')
        result[row['name']] = row['sha256']
    return result


def conditions(value):
    keys(value, 'runtime command suite')
    for item in value.values():
        if item is not None:
            text(item)
            require(item.lower() not in ('unknown', 'n/a', '?', 'null'), 'use null for unknown conditions')
    return value


def record(ref, directory, verified):
    value = parse(reference(ref, directory, verified))
    keys(value, 'schema_version run_id head base verdict provenance conditions targets evidence unverified')
    require(type(value['schema_version']) is int and value['schema_version'] == 1, 'unsupported run schema')
    text(value['run_id'])
    digest(value['head'], 40)
    digest(value['base'], 40)
    require(value['verdict'] in ('pass', 'fail', 'unknown', 'not_run'), 'invalid verdict')
    keys(value['provenance'], 'kind source')
    require(value['provenance']['kind'] in ('recorded', 'reconstructed'), 'invalid provenance')
    text(value['provenance']['source'])
    conditions(value['conditions'])
    parent = (directory / ref['path']).parent
    value['target_hashes'] = targets(value['targets'], parent, verified)
    rows(value['evidence'], True)
    hashes = []
    for evidence in value['evidence']:
        reference(evidence, parent, verified)
        hashes.append(evidence['sha256'])
    unique(hashes)
    for gap in rows(value['unverified']):
        text(gap)
    return value


def reasons(run, requirement, base):
    result = []
    if run['verdict'] != 'pass':
        result.append('original_verdict_' + run['verdict'])
    if run['unverified']:
        result.append('run_has_unverified')
    if any(v is None for v in run['conditions'].values()) or any(
            v is None for v in requirement['conditions'].values()):
        result.append('unknown_conditions')
    if run['conditions'] != requirement['conditions']:
        result.append('conditions_changed')
    if run['target_hashes'] != requirement['target_hashes']:
        result.append('targets_changed')
    if run['base'] != base:
        result.append('base_changed')
    return result


def inspect(path, output):
    data = parse(read(path))
    keys(data, 'schema_version head base requirements prior_runs new_runs inherited')
    require(type(data['schema_version']) is int and data['schema_version'] == 1, 'unsupported schema')
    digest(data['head'], 40)
    digest(data['base'], 40)
    output.update(head=data['head'], base=data['base'])
    requirements = {}
    for item in rows(data['requirements'], True):
        keys(item, 'id conditions targets')
        text(item['id'])
        require(item['id'] not in requirements, 'duplicate requirement')
        conditions(item['conditions'])
        item['target_hashes'] = targets(item['targets'], path.parent, output['verified_files'])
        requirements[item['id']] = item
    runs, evidence_seen = {}, set()
    for lane in ('prior_runs', 'new_runs'):
        for ref in rows(data[lane]):
            run = record(ref, path.parent, output['verified_files'])
            require(run['run_id'] not in runs, 'duplicate run identity')
            evidence = {e['sha256'] for e in run['evidence']}
            require(not evidence_seen.intersection(evidence), 'reused run evidence bytes')
            evidence_seen.update(evidence)
            if lane == 'new_runs':
                require(run['head'] == data['head'] and run['base'] == data['base'], 'new run revision mismatch')
            runs[run['run_id']] = (lane, run)
            output['observations'].append({'lane': lane, 'record': ref, 'run': run})
    links = []
    for link in rows(data['inherited']):
        keys(link, 'requirement run_id')
        text(link['requirement'])
        text(link['run_id'])
        require(link['requirement'] in requirements and link['run_id'] in runs, 'unknown inheritance link')
        require(runs[link['run_id']][0] == 'prior_runs', 'inheritance requires prior run')
        links.append((link['requirement'], link['run_id']))
    unique(links)
    new_ids, inherited_ids = set(), set()
    for rid, requirement in requirements.items():
        new, inherited, rejected = [], [], []
        for run_id, (lane, run) in runs.items():
            selected = (rid, run_id) in links
            if lane != 'new_runs' and not selected:
                continue
            why = reasons(run, requirement, data['base'])
            if why:
                rejected.append({'run_id': run_id, 'reasons': why})
            elif lane == 'new_runs':
                new.append(run_id)
                new_ids.add(run_id)
            else:
                inherited.append(run_id)
                inherited_ids.add(run_id)
        output['requirements'].append({'id': rid, 'state': 'new' if new else (
            'inherited' if inherited else 'unverified'), 'new': new, 'inherited': inherited,
            'rejected': rejected})
    output['unverified'] = [r['id'] for r in output['requirements'] if r['state'] == 'unverified']
    # An invalid inheritance claim cannot be hidden by a separate passing run.
    rejected_links = [r for r in output['requirements'] for bad in r['rejected']
                      if (r['id'], bad['run_id']) in links]
    output.update(inspection_complete=True, recorded_new_runs=sorted(new_ids),
                  inherited_runs=sorted(inherited_ids),
                  all_requirements_accounted=not output['unverified'] and not rejected_links,
                  current_execution_complete=all(r['new'] for r in output['requirements']) and not rejected_links)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    args = parser.parse_args()
    output = {'schema_version': 1, 'inspection_complete': False,
              'all_requirements_accounted': False, 'current_execution_complete': False,
              'authenticity_verified': False, 'execution_verified': False,
              'observations': [], 'verified_files': [], 'requirements': [], 'unverified': [], 'errors': []}
    try:
        inspect(args.input, output)
    except (OSError, ValueError, RuntimeError, RecursionError) as error:
        output['errors'].append(str(error)[:400])
    print(json.dumps(output, ensure_ascii=True, indent=2))
    return 2 if output['errors'] else (0 if output['all_requirements_accounted'] else 1)


if __name__ == '__main__':
    raise SystemExit(main())
