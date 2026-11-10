#!/usr/bin/env python3
"""Manually compare saved T3 inventory with independently captured Git worktrees."""
import argparse
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import subprocess
import sys

from delegation_preflight import identity

STATUSES = {'idle', 'preparing', 'queued', 'starting', 'running', 'waiting',
            'completed', 'interrupted', 'failed', 'cancelled', 'rolled_back'}
GIT = {
    'root': ['rev-parse', '--show-toplevel'],
    'origin': ['config', '--local', '--get-all', 'remote.origin.url'],
    'head': ['rev-parse', '--verify', 'HEAD'],
    'branch': ['symbolic-ref', '--quiet', '--short', 'HEAD'],
    'status': ['status', '--porcelain=v1', '-z', '--untracked-files=all'],
    'log': ['log', '-5', '--format=%H %cI'],
    'upstream': ['rev-parse', '--symbolic-full-name', '@{upstream}'],
    'unpushed': ['rev-list', '--count', '@{upstream}..HEAD'],
    'worktrees': ['worktree', 'list', '--porcelain', '-z'],
}
CONDITIONS = ['PR_merged', 'post_merge_main_CI_success', 'no_uncommitted_changes',
              'no_unpushed_commits', 'no_assignee_using_tree', 'non_shared',
              'information_saved_to_PR_comment_validation_record',
              'no_failed_interrupted_waiting_owner', 'no_tree_only_artifacts',
              'ownership_and_approval_authenticated']


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def load(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda _: require(False, 'non-JSON constant'))


def string(value):
    require(type(value) is str and bool(value) and '\0' not in value, 'expected nonempty string')
    return value


def timestamp(value):
    parsed = datetime.fromisoformat(string(value).replace('Z', '+00:00'))
    require(parsed.utcoffset() is not None, 'timestamp needs timezone')


def integer(value):
    require(type(value) is int and value >= 0, 'expected nonnegative integer')


def now():
    return datetime.now(timezone.utc).isoformat()


def git(path, field, aliases):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0', LC_ALL='C')
    try:
        run = subprocess.run(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
                              '-c', 'core.untrackedCache=false', '-C', path] + GIT[field],
                             env=env, capture_output=True, timeout=15)
        if run.returncode:
            return {'error': 'git exit ' + str(run.returncode)}
        value = run.stdout.decode('utf-8')
        if value.endswith('\n'):
            value = value[:-1]
        if field == 'origin':
            value = identity(value, aliases)
            if value is None:
                return {'error': 'unrecognized or multiple origins'}
        return {'value': value}
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        return {'error': 'git observation unavailable'}


def porcelain(value):
    """Git -z leaves paths literal, including whitespace, Unicode and newlines."""
    require(type(value) is str, 'porcelain must be a string')
    rows, row = [], {}
    for token in value.split('\0'):
        if not token:
            if row:
                require('worktree' in row, 'missing worktree path')
                rows.append(row)
                row = {}
            continue
        key, _, val = token.partition(' ')
        require(key not in row, 'duplicate porcelain field')
        row[key] = val
    require(not row, 'unterminated porcelain record')
    return rows


def capture(roots):
    require(type(roots) is dict and type(roots.get('repositories')) is list, 'invalid roots')
    aliases = roots.get('host_aliases', {})
    require(type(aliases) is dict and all(type(k) is str and type(v) is str
            for k, v in aliases.items()), 'invalid aliases')
    output = dict(source='local allowlisted git commands', at=now(), repositories=[])
    for entry in roots['repositories']:
        repo, root = string(entry['repo']), string(entry['root'])
        require(Path(root).is_absolute(), 'root must be absolute')
        listing = git(root, 'worktrees', aliases)
        record = dict(repo=repo, root=root, listing=listing, trees=[])
        output['repositories'].append(record)
        if 'value' not in listing:
            continue
        for tree in porcelain(listing['value']):
            path = tree['worktree']
            fields = {k: git(path, k, aliases) for k in GIT if k != 'worktrees'}
            record['trees'].append(dict(path=path, at=now(), observations=fields))
    return output


