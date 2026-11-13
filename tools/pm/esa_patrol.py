#!/usr/bin/env python3
"""The ESA patrol, run on Spark by the patrol automation instead of by the coordinator.

It runs the cleanup (orca_cleanup.py), looks at the open PRs and the issues opened since the
last patrol in the ESA repositories, takes an inventory of the open PRs (left mergeable for a
day or more, too many drafts and WIP PRs in one repository), and writes to the coordinator's Run inbox only when there
is something to report. A quiet patrol sends nothing, so the coordinator is not woken.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import orca_cleanup
from orca_cleanup import PROJECTS, run, run_json

STATE = Path.home() / '.local' / 'state' / 'esa-orca-cleanup' / 'patrol.json'
LIMIT = 1000
STALE_HOURS = 24
WIP_THRESHOLD = 5
PR_QUERY = """query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) {
  pullRequests(states: OPEN, first: 100) { totalCount nodes {
    number title isDraft updatedAt
    reviewThreads(first: 100) { totalCount nodes { isResolved } }
    commits(last: 1) { nodes { commit { statusCheckRollup { state contexts(first: 100) { totalCount nodes {
      ... on CheckRun { completedAt } ... on StatusContext { createdAt } } } } } } } } } } }"""


def complete(items):
    """gh returns at most --limit items; a full page may be cut off, so it counts as unread."""
    return None if items is None or len(items) >= LIMIT else items


def open_prs():
    """{'repo#number': title} for every open PR, or None when a repository cannot be read."""
    found = {}
    for repo in PROJECTS.values():
        prs = complete(run_json(['gh', 'pr', 'list', '-R', repo, '--state', 'open', '--json', 'number,title',
                                 '--limit', str(LIMIT)]))
        if prs is None:
            return None
        for pr in prs:
            found[f"{repo}#{pr['number']}"] = pr['title']
    return found


def new_issues(since):
    """['repo#number title'] for issues opened at or after since, or None on failure."""
    found = []
    for repo in PROJECTS.values():
        issues = complete(run_json(['gh', 'issue', 'list', '-R', repo, '--state', 'all', '--search',
                                    f'created:>={since}', '--json', 'number,title', '--limit', str(LIMIT)]))
        if issues is None:
            return None
        found += [f"{repo}#{issue['number']} {issue['title']}" for issue in issues]
    return found


def rollup_of(pr):
    return (((pr['commits']['nodes'] or [{}])[0].get('commit') or {}).get('statusCheckRollup') or {})


def complete_pr(pr):
    """Whether every thread and every check of the PR was read (the query reads up to 100)."""
    threads = pr['reviewThreads']
    contexts = rollup_of(pr).get('contexts') or {}
    return (threads['totalCount'] <= len(threads['nodes'])
            and contexts.get('totalCount', 0) <= len(contexts.get('nodes') or []))


def ready_since(pr):
    """When an open PR became mergeable (not a draft, every check passed, no unresolved
    thread), taken as its last update or last check result; None when it is not mergeable."""
    threads = pr['reviewThreads']
    rollup = rollup_of(pr)
    if pr['isDraft'] or rollup.get('state') != 'SUCCESS':
        return None
    if any(not t['isResolved'] for t in threads['nodes']):
        return None
    nodes = (rollup.get('contexts') or {}).get('nodes') or []
    times = [pr['updatedAt']] + [n.get('completedAt') or n.get('createdAt') for n in nodes]
    return max(t for t in times if t)


def pr_health():
    """{'repo': [{'number', 'title', 'wip', 'ready_since'}]} for every open PR, or None when a
    repository cannot be read completely."""
    found = {}
    for repo in PROJECTS.values():
        owner, name = repo.split('/')
        data = run_json(['gh', 'api', 'graphql', '-f', f'query={PR_QUERY}', '-F', f'owner={owner}', '-F', f'name={name}'])
        prs = ((((data or {}).get('data') or {}).get('repository') or {}).get('pullRequests'))
        # An incomplete read is unread, not "not mergeable": the stored state must not change.
        if prs is None or prs['totalCount'] > len(prs['nodes']) or not all(complete_pr(pr) for pr in prs['nodes']):
            return None
        found[repo] = [{'number': pr['number'], 'title': pr['title'],
                        'wip': pr['isDraft'] or 'wip' in pr['title'].lower(), 'ready_since': ready_since(pr)}
                       for pr in prs['nodes']]
    return found


def inventory_lines(health, reported, now):
    """Lines for PRs left mergeable for STALE_HOURS or more and repositories with WIP_THRESHOLD
    or more drafts and WIP PRs, each reported once per state; returns (lines, reported)."""
    lines, keep = [], {}
    for repo, prs in sorted(health.items()):
        for pr in prs:
            since = pr['ready_since']
            if not since:
                continue
            hours = (now - datetime.fromisoformat(since.replace('Z', '+00:00'))).total_seconds() / 3600
            if hours < STALE_HOURS:
                continue
            key = f"{repo}#{pr['number']}"
            keep[key] = since
            if reported.get(key) != since:
                lines.append(f"放置: {key} {pr['title']}（マージ可能になってから {int(hours)} 時間）")
        wip = sum(pr['wip'] for pr in prs)
        if wip >= WIP_THRESHOLD:
            key = f'{repo}:wip'
            keep[key] = wip
            if reported.get(key) != wip:
                lines.append(f'WIP: {repo} のドラフト・WIP の PR が {wip} 件')
    return lines, keep


def report_lines(cleanup, prs, previous_prs, issues):
    lines = []
    summary = cleanup['summary']
    if summary['removed_worktrees'] or summary['released_workers'] or summary['needs_judgement']:
        lines.append(f"掃除: worktree 削除 {summary['removed_worktrees']}、ワーカー解放 {summary['released_workers']}、"
                     f"要判断 {summary['needs_judgement']}")
        for entry in cleanup['worktrees'] + cleanup['workers'] + cleanup['terminals']:
            if entry.get('done') or entry.get('needs_judgement'):
                name = entry.get('path') or entry.get('dispatch') or entry.get('handle')
                lines.append(f"  - {name}: {entry['reason']}")
    for error in cleanup['errors']:
        lines.append(f'掃除のエラー: {error}')
    if prs is None:
        lines.append('PR の一覧を読めなかった')
    elif previous_prs is not None:
        for key in sorted(set(prs) - set(previous_prs)):
            lines.append(f'新しい PR: {key} {prs[key]}')
        for key in sorted(set(previous_prs) - set(prs)):
            lines.append(f'閉じた PR: {key} {previous_prs[key]}')
    if issues is None:
        lines.append('issue の一覧を読めなかった')
    else:
        lines += [f'新しい issue: {issue}' for issue in issues]
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--run', required=True, help='coordinator の Run ID（報告の送り先）')
    parser.add_argument('--automation', action='append', default=[])
    parser.add_argument('--coordinator-terminal', action='append', default=[])
    parser.add_argument('--apply', action='store_true', help='掃除で条件を満たすものを実際に消す')
    parser.add_argument('--no-send', action='store_true', help='受信箱へ送らず、状態も更新しない（確認用）')
    parser.add_argument('--state', type=Path, default=STATE)
    parser.add_argument('--log', type=Path, default=orca_cleanup.LOG)
    args = parser.parse_args(argv)

    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    state = json.loads(args.state.read_text()) if args.state.exists() else {}
    cleanup = orca_cleanup.inventory([args.run], args.apply, args.automation, args.coordinator_terminal)
    cleanup['summary'] = orca_cleanup.summary(cleanup)
    prs = open_prs()
    issues = new_issues(state['last_at']) if state.get('last_at') else []
    lines = report_lines(cleanup, prs, state.get('prs'), issues)
    health = pr_health()
    reported = state.get('inventory', {})
    if health is None:
        lines.append('PR の棚卸しを読めなかった')
    else:
        inventory, reported = inventory_lines(health, reported, datetime.now(timezone.utc))
        lines += inventory

    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open('a', encoding='utf-8') as log:
        log.write(json.dumps(dict(cleanup, patrol={'prs': prs, 'issues': issues, 'report': lines}),
                             ensure_ascii=False) + '\n')
    # A report that could not be sent is kept and sent again with the next one: the cleanup it
    # describes cannot be observed a second time.
    outgoing = state.get('unsent', []) + lines
    sent = None
    if outgoing and not args.no_send:
        body = '【ESA】見回り（Spark）\n' + '\n'.join(outgoing)
        sent = run(['orca', 'orchestration', 'send', '--to', f'run:{args.run}', '--type', 'status',
                    '--subject', '【ESA】見回りの報告', '--body', body, '--json'])
    if not args.no_send:
        new_state = {
            # The search start advances only when the issues were read, so none are skipped.
            'last_at': started if issues is not None else state.get('last_at'),
            # Keep the previous PR set when this one could not be read, so a change is not lost.
            'prs': prs if prs is not None else state.get('prs'),
            'unsent': [] if sent is not None else outgoing,
            # A stale PR or a WIP count is reported once until its state changes.
            'inventory': reported,
        }
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(new_state, ensure_ascii=False))
    print(json.dumps({'report': outgoing, 'sent': sent is not None, 'summary': cleanup['summary']}, ensure_ascii=False))
    return 0 if args.no_send or not outgoing or sent is not None else 1


if __name__ == '__main__':
    sys.exit(main())
