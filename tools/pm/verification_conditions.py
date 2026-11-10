#!/usr/bin/env python3
"""Compare recorded verification conditions without running commands or fetching evidence."""

import argparse
import json
from pathlib import Path
import re
import sys


FIELDS = ('repository', 'revision', 'base', 'jdk', 'runtime', 'command', 'suite', 'resources')
RESOURCES = ('heap', 'cpu', 'memory', 'parallelism')
SCOPE = ('repository', 'revision', 'base', 'jdk', 'suite')


class InvalidInput(ValueError):
    def __init__(self, code, path):
        self.reason = {'code': code, 'path': path}


def require(ok, code, path):
    if not ok:
        raise InvalidInput(code, path)


def text_value(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in {
        'unknown', 'n/a', 'null', '?', 'unspecified'
    }


def keys(value, expected, path):
    require(isinstance(value, dict), 'expected_object', path)
    require(set(value) == set(expected), 'invalid_fields', path)


def strings(value, path):
    require(isinstance(value, list) and all(text_value(x) for x in value),
            'expected_strings', path)


def conditions(value, path):
    keys(value, FIELDS, path)
    for field in FIELDS[:-1]:
        item = value[field]
        require(item is None or text_value(item), 'expected_text_or_null', path + '.' + field)
        if field in ('revision', 'base') and item is not None:
            require(re.fullmatch('[0-9a-f]{40}', item) is not None,
                    'expected_full_sha', path + '.' + field)
    keys(value['resources'], RESOURCES, path + '.resources')
    for field, item in value['resources'].items():
        require(item is None or text_value(item), 'expected_text_or_null',
                path + '.resources.' + field)


def validate(data):
    keys(data, ('schema_version', 'requirements', 'runs'), '$')
    require(type(data['schema_version']) is int and data['schema_version'] == 1,
            'unsupported_schema', '$.schema_version')
    for collection in ('requirements', 'runs'):
        items = data[collection]
        require(isinstance(items, list) and bool(items), 'expected_nonempty_array', collection)
        seen = set()
        for index, item in enumerate(items):
            path = f'{collection}[{index}]'
            expected = ('id', 'conditions') if collection == 'requirements' else (
                'id', 'actor', 'role', 'conditions', 'result', 'evidence', 'unverified')
            keys(item, expected, path)
            require(text_value(item['id']), 'invalid_id', path + '.id')
            require(item['id'] not in seen, 'duplicate_id', path + '.id')
            seen.add(item['id'])
            conditions(item['conditions'], path + '.conditions')
            if collection == 'runs':
                require(text_value(item['actor']), 'invalid_actor', path + '.actor')
                require(item['role'] in ('author', 'review'), 'invalid_role', path + '.role')
                require(item['result'] in ('pass', 'fail', 'unknown', 'not_run'),
                        'invalid_result', path + '.result')
                strings(item['evidence'], path + '.evidence')
                strings(item['unverified'], path + '.unverified')
    return data


def flatten(value):
    return {**{k: value[k] for k in FIELDS[:-1]},
            **{'resources.' + k: v for k, v in value['resources'].items()}}


def unknowns(value):
    return [{'code': 'unknown_condition', 'path': k}
            for k, v in flatten(value).items() if v is None]


def eligibility(run):
    reasons = unknowns(run['conditions'])
    if run['result'] != 'pass':
        reasons.append({'code': 'result_' + run['result'], 'path': 'result'})
    if not run['evidence']:
        reasons.append({'code': 'missing_evidence', 'path': 'evidence'})
    if run['unverified']:
        reasons.append({'code': 'declared_unverified', 'path': 'unverified'})
    return reasons


def compare(data):
    runs = data['runs']
    authors = [r for r in runs if r['role'] == 'author']
    reviews = [r for r in runs if r['role'] == 'review']
    assessed = [{'id': r['id'], 'eligible_pass': not eligibility(r),
                 'result': r['result'], 'evidence': r['evidence'],
                 'unverified': r['unverified'], 'reasons': eligibility(r)} for r in runs]
    overlaps, added, scope_overlap = [], [], []
    for review in reviews:
        matches = [r['id'] for r in authors if r['conditions'] == review['conditions']]
        if matches:
            overlaps.append({'review': review['id'], 'authors': matches})
        else:
            added.append(review['id'])
        for author in authors:
            ac, rc = author['conditions'], review['conditions']
            if all(ac[k] is not None and ac[k] == rc[k] for k in SCOPE):
                differences = [k for k, v in flatten(ac).items() if v != flatten(rc)[k]]
                scope_overlap.append({'author': author['id'], 'review': review['id'],
                                      'different_fields': differences,
                                      'unknown_fields': [x['path'] for x in unknowns(ac)]})
    coverage = []
    for requirement in data['requirements']:
        target = requirement['conditions']
        reasons = unknowns(target)
        matching = [r for r in runs if r['conditions'] == target]
        covered = [r for r in matching if not eligibility(r) and not reasons]
        if not matching:
            reasons.append({'code': 'no_exact_run', 'path': 'conditions'})
        elif not covered:
            reasons.append({'code': 'no_eligible_pass', 'path': 'runs'})
        coverage.append({'id': requirement['id'], 'covered': bool(covered),
                         'author': [r['id'] for r in covered if r['role'] == 'author'],
                         'review': [r['id'] for r in covered if r['role'] == 'review'],
                         'matching_runs': [r['id'] for r in matching], 'reasons': reasons})
    return {'schema_version': 1, 'complete': all(r['covered'] for r in coverage),
            'evidence_verified': False, 'independence_verified': False,
            'overlap': overlaps, 'added_review_conditions': added,
            'scope_overlap': scope_overlap, 'runs': assessed, 'requirements': coverage,
            'unverified': [r['id'] for r in coverage if not r['covered']]}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_json_key', key)
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='JSON record file, read only')
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.input.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
        output = compare(validate(data))
    except InvalidInput as error:
        output = {'complete': False, 'errors': [error.reason]}
    except (OSError, UnicodeError, ValueError, RecursionError):
        output = {'complete': False, 'errors': [{'code': 'unreadable_or_invalid_json', 'path': '$'}]}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 2 if 'errors' in output else (0 if output['complete'] else 1)


if __name__ == '__main__':
    sys.exit(main())