def audit(export, observed, ledger):
    require(type(export) is dict and type(observed) is dict, 'expected objects')
    require(type(export.get('schema_version')) is int and export['schema_version'] == 1,
            'schema_version must be integer 1')
    for obj in (export, observed):
        string(obj['source'])
        timestamp(obj['at'])
    require(type(export.get('includeSubagents')) is bool, 'includeSubagents must be boolean')
    require(type(export.get('filters')) is dict, 'filters must be an object')
    require(type(export.get('auditPaths', [])) is list and all(type(p) is str for p in export.get('auditPaths', [])), 'invalid auditPaths')
    project, parent = string(export['projectId']), string(export['parentThreadId'])
    pages, metadata = export['pages'], export['metadata']
    require(type(pages) is list and type(metadata) is list, 'expected page/metadata lists')
    issues, invalid, threads, metas = [], [], {}, {}
    thread_observations, metadata_observations, ambiguous = {}, {}, set()
    if export.get('includeSubagents') is not True:
        issues.append('includeSubagents_not_true')
    if export.get('filters') != {}:
        issues.append('unknown_or_filtered_scope')
    cursor, totals, cursors = None, [], set()
    for i, page in enumerate(pages):
        try:
            require(type(page) is dict, 'invalid page')
            if 'error' in page:
                string(page['error'])
                issues.append('page_failure:' + str(i))
                continue
            for key in ('cursor', 'nextCursor'):
                if page[key] is not None:
                    integer(page[key])
            if page['cursor'] in cursors or (page['nextCursor'] is not None and
                    page['nextCursor'] <= (page['cursor'] or 0)):
                issues.append('broken_page_chain:' + str(i))
            cursors.add(page['cursor'])
            integer(page['total'])
            require(type(page['threads']) is list, 'invalid threads')
            if page['cursor'] != cursor or (i and cursor is None):
                issues.append('broken_page_chain:' + str(i))
            cursor = page['nextCursor']
            totals.append(page['total'])
            if page['projectId'] != project:
                issues.append('page_project_mismatch')
            for t in page['threads']:
                try:
                    tid = string(t['threadId'])
                    require(t['status'] in STATUSES, 'unknown status')
                    timestamp(t['updatedAt'])
                    require(t['projectId'] == project, 'thread project mismatch')
                    p, rel = t['parentThreadId'], t['relationshipToParent']
                    require((p is None and rel is None) or
                            (type(p) is str and bool(p) and rel in ('fork', 'subagent')),
                            'invalid parent relationship')
                    record = {k: t[k] for k in ('threadId', 'projectId', 'parentThreadId',
                              'relationshipToParent', 'status', 'updatedAt')}
                    thread_observations.setdefault(tid, []).append(record)
                    if tid in threads:
                        issues.append('duplicate_thread:' + tid)
                        ambiguous.add(tid)
                    else:
                        threads[tid] = dict(record)
                except (ValueError, KeyError, TypeError):
                    invalid.append('invalid_thread_in_page:' + str(i))
        except (ValueError, KeyError, TypeError):
            invalid.append('invalid_page:' + str(i))
    if not pages or cursor is not None or not totals or len(set(totals)) != 1 or totals[0] != len(threads):
        issues.append('incomplete_pagination_or_total')
    for m in metadata:
        try:
            tid = string(m['threadId'])
            if tid in metadata_observations:
                issues.append('duplicate_metadata:' + tid)
                ambiguous.add(tid)
            record = {'threadId': tid}
            metadata_observations.setdefault(tid, []).append(record)
            if 'error' in m:
                string(m['error'])
                record['error'] = 'metadata unavailable'
                issues.append('metadata_failure:' + tid)
                ambiguous.add(tid)
                continue
            for key in ('worktreePath', 'branch', 'updatedAt', 'parentThreadId',
                        'relationshipToParent', 'status', 'projectId', 'pendingRequestCount'):
                if key in ('projectId', 'pendingRequestCount') and key not in m:
                    continue
                try:
                    value = m[key]
                    if key == 'worktreePath':
                        require(value is None or (type(value) is str and Path(value).is_absolute()),
                                'invalid metadata path')
                    elif key in ('branch', 'parentThreadId'):
                        require(value is None or type(value) is str, 'invalid metadata string')
                    elif key == 'updatedAt':
                        timestamp(value)
                    elif key == 'pendingRequestCount':
                        integer(value)
                    elif key == 'projectId':
                        string(value)
                    elif key == 'status':
                        require(type(value) is str and value in STATUSES, 'invalid status')
                    else:
                        require(value is None or value in ('fork', 'subagent'), 'invalid relationship')
                    record[key] = value
                except (ValueError, KeyError, TypeError):
                    invalid.append('invalid_metadata_field:' + tid + ':' + key)
                    ambiguous.add(tid)
            metas.setdefault(tid, record)
            if 'projectId' in record and record['projectId'] != project:
                issues.append('metadata_project_mismatch:' + tid)
                ambiguous.add(tid)
            if tid not in threads or any(record.get(k) != threads[tid][k] for k in
                    ('parentThreadId', 'relationshipToParent', 'status', 'updatedAt')):
                issues.append('metadata_changed_or_unlisted:' + tid)
                ambiguous.add(tid)
        except (ValueError, KeyError, TypeError):
            invalid.append('invalid_metadata')
    if parent not in threads:
        issues.append('parent_missing')
    children = {parent}
    for tid, t in threads.items():
        seen, p = {tid}, t['parentThreadId']
        while p is not None:
            if p in seen:
                issues.append('graph_cycle:' + tid)
                break
            seen.add(p)
            if p not in threads:
                issues.append('missing_parent:' + tid)
                break
            if p == parent:
                children.add(tid)
            p = threads[p]['parentThreadId']
    require(type(ledger) is dict and type(ledger.get('repositories')) is list
            and bool(ledger['repositories']), 'invalid ledger')
    names = [string(r['repo']) for r in ledger['repositories']]
    require(len(set(names)) == len(names) and all(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', n)
            for n in names), 'invalid or duplicate ledger repository')
    expected = set(names)
    require(type(observed['repositories']) is list, 'invalid git repositories')
    repos, trees = set(), []
    for repo in observed['repositories']:
        try:
            name, root = string(repo['repo']), string(repo['root'])
            if name in repos:
                issues.append('duplicate_repository:' + name)
            repos.add(name)
            listing, listed = repo.get('listing'), []
            try:
                require(type(listing) is dict and set(listing) in ({'value'}, {'error'})
                        and type(next(iter(listing.values()))) is str, 'invalid listing')
                listed = porcelain(listing['value']) if 'value' in listing else []
            except (ValueError, KeyError, TypeError, StopIteration):
                invalid.append('invalid_git_listing:' + name)
                listing = {'error': 'invalid saved listing'}
            if 'error' in listing:
                issues.append('git_listing_failure:' + name)
            require(type(repo['trees']) is list, 'invalid trees')
            listed_paths = [x['worktree'] for x in listed]
            paths = [x.get('path') for x in repo['trees'] if type(x) is dict
                     and type(x.get('path')) is str]
            if len(set(paths)) != len(paths) or sorted(paths) != sorted(listed_paths):
                issues.append('git_tree_coverage:' + name)
            for tree in repo['trees']:
                try:
                    path = string(tree['path'])
                except (ValueError, KeyError, TypeError):
                    invalid.append('invalid_git_tree_path:' + name)
                    continue
                at = tree.get('at')
                try:
                    timestamp(at)
                except (ValueError, TypeError):
                    invalid.append('invalid_git_tree_timestamp:' + path)
                    at = None
                saved, obs = tree.get('observations'), {}
                if type(saved) is not dict:
                    invalid.append('invalid_git_observations:' + path)
                    saved = {}
                for field, value in saved.items():
                    valid = (field in GIT and type(value) is dict and set(value) in
                             ({'value'}, {'error'}) and type(next(iter(value.values()))) is str)
                    if not valid:
                        invalid.append('invalid_git_observation:' + path + ':' + field)
                        if field in GIT:
                            obs[field] = {'error': 'invalid saved observation'}
                    else:
                        obs[field] = dict(value)
                origin = obs.get('origin', {}).get('value')
                if origin is not None and not re.fullmatch(r'github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', origin):
                    obs['origin'] = {'error': 'unrecognized saved origin identity'}
                values = {k: v.get('value') for k, v in obs.items()}
                if any('value' not in obs.get(k, {}) for k in GIT if k != 'worktrees'):
                    issues.append('git_observation_unknown:' + path)
                if values.get('root') != path or values.get('origin') != 'github.com/' + name.lower():
                    issues.append('git_identity_mismatch:' + path)
                listed_row = next((x for x in listed if x['worktree'] == path), {})
                if listed_row.get('HEAD') != values.get('head') or listed_row.get('branch') != 'refs/heads/' + (values.get('branch') or ''):
                    issues.append('git_listing_changed:' + path)
                owners = [threads[tid] for tid in children if tid in threads and
                          any(m.get('worktreePath') == path
                              for m in metadata_observations.get(tid, []))]
                if not owners:
                    issues.append('owner_unknown:' + path)
                conditions = {k: 'unknown' for k in CONDITIONS}
                conditions['no_uncommitted_changes'] = ('observed_true' if values.get('status') == ''
                    else 'observed_false' if values.get('status') is not None else 'unknown')
                conditions['no_unpushed_commits'] = ('observed_true' if values.get('unpushed') == '0'
                    else 'observed_false' if values.get('unpushed') is not None else 'unknown')
                conditions['non_shared'] = 'observed_false' if path == root or len(owners) > 1 else 'unknown'
                owner_records = [r for t in owners for r in
                    thread_observations[t['threadId']] + metadata_observations.get(t['threadId'], [])]
                if any(r.get('status') in ('waiting', 'interrupted', 'failed', 'cancelled', 'rolled_back')
                       or r.get('pendingRequestCount', 0) > 0 for r in owner_records):
                    conditions['no_failed_interrupted_waiting_owner'] = 'observed_false'
                trees.append(dict(repo=name, path=path, role='root' if path == root else
                    'audit' if path in export.get('auditPaths', []) else 'work',
                    at=at, observations=obs, owners=[t['threadId'] for t in owners],
                    cleanup='retain', cleanup_conditions=conditions))
        except (ValueError, KeyError, TypeError, StopIteration):
            invalid.append('invalid_git_repository')
    issues.extend('missing_repository:' + r for r in sorted(expected - repos))
    issues.extend('unexpected_repository:' + r for r in sorted(repos - expected))
    for tid, t in threads.items():
        t['list_observations'] = thread_observations[tid]
        t['metadata_observations'] = metadata_observations.get(tid, [])
    for tid in sorted(children & threads.keys()):
        m = metas.get(tid, {})
        t = threads[tid]
        t['metadata'] = {k: m.get(k) for k in ('worktreePath', 'branch', 'updatedAt', 'pendingRequestCount')}
        path = m.get('worktreePath')
        matches = [tree for tree in trees if tree['path'] == path]
        t['git_comparison'] = 'unknown'
        if path is None:
            issues.append('worktree_metadata_unknown:' + tid)
        elif len(matches) != 1:
            issues.append('worktree_not_observed:' + tid)
        else:
            obs = matches[0]['observations']
            t['git_comparison'] = ('incomplete' if any('value' not in obs.get(k, {})
                for k in GIT if k != 'worktrees') else 'match' if m.get('branch') is not None and
                obs.get('branch', {}).get('value') == m['branch'] and
                obs.get('root', {}).get('value') == path and
                obs.get('origin', {}).get('value') == 'github.com/' + matches[0]['repo'].lower()
                else 'mismatch')
            if t['git_comparison'] != 'match':
                issues.append('worktree_mismatch:' + tid)
        if tid in ambiguous:
            t['git_comparison'] = 'ambiguous'
        t['stale'] = 'not_assessed_single_observation'
    result = dict(schema_version=1, status='invalid_input' if invalid else 'review_required' if issues else 'consistent',
                  sources=[{'source': x['source'], 'at': x['at']} for x in (export, observed)],
                  projectId=project, parentThreadId=parent, issues=issues, errors=invalid,
                  inventory_complete=not invalid and not any(i.split(':')[0] in {
                      'includeSubagents_not_true', 'unknown_or_filtered_scope', 'page_failure',
                      'broken_page_chain', 'page_project_mismatch', 'duplicate_thread',
                      'incomplete_pagination_or_total', 'parent_missing', 'graph_cycle', 'missing_parent'
                      } for i in issues),
                  threads=list(threads.values()), trees=trees, cleanup='retain',
                  limitation='Manual point-in-time comparison; no authenticity, acceptance, ownership, approval, deletion or future guarantee. Read-only/API work may leave no Git artifacts. Single observation cannot prove stagnation.')
    return result, 2 if invalid else 1 if issues else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    observe = sub.add_parser('observe-git')
    observe.add_argument('roots', type=Path)
    check = sub.add_parser('check')
    check.add_argument('export', type=Path)
    check.add_argument('git', type=Path)
    check.add_argument('--ledger', type=Path, default=Path(__file__).with_name('repository_coverage_ledger.json'))
    args = parser.parse_args()
    try:
        if args.command == 'observe-git':
            result, code = capture(load(args.roots)), 0
            if any('error' in r['listing'] or any('error' in value for tree in r['trees']
                   for value in tree['observations'].values()) for r in result['repositories']):
                code = 1
        else:
            result, code = audit(load(args.export), load(args.git), load(args.ledger))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError, RuntimeError):
        result, code = dict(schema_version=1, status='invalid_input', errors=['Invalid input; see thread_worktree_audit.md']), 2
    if code:
        print('Audit requires review; inspect JSON issues/errors.', file=sys.stderr)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
