#!/usr/bin/env python3
"""Manual read-only CI evidence probe. See ci_status.md."""
import argparse
import copy
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


class Probe:
    def __init__(self, capture, live=False):
        self.capture = capture
        self.live = live
        self.errors = []

    def get(self, path):
        responses = self.capture['responses']
        if self.live and path not in responses:
            try:
                proc = subprocess.run(
                    ['gh', 'api', '--hostname', 'github.com', '--method', 'GET',
                     '--include', '-H', 'Accept: application/vnd.github+json',
                     '-H', 'X-GitHub-Api-Version: 2026-03-10', path],
                    capture_output=True, timeout=45)
                raw = proc.stdout.decode()
                header, body = re.split(r'\r?\n\r?\n', raw, maxsplit=1)
                code = int(header.splitlines()[0].split()[1])
                if proc.returncode and code == 200:
                    raise ValueError('incomplete gh response')
                links = re.findall(r'<([^>]+)>; rel="next"', header)
                links = [x.removeprefix('https://api.github.com/') for x in links]
                responses[path] = {'http_status': code, 'body': json.loads(body),
                                   'next': links[0] if links else None}
            except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                responses[path] = {'http_status': None, 'body': None, 'next': None}
        value = responses.get(path)
        if not isinstance(value, dict) or value.get('http_status') != 200:
            self.errors.append({'path': path, 'reason': 'unavailable',
                                'http_status': value.get('http_status') if value else None})
            return None
        if 'next' not in value:
            self.errors.append({'path': path, 'reason': 'pagination_metadata_missing'})
        return copy.deepcopy(value)

    def one(self, path):
        value = self.get(path)
        return value['body'] if value else None

    def listing(self, path, key=None):
        result, seen, total = [], set(), None
        while path:
            if path in seen or len(seen) >= 100:
                self.errors.append({'path': path, 'reason': 'pagination_loop_or_limit'})
                break
            seen.add(path)
            value = self.get(path)
            if value is None:
                break
            body = value['body']
            rows = body.get(key) if key and isinstance(body, dict) else body
            if not isinstance(rows, list):
                self.errors.append({'path': path, 'reason': 'invalid_list'})
                break
            if key == 'statuses' and body.get('sha') != self.capture['head']:
                self.errors.append({'path': path, 'reason': 'foreign_status_head'})
            if key:
                count = body.get('total_count')
                if type(count) is not int or (total is not None and total != count):
                    self.errors.append({'path': path, 'reason': 'invalid_or_changed_total'})
                total = count
            result.extend(rows)
            next_path = value.get('next')
            if next_path and not next_path.startswith('repos/' + self.capture['repository'] + '/'):
                self.errors.append({'path': path, 'reason': 'foreign_next_page'})
                break
            path = next_path
        if total is not None and total != len(result):
            self.errors.append({'path': path, 'reason': 'count_mismatch'})
        return result


def outcome(row, status=False):
    if status:
        return row.get('state', 'unknown')
    if row.get('status') != 'completed':
        return row.get('status') or 'unknown'
    return row.get('conclusion') or 'unknown'


