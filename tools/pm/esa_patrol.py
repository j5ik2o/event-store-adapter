#!/usr/bin/env python3
"""The ESA patrol, run on Spark by the patrol automation instead of by the coordinator.

It runs the cleanup (orca_cleanup.py), looks at the open PRs and the issues opened since the
last patrol in the ESA repositories, and writes to the coordinator's Run inbox only when there
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
        }
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(new_state, ensure_ascii=False))
    print(json.dumps({'report': outgoing, 'sent': sent is not None, 'summary': cleanup['summary']}, ensure_ascii=False))
    return 0 if args.no_send or not outgoing or sent is not None else 1


if __name__ == '__main__':
    sys.exit(main())
