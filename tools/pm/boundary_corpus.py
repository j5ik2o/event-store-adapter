#!/usr/bin/env python3
"""Run the four PM CLI boundary contracts offline. See boundary_corpus.md."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys
import tempfile

TARGETS = ('pr_file_diff', 'repository_coverage', 'artifact_evidence', 'ci_status')
RECIPES = {
    'pr_file_diff': ('normal', 'invalid_marker', 'huge_hunk_integer'),
    'repository_coverage': ('integer', 'bool', 'float', 'deep', 'acquisition_error'),
    'artifact_evidence': ('roundtrip', 'absolute_path', 'json_escape', 'invalid_contract'),
    'ci_status': ('replay',),
}


class Unsupported(Exception):
    pass


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')


def prepare(case, directory, python):
    """Create only named local recipes; corpus data contains no command templates."""
    target, recipe = case['target'], case['recipe']
    env = {k: v for k, v in os.environ.items() if not k.startswith(('GH_', 'GITHUB_'))}
    env.update(HOME=str(directory), TMPDIR=str(directory), PYTHONDONTWRITEBYTECODE='1')
    output = directory / 'manifest.json'
    if target == 'ci_status':
        save(directory / 'input.json', case['fixture'])
        return ['--replay', str(directory / 'input.json')], env, output
    if target == 'pr_file_diff':
        meta = {'head': {'sha': '1' * 40}, 'base': {'sha': '2' * 40},
                'changed_files': 1, 'additions': 1, 'deletions': 1}
        patch = '@@ -1 +1 @@\n-a\n+b'
        if recipe == 'invalid_marker':
            patch = '@@ -1 +1 @@\n\\ No newline at end of file\n-a\n+b'
        elif recipe == 'huge_hunk_integer':
            patch = '@@ -' + '9' * 5000 + ' +1 @@\n-a\n+b'
        row = {'filename': 'x', 'status': 'modified', 'sha': '3' * 40,
               'additions': 1, 'deletions': 1, 'changes': 2, 'patch': patch}
        save(directory / 'responses.json', [meta, [row], meta])
        driver = directory / 'fake-gh.py'
        driver.write_text('''
import json, pathlib, sys
p = pathlib.Path(__file__).parent
args = sys.argv[1:]
if args[:1] != ['api'] or '--method' not in args or args[args.index('--method')+1] != 'GET':
    sys.exit(91)
with (p/'calls.jsonl').open('a') as f:
    f.write(json.dumps(args)+'\\n')
n = len((p/'calls.jsonl').read_text(encoding='utf-8').splitlines())
responses = json.loads((p/'responses.json').read_text(encoding='utf-8'))
if n > len(responses):
    sys.exit(92)
print(json.dumps(responses[n-1]))
''', encoding='utf-8')
        fake = directory / 'gh'
        fake.write_text('#!/bin/sh\nexec ' + shlex.quote(python) + ' -B ' +
                        shlex.quote(str(driver)) + ' "$@"\n', encoding='utf-8')
        fake.chmod(0o700)
        env['PATH'] = str(directory)
        return ['owner/repo', '1', '--file', 'x'], env, output
    if target == 'repository_coverage':
        ledger = {'schema_version': True if recipe == 'bool' else 1.0 if recipe == 'float' else 1,
                  'sources': {'fixture': {'url': 'https://example.invalid', 'scope': 'synthetic'}},
                  'repositories': [{'repo': 'j5ik2o/example', 'sources': ['fixture']}]}
        inventory = {'at': '2026-11-10T00:00:00Z', 'results': [
            {'repo': 'example', 'prs': 0, 'issues': 0, 'milestones': [], 'pagination': []}]}
        if recipe == 'acquisition_error':
            inventory['results'] = [{'repo': 'example', 'error': 'recorded acquisition failure'}]
        save(directory / 'ledger.json', ledger)
        save(directory / 'input.json', inventory)
        raw = {'data': {'repository': dict(name='example', **{
            k: {'nodes': [], 'pageInfo': {'hasNextPage': False}}
            for k in ('pullRequests', 'issues', 'milestones')})}}
        save(directory / 'example.json', raw)
        if recipe == 'deep':
            payload = json.dumps(raw)
            payload = payload.replace('"name": "example"', '"name": "example", "extra": ' + '[' * 1100 + '0' + ']' * 1100)
            (directory / 'example.json').write_text(payload, encoding='utf-8')
        return ['--ledger', str(directory / 'ledger.json'), '--inventory',
                str(directory / 'input.json'), '--records-dir', str(directory)], env, output
    root = directory
    if case.get('long_path'):
        if not hasattr(os, 'pathconf') or os.pathconf(directory, 'PC_PATH_MAX') < 3500:
            raise Unsupported('long Unicode path requires PATH_MAX >=3500; Linux case unexecuted')
        levels = 14 if recipe == 'absolute_path' else 10
        expanded = directory.joinpath(*(['あ' * 75] * levels))
        if recipe == 'json_escape' and len(str(expanded / 'f255.txt')) > 1024:
            raise Unsupported('JSON byte limit fixture cannot be isolated within the 1024-character path limit')
        try:
            for _ in range(levels):
                root = root / ('あ' * 75)
                root.mkdir()
        except OSError as exc:
            raise Unsupported('fixture path could not be created: ' + str(exc)) from exc
    roles = ('script', 'raw', 'log', 'report')
    count = 256 if recipe == 'json_escape' else 4
    rows = [{'path': 'f' + str(i) + ('é"\\.txt' if recipe == 'roundtrip' else '.txt'),
             'role': roles[i % 4]} for i in range(count)]
    for row in rows:
        (root / row['path']).write_text('fixture\n', encoding='utf-8')
    spec = {'task_id': 'boundary', 'artifact_root': '.', 'first_artifact': rows[0]['path'],
            'deadline': '2026-01-01T00:00:00Z', 'required_files': rows}
    if recipe == 'invalid_contract':
        spec['required_files'] = rows[:1]
    save(root / 'contract.json', spec)
    output = root / 'manifest.json'
    return ['generate', str(root / 'contract.json'), '--output', str(output)], env, output


def invoke(python, script, args, directory, env, label):
    command = [python, '-B', str(script)] + args
    proc = subprocess.run(command, cwd=directory, env=env, capture_output=True, timeout=60)
    (directory / (label + '.stdout')).write_bytes(proc.stdout)
    (directory / (label + '.stderr')).write_bytes(proc.stderr)
    result = {'command': command, 'exit': proc.returncode,
              'stdout': proc.stdout.decode('utf-8'), 'stderr': proc.stderr.decode('utf-8')}
    save(directory / (label + '.json'), result)
    return result


def check(result, expected, output):
    problems = []
    if result['exit'] != expected['exit']:
        problems.append('exit: expected %s, got %s' % (expected['exit'], result['exit']))
    try:
        report = json.loads(result['stdout'])
    except (ValueError, RecursionError):
        return problems + ['stdout is not one JSON value']
    if not isinstance(report, dict):
        return problems + ['stdout is not a JSON object']
    for pointer, value in expected.get('fields', {}).items():
        actual = report
        try:
            for key in pointer.split('/'):
                actual = actual[int(key)] if isinstance(actual, list) else actual[key]
            if type(actual) is not type(value) or actual != value:
                problems.append(pointer + ': expected ' + repr(value) + ', got ' + repr(actual))
        except (KeyError, IndexError, TypeError, ValueError):
            problems.append(pointer + ': missing')
    for key, fragment in expected.get('contains', {}).items():
        if not isinstance(report.get(key), str) or fragment not in report[key]:
            problems.append(key + ': expected diagnostic fragment ' + fragment)
    if bool(result['stderr']) != (expected['stderr'] == 'nonempty'):
        problems.append('stderr presence differs')
    if 'Traceback' in result['stderr']:
        problems.append('unexpected traceback')
    if output.exists() != expected['output']:
        problems.append('output creation differs')
    if 'errors' in expected and bool(report.get('acquisition_errors')) != expected['errors']:
        problems.append('acquisition_errors presence differs')
    return problems


def retention(result, fixture):
    try:
        report = json.loads(result['stdout'])
    except (ValueError, RecursionError):
        return ['retention: stdout is not one JSON value']
    if not isinstance(report, dict) or not isinstance(report.get('counts'), dict):
        return ['retention: missing report object or counts']
    arrays = {'check_runs': 'check_runs', 'suites': 'check_suites',
              'workflow_runs': 'workflow_runs', 'jobs': 'jobs', 'commit_statuses': 'statuses'}
    problems = []
    for name, source in arrays.items():
        rows = [row for response in fixture['responses'].values()
                if isinstance(response.get('body'), dict)
                for row in response['body'].get(source, [])]
        actual = report.get(name, [])
        count = report['counts'].get(name)
        if (not isinstance(actual, list) or type(count) is not int
                or count != len(rows) or len(actual) != len(rows)):
            problems.append(name + ': lost rows or counts')
            continue
        for original, observed in zip(rows, actual):
            if not isinstance(observed, dict):
                problems.append(name + ': raw observation is not an object')
                continue
            if any(k not in observed or json.dumps(observed[k], sort_keys=True) !=
                   json.dumps(v, sort_keys=True) for k, v in original.items()):
                problems.append(name + ': raw observation changed')
    return problems


def accepts_historical_integer(python, directory, env):
    probe = directory / 'integer-probe.py'
    probe.write_text("import json\ntry:\n    int('9' * 5000)\nexcept ValueError:\n"
                     "    accepts = False\nelse:\n    accepts = True\n"
                     "print(json.dumps({'accepts': accepts}))\n", encoding='utf-8')
    result = invoke(python, probe, [], directory, env, 'integer-probe')
    report = json.loads(result['stdout'])
    if (result['exit'] != 0 or result['stderr'] or not isinstance(report, dict)
            or type(report.get('accepts')) is not bool):
        raise ValueError('historical integer capability probe failed')
    return report['accepts']


def run_case(case, directory, python, script, historical=False):
    args, env, output = prepare(case, directory, python)
    result = invoke(python, script, args, directory, env, 'cli')
    expected = case['old_expect'] if historical else case['expect']
    if expected.get('special') == 'huge_integer':
        if accepts_historical_integer(python, directory, env):
            expected = {'exit': 1, 'fields': {'api_consistent': True,
                        'files/0/state': 'validated-api-patch'}, 'stderr': 'empty', 'output': False}
        else:
            return [] if result['exit'] == 1 and 'ValueError' in result['stderr'] and 'integer string conversion' in result['stderr'] and not result['stdout'] else ['old huge integer signature differs']
    if expected.get('special') == 'deep':
        return [] if result['exit'] == 1 and 'RecursionError' in result['stderr'] and not result['stdout'] else ['old recursion signature differs']
    if case['target'] == 'artifact_evidence' and case['recipe'] == 'roundtrip' and result['exit'] == 0:
        producer = check(result, {'exit': 0, 'fields': {'generated_files': 4,
                         'evidence': 'not_assessed'}, 'stderr': 'empty', 'output': True}, output)
        if producer:
            return producer
        (directory / 'generated.json').write_bytes(output.read_bytes())
        result = invoke(python, script, ['verify', str(output), '--contract', args[1]],
                        directory, env, 'reader')
    problems = check(result, expected, output)
    if expected.get('retain'):
        problems.extend(retention(result, case['fixture']))
    if case['target'] == 'pr_file_diff':
        call_log = directory / 'calls.jsonl'
        calls = call_log.read_text(encoding='utf-8').splitlines() if call_log.exists() else []
        if len(calls) != 3 and not historical:
            problems.append('fake gh did not serve all three saved responses')
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='New evidence directory; never overwrites')
    parser.add_argument('--case', action='append', dest='ids', help='Select exact case ID; repeatable')
    parser.add_argument('--historical-dir', type=Path, help='Explicit trusted source directory: SHA/target.py')
    args = parser.parse_args()
    root = (args.output or Path(tempfile.mkdtemp(prefix='pm-boundary-corpus-')) / 'run').resolve()
    if root.exists():
        parser.error('--output must name a new directory')
    root.mkdir(parents=True, exist_ok=False)
    cases = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))['cases']
    ids = [c['id'] for c in cases]
    if (len(set(ids)) != len(ids) or any(not re.fullmatch(r'[a-z][a-z0-9_-]*', i) for i in ids)
            or any(not re.fullmatch(r'[0-9a-f]{40}', c['old_sha']) for c in cases)
            or (args.ids and set(args.ids) - set(ids))):
        save(root / 'results.json', {'state': 'incomplete', 'error': 'duplicate or unknown case IDs'})
        return 2
    selected = [c for c in cases if args.ids is None or c['id'] in args.ids]
    results = []
    for case in selected:
        if case['target'] not in TARGETS or case['recipe'] not in RECIPES[case['target']]:
            results.append({'case': case['id'], 'state': 'incomplete', 'error': 'unsupported recipe'})
            continue
        directory = root / case['id']
        directory.mkdir()
        script = Path(__file__).with_name(case['target'] + '.py').resolve()
        entry = {'case': case['id'], 'state': 'incomplete'}
        try:
            entry['source_sha256'] = hashlib.sha256(script.read_bytes()).hexdigest()
            failures = run_case(case, directory, sys.executable, script)
            entry.update(state='fail' if failures else 'pass', failures=failures)
            if args.historical_dir and not failures:
                old = args.historical_dir.resolve() / case['old_sha'] / (case['target'] + '.py')
                old_dir = directory / 'historical'
                old_dir.mkdir()
                entry['old_sha256'] = hashlib.sha256(old.read_bytes()).hexdigest()
                failures = run_case(case, old_dir, sys.executable, old, historical=True)
                entry.update(state='fail' if failures else 'pass', historical_failures=failures,
                             historical='legal_control' if case.get('control') else 'regression_signature')
        except Unsupported as exc:
            entry.update(state='unsupported', error=str(exc))
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            entry.update(state='incomplete', error=type(exc).__name__ + ': ' + str(exc))
        results.append(entry)
    state = 'incomplete' if not results or any(r['state'] in ('incomplete', 'unsupported') for r in results) else 'fail' if any(r['state'] == 'fail' for r in results) else 'pass'
    summary = {'state': state, 'python': sys.version, 'platform': platform.platform(), 'cases': results,
               'scope': list(TARGETS), 'selected_cases': [c['id'] for c in selected],
               'full_corpus': len(selected) == len(cases),
               'external_GET': False, 'CI_enforcement': False}
    save(root / 'results.json', summary)
    save(root / 'manifest.json', {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in root.rglob('*') if p.is_file()})
    print(json.dumps({'state': state, 'results': str(root / 'results.json')}))
    return 0 if state == 'pass' else 1 if state == 'fail' else 2


if __name__ == '__main__':
    sys.exit(main())