def evaluate(probe):
    c = probe.capture
    root = 'repos/' + c['repository']
    head, branch = c['head'], quote(c['branch'], safe='')
    base = root + '/branches/' + branch
    branch_info = probe.one(base)
    rules = probe.listing(root + '/rules/branches/' + branch + '?per_page=100')
    required = []
    protected = branch_info.get('protected') if isinstance(branch_info, dict) else None
    if type(protected) is not bool:
        protected = None
        probe.errors.append({'path': base, 'reason': 'invalid_branch_protection_flag'})
    if protected is not False:
        protection = probe.one(base + '/protection')
        if isinstance(protection, dict) and 'required_status_checks' in protection:
            checks = protection.get('required_status_checks')
            if checks:
                required.extend({'context': x['context'], 'app_id': x.get('app_id')}
                                for x in checks.get('checks', []))
                names = {x['context'] for x in required}
                required.extend({'context': x, 'app_id': None}
                                for x in checks.get('contexts', []) if x not in names)
        else:
            probe.errors.append({'path': base, 'reason': 'protection_unknown'})
    for rule in rules:
        if rule['type'] == 'required_status_checks':
            required.extend({'context': x['context'], 'app_id': x.get('integration_id')}
                            for x in rule['parameters']['required_status_checks'])
        if rule['type'] == 'workflows':
            probe.errors.append({'path': base, 'reason': 'required_workflow_policy_not_evaluated'})
    config_known = not probe.errors and protected is not None
    checks = probe.listing(root + '/commits/' + head + '/check-runs?per_page=100&filter=latest', 'check_runs')
    statuses = probe.listing(root + '/commits/' + head + '/status?per_page=100', 'statuses')
    suites = probe.listing(root + '/commits/' + head + '/check-suites?per_page=100', 'check_suites')
    runs = probe.listing(root + '/actions/runs?head_sha=' + head + '&per_page=100', 'workflow_runs')
    jobs = []
    for run in runs:
        rows = probe.listing(root + '/actions/runs/' + str(run['id']) + '/attempts/' + str(run['run_attempt']) + '/jobs?per_page=100', 'jobs')
        run['observed_job_count'] = len(rows)
        for row in rows:
            if row.get('run_id') != run['id'] or row.get('run_attempt') != run['run_attempt']:
                probe.errors.append({'reason': 'foreign_job_run_or_attempt', 'id': row.get('id')})
        jobs.extend(rows)
    for kind, rows in [('checks', checks), ('suites', suites), ('runs', runs), ('jobs', jobs)]:
        ids = set()
        for row in rows:
            if type(row.get('id')) is not int or row['id'] <= 0 or row.get('id') in ids or row.get('head_sha') != head:
                probe.errors.append({'reason': 'duplicate_or_foreign_head', 'kind': kind, 'id': row.get('id')})
            ids.add(row.get('id'))
    status_ids = [x.get('id') for x in statuses]
    if len(status_ids) != len(set(status_ids)) or any(type(x) is not int or x <= 0 for x in status_ids):
        probe.errors.append({'reason': 'duplicate_status'})
    # The combined endpoint returns the latest state of each status context.
    latest = {}
    for row in statuses:
        latest.setdefault(row['context'], row)
    gate = []
    for req in required:
        matches = [x for x in checks if x.get('name') == req['context'] and
                   (req['app_id'] in (None, -1) or x.get('app', {}).get('id') == req['app_id'])]
        states = [outcome(x) for x in matches]
        if req['context'] in latest:
            states.append(outcome(latest[req['context']], True) if req['app_id'] in (None, -1) else 'unknown')
        accepted = bool(states) and len(matches) <= 1 and all(x in ('success', 'skipped', 'neutral') for x in states)
        gate.append(dict(req, observed=states or ['absent'], accepted=accepted))
    policy = 'unknown' if not config_known or probe.errors else (
        'none' if not gate else 'accepted' if all(x['accepted'] for x in gate) else 'not_accepted')
    for suite in suites:
        suite['observed_check_count'] = sum(x.get('check_suite', {}).get('id') == suite['id'] for x in checks)
        suite['observed_actions_job_count'] = sum(x['observed_job_count'] for x in runs if x.get('check_suite_id') == suite['id'])
    observations = [outcome(x) for rows in (checks, suites, runs, jobs) for x in rows]
    observations += [outcome(x, True) for x in latest.values()]
    failed = any(x in ('failure', 'error', 'timed_out', 'cancelled', 'action_required', 'startup_failure') for x in observations)
    empty_suite = any(x['observed_check_count'] == 0 for x in suites)
    execution = 'unknown' if probe.errors else 'failure' if failed else (
        'success' if jobs and observations and all(x == 'success' for x in observations)
        and not empty_suite and all(x['observed_job_count'] > 0 for x in runs) else 'incomplete')
    return {'schema_version': 1, 'repository': c['repository'], 'head': head, 'branch': c['branch'],
            'captured_at': c['captured_at'], 'configuration': {'state': 'known' if config_known else 'unknown',
            'protected': protected, 'required_contexts': required},
            'required_gate': {'state': policy, 'contexts': gate, 'scope': 'status contexts only; not merge eligibility'},
            'execution': {'state': execution, 'observed_failure': failed},
            'actual_jobs': {'state': 'unknown' if probe.errors else 'absent' if not jobs else
                            'success' if all(outcome(x) == 'success' for x in jobs) else
                            'failure' if any(outcome(x) in ('failure', 'timed_out', 'cancelled', 'action_required') for x in jobs) else 'incomplete'},
            'test_execution': {'state': 'unverified', 'reason': 'Job and step names do not prove test contents or nonzero tests.',
                               'successful_job_ids': [x['id'] for x in jobs if outcome(x) == 'success']},
            'counts': {k: len(v) for k, v in [('check_runs', checks), ('commit_statuses', statuses), ('suites', suites), ('workflow_runs', runs), ('jobs', jobs)]},
            'check_runs': checks, 'commit_statuses': list(latest.values()), 'suites': suites,
            'workflow_runs': runs, 'jobs': jobs, 'acquisition_errors': probe.errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo')
    parser.add_argument('--head')
    parser.add_argument('--branch', help='Target branch whose required contexts apply')
    parser.add_argument('--replay', type=Path)
    parser.add_argument('--save', type=Path, help='Save GET response capture, without request headers')
    args = parser.parse_args()
    try:
        if args.replay:
            if args.repo or args.head or args.branch:
                parser.error('--replay cannot be combined with live target flags')
            capture = json.loads(args.replay.read_text())
        else:
            capture = {'schema_version': 1, 'repository': args.repo, 'head': args.head,
                       'branch': args.branch, 'captured_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'responses': {}}
        if (type(capture['schema_version']) is not int or capture['schema_version'] != 1
                or not re.fullmatch(r'[\w.-]+/[\w.-]+', capture['repository'] or '')
                or not re.fullmatch(r'[0-9a-f]{40}', capture['head'] or '') or not capture['branch']
                or not isinstance(capture['responses'], dict)):
            raise ValueError('invalid capture or target')
        probe = Probe(capture, live=not args.replay)
        report = evaluate(probe)
        if args.save:
            args.save.write_text(json.dumps(capture, indent=2) + '\n')
        print(json.dumps(report, indent=2))
        code = 2 if probe.errors else 0 if report['execution']['state'] == 'success' else 1
        if code:
            print('CI execution is not established as successful; inspect JSON evidence.', file=sys.stderr)
        return code
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
        print(json.dumps({'schema_version': 1, 'execution': {'state': 'unknown'}, 'error': 'invalid_input_or_response'}))
        print('Invalid input, response, or output path: ' + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
