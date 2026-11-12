#!/usr/bin/env python3
"""Inventory the ESA line's Orca worktrees and worker terminals, and clean up only what is provably safe.

Without --apply nothing is changed. A worktree is removed only when all three facts were observed:
its branch has a merged PR, it is clean (no changes, no untracked files), and no commit is unpushed.
A worker terminal is released only when its task is settled and nothing runs or waits for input in it.
Anything that cannot be observed is kept and listed with the reason.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

REPOS = (
    'event-store-adapter',
    'event-store-adapter-java',
    'event-store-adapter-rs',
    'event-store-adapter-go',
    'event-store-adapter-js',
    'event-store-adapter-scala',
    'event-store-adapter-kotlin',
    'cqrs-es-example',
    'cqrs-es-example-java',
    'cqrs-es-example-rs',
    'cqrs-es-example-go',
    'cqrs-es-example-js',
    'cqrs-es-example-scala',
    'cqrs-es-example-kotlin',
)
PROJECTS = {f'github:j5ik2o/{name}': f'j5ik2o/{name}' for name in REPOS}
PARALLEL_MARKERS = ('parallel', '並列')
SETTLED = {'succeeded', 'failed', 'cancelled'}
LOG = Path.home() / '.local' / 'state' / 'esa-orca-cleanup' / 'log.jsonl'
TIMEOUT = 60


def run(args, cwd=None):
    """Return stdout, or None when the command failed or timed out."""
    try:
        done = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def run_json(args):
    out = run(args)
    if out is None:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


# ---- decisions (pure) -------------------------------------------------------------------------


def decide_worktree(facts):
    """facts: dict with keys main, seat, parallel, attached, merged_pr, clean, unpushed_free.

    Each fact is True, False or None (not observed). Returns (action, reason).
    """
    if facts['main']:
        return 'keep', 'ghq のプライマリ（main worktree）'
    if facts['seat']:
        return 'keep', 'coordinator の座'
    if facts['attached'] is not False:
        return 'keep', '生きているワーカーかターミナルがある' if facts['attached'] else '確認不能: 付いているワーカーかターミナルを確かめられない'
    missing = [name for name in ('merged_pr', 'clean', 'unpushed_free') if facts[name] is None]
    if missing:
        return 'keep', '確認不能: ' + ', '.join(missing)
    if not facts['merged_pr']:
        return 'keep', '対応する PR がマージされていない'
    if not facts['clean']:
        return 'keep', '未コミットの変更か未追跡のファイルがある'
    if not facts['unpushed_free']:
        return 'keep', '未 push のコミットがある'
    if facts['parallel']:
        return 'list', '並列 worktree: 条件は満たすが、記録した掃除担当・時期に従う'
    return 'remove', '3 条件を満たす（PR マージ済み・クリーン・未 push なし）'


def decide_worker(worker, own_terminal, released_terminals=frozenset()):
    """worker: worker-show result merged with worker-list. Returns (action, reason)."""
    if worker.get('terminal') == own_terminal:
        return 'keep', 'coordinator 自身のターミナル'
    if not worker.get('terminal'):
        return 'skip', 'ターミナルを持たない'
    if worker.get('terminalState') is None and worker['terminal'] in released_terminals:
        return 'skip', '後続のディスパッチに引き継いだターミナルは解放済み'
    if worker.get('terminalState') in ('released', None) and worker.get('liveness') in ('exited', None):
        return 'skip', 'ターミナルはもうない'
    if worker.get('state') not in SETTLED or worker.get('stage') not in ('settled', None):
        return 'keep', f"タスクが完了していない（state={worker.get('state')}）"
    if worker.get('terminalState') != 'retained':
        return 'keep', f"terminalState={worker.get('terminalState')}"
    liveness = worker.get('liveness')
    if liveness == 'exited':
        return 'release', 'タスク完了、プロセスは終了済み'
    if liveness != 'live':
        return 'keep', f'確認不能: liveness={liveness}'
    if worker.get('activity') != 'idle':
        return 'keep', f"実行中（activity={worker.get('activity')}）"
    waiting = worker.get('waitingOnHuman')
    if waiting is True or waiting == 'yes':
        return 'keep', '入力待ちで停滞（要判断）'
    if waiting not in (False, 'no'):
        return 'keep', f'確認不能: 入力待ちかどうか分からない（waitingOnHuman={waiting}）'
    return 'release', 'タスク完了、アイドルで入力待ちなし'


# ---- observation ------------------------------------------------------------------------------


def branch_name(ref):
    return ref[len('refs/heads/'):] if ref and ref.startswith('refs/heads/') else None


def merged_prs(repo, branch):
    return run_json(['gh', 'pr', 'list', '-R', repo, '--head', branch, '--state', 'merged',
                     '--json', 'number,headRefOid', '--limit', '100'])


def contains(path, pr, head):
    """True when the merged PR's head is HEAD, or HEAD is its ancestor (the branch was
    updated on GitHub after this tree last pushed). The PR head is fetched from its pull ref
    and must be the commit GitHub reports."""
    if pr['headRefOid'] == head:
        return True
    if run(['git', '-C', path, 'fetch', '-q', 'origin', f"pull/{pr['number']}/head"]) is None:
        return False
    fetched = run(['git', '-C', path, 'rev-parse', 'FETCH_HEAD'])
    if not fetched or fetched.strip() != pr['headRefOid']:
        return False
    return run(['git', '-C', path, 'merge-base', '--is-ancestor', head, pr['headRefOid']]) is not None


def observe_worktree(wt, seat, attached):
    path = wt['path']
    repo = PROJECTS[wt['projectId']]
    branch = branch_name(wt.get('branch'))
    facts = {
        'main': bool(wt.get('isMainWorktree')),
        'seat': wt['id'] == seat,
        'parallel': any(m in (wt.get('comment') or '').lower() for m in PARALLEL_MARKERS),
        'attached': attached,
        'merged_pr': None,
        'clean': None,
        'unpushed_free': None,
    }
    detail = {'repo': repo, 'branch': branch, 'path': path}
    if facts['main'] or facts['seat']:
        return facts, detail
    head = run(['git', '-C', path, 'rev-parse', 'HEAD'])
    head = head.strip() if head else None
    detail['head'] = head
    status = run(['git', '-C', path, 'status', '--porcelain', '--untracked-files=all'])
    if status is not None:
        facts['clean'] = status.strip() == ''
    prs = merged_prs(repo, branch) if branch else None
    # Only a merged PR that contains this HEAD proves this tree's work was merged; an older
    # PR of the same branch name does not.
    merged_here = None if prs is None or head is None else any(contains(path, p, head) for p in prs)
    facts['merged_pr'] = merged_here
    if prs is not None:
        detail['prs'] = [p['number'] for p in prs]
    unpushed = run(['git', '-C', path, 'rev-list', 'HEAD', '--not', '--remotes'])
    if unpushed is not None:
        # A deleted remote branch drops its refs, but the merged PR whose head is HEAD keeps
        # every commit on GitHub.
        facts['unpushed_free'] = unpushed.strip() == '' or bool(merged_here)
    return facts, detail


def all_workers(run_id):
    """Every worker of one Run, across pages. None when any page cannot be read."""
    workers, cursor = [], None
    while True:
        args = ['orca', 'orchestration', 'worker-list', '--run', run_id, '--limit', '100', '--json']
        page = run_json(args + (['--cursor', cursor] if cursor else []))
        if page is None:
            return None
        workers += page['result']['workers']
        cursor = page['result'].get('nextCursor')
        if not cursor:
            return workers


def other_live_workspaces(own_runs):
    """Workspaces that a worker of any other Run still holds. None when that cannot be observed."""
    held, cursor = set(), None
    while True:
        args = ['orca', 'orchestration', 'run-list', '--json'] + (['--cursor', cursor] if cursor else [])
        page = run_json(args)
        if page is None:
            return None
        for item in page['result']['runs']:
            if item['id'] in own_runs:
                continue
            workers = all_workers(item['id'])
            if workers is None:
                return None
            for worker in workers:
                if worker.get('liveness') != 'exited' or worker.get('terminalState') == 'retained':
                    held.add(worker.get('workspace'))
        cursor = page['result'].get('nextCursor')
        if not cursor:
            return held


def automation_ptys(automations):
    """PTYs of the patrol automations' sessions. None when they cannot be observed."""
    ptys = set()
    for automation in automations:
        runs = run_json(['orca', 'automations', 'runs', '--id', automation, '--limit', '20', '--json'])
        if runs is None:
            return None
        for item in runs['result'].get('runs', []):
            if item.get('terminalPtyId'):
                ptys.add(item['terminalPtyId'])
    return ptys


def complete_list(args, key):
    """Items of an Orca list, or None when it failed or was truncated."""
    data = run_json(args)
    if data is None or data['result'].get('truncated'):
        return None
    return data['result'][key]


def observation(worker):
    """What the owner asked to measure: waitingOnHuman and liveness of settled workers, with
    the completion time, so that --exit-report can bound the time until the process exits."""
    observed = {key: worker.get(key) for key in ('state', 'liveness', 'activity', 'waitingOnHuman', 'agent')}
    if worker.get('state') in SETTLED:
        full = run_json(['orca', 'orchestration', 'worker-show', '--dispatch', worker['dispatchId'], '--json', '--full'])
        observed['completedAt'] = ((full or {}).get('result', {}).get('dispatch') or {}).get('completedAt')
    return observed


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    # Orca prints some timestamps without a zone; they are UTC.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def exit_report(lines):
    """Per settled worker: the waitingOnHuman values seen while it was live, and bounds on the
    seconds from completion to exit (last live observation, first exited observation)."""
    workers = {}
    for line in lines:
        record = json.loads(line)
        at = parse_time(record.get('at'))
        for entry in record.get('workers', []):
            observed = entry.get('observed')
            if not observed or observed.get('state') not in SETTLED:
                continue
            row = workers.setdefault(entry['dispatch'], {
                'dispatch': entry['dispatch'], 'agent': observed.get('agent'),
                'completedAt': observed.get('completedAt'), 'waitingOnHuman_while_live': {},
                'last_live_at': None, 'first_exited_at': None})
            if observed.get('liveness') == 'live':
                value = str(observed.get('waitingOnHuman'))
                row['waitingOnHuman_while_live'][value] = row['waitingOnHuman_while_live'].get(value, 0) + 1
                if row['first_exited_at'] is None:
                    row['last_live_at'] = record['at']
            elif observed.get('liveness') == 'exited' and row['first_exited_at'] is None:
                row['first_exited_at'] = record['at']
    rows = []
    for row in workers.values():
        done = parse_time(row['completedAt'])
        live, exited = parse_time(row['last_live_at']), parse_time(row['first_exited_at'])
        row['exit_after_seconds_min'] = round((live - done).total_seconds()) if done and live else 0 if done and exited else None
        row['exit_after_seconds_max'] = round((exited - done).total_seconds()) if done and exited else None
        rows.append(row)
    values = {}
    for row in rows:
        for value, count in row['waitingOnHuman_while_live'].items():
            values[value] = values.get(value, 0) + count
    return {'workers': rows, 'waitingOnHuman_while_live': values,
            'exited': sum(1 for row in rows if row['first_exited_at']),
            'still_live': sum(1 for row in rows if not row['first_exited_at'])}


def needs_judgement(action, reason):
    return action == 'list' or '停滞' in reason or reason.startswith('確認不能')


def inventory(runs, apply, automations=()):
    own_terminal = os.environ.get('ORCA_TERMINAL_HANDLE')
    seat = os.environ.get('ORCA_WORKTREE_ID')
    result = {'at': datetime.now(timezone.utc).isoformat(), 'apply': apply,
              'workers': [], 'worktrees': [], 'terminals': [], 'errors': []}
    if not own_terminal:
        result['errors'].append('ORCA_TERMINAL_HANDLE がない: 自分のターミナルを守れないので何も解放しない')

    worktrees = complete_list(['orca', 'worktree', 'list', '--json', '--limit', '1000'], 'worktrees')
    if worktrees is None:
        result['errors'].append('worktree list に失敗したか打ち切られた')
        return result
    esa_ids = {wt['id'] for wt in worktrees if wt.get('projectId') in PROJECTS}

    attachment_known = True
    live_workspaces = set()
    for run_id in runs:
        listed = all_workers(run_id)
        if listed is None:
            result['errors'].append(f'worker-list に失敗: {run_id}')
            attachment_known = False
            continue
        released = {w.get('terminal') for w in listed if w.get('terminalState') == 'released'}
        for item in listed:
            shown = run_json(['orca', 'orchestration', 'worker-show', '--dispatch', item['dispatchId'], '--json'])
            worker = dict(item, **(shown['result'] if shown else {}))
            action, reason = decide_worker(worker, own_terminal, released)
            if action == 'release' and not own_terminal:
                action, reason = 'keep', '確認不能: 自分のターミナルを確かめられない'
            if action == 'skip':
                continue
            entry = {'dispatch': item['dispatchId'], 'task': item.get('taskId'),
                     'workspace': item.get('workspace'), 'action': action, 'reason': reason,
                     'observed': observation(worker)}
            if action == 'release' and apply:
                done = run_json(['orca', 'orchestration', 'worker-release', '--dispatch', item['dispatchId'], '--json'])
                entry['done'] = bool(done and done.get('ok'))
                if not entry['done']:
                    entry['action'], entry['reason'] = 'keep', '確認不能: release に失敗'
            if entry['action'] != 'release' or not apply:
                live_workspaces.add(item.get('workspace'))
            entry['needs_judgement'] = needs_judgement(entry['action'], entry['reason'])
            result['workers'].append(entry)

    others = other_live_workspaces(set(runs))
    if others is None:
        result['errors'].append('ほかの Run のワーカーを確かめられない')
        attachment_known = False
    else:
        live_workspaces |= others

    terminals = complete_list(['orca', 'terminal', 'list', '--json', '--limit', '1000'], 'terminals')
    terminal_worktrees = set()
    if terminals is None:
        result['errors'].append('terminal list に失敗したか打ち切られた')
        attachment_known = False
    else:
        patrol = automation_ptys(automations) or set()
        for term in terminals:
            terminal_worktrees.add(term.get('worktreeId'))
            if term.get('worktreeId') not in esa_ids:
                continue
            if own_terminal and term['handle'] == own_terminal:
                reason = 'coordinator 自身のターミナル'
            elif term.get('ptyId') in patrol:
                reason = '見回り automation のセッション（reuse-session で常設）'
            else:
                reason = '確認不能: 対応するタスクが分からない（Run のワーカーではない）'
            result['terminals'].append({'handle': term['handle'], 'title': term.get('title'),
                                        'worktree': term.get('worktreeId'), 'action': 'keep', 'reason': reason,
                                        'needs_judgement': needs_judgement('keep', reason)})

    for wt in worktrees:
        if wt['id'] not in esa_ids or wt.get('isMainWorktree'):
            continue
        attached = (wt['id'] in live_workspaces or wt['id'] in terminal_worktrees) if attachment_known else None
        facts, detail = observe_worktree(wt, seat, attached)
        action, reason = decide_worktree(facts)
        entry = dict(detail, id=wt['id'], action=action, reason=reason, facts=facts)
        if action == 'remove' and apply:
            done = run_json(['orca', 'worktree', 'rm', '--worktree', f"id:{wt['id']}", '--delete-branch', '--json'])
            entry['done'] = bool(done and done.get('ok'))
            if not entry['done']:
                entry['action'], entry['reason'] = 'keep', '確認不能: worktree rm に失敗'
        entry['needs_judgement'] = needs_judgement(entry['action'], entry['reason'])
        result['worktrees'].append(entry)
    return result


def summary(result):
    entries = result['worktrees'] + result['workers'] + result['terminals']
    return {'removed_worktrees': sum(1 for w in result['worktrees'] if w['action'] == 'remove' and w.get('done')),
            'released_workers': sum(1 for w in result['workers'] if w['action'] == 'release' and w.get('done')),
            'needs_judgement': sum(1 for w in entries if w.get('needs_judgement')),
            'errors': len(result['errors'])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--run', action='append', default=[], help='coordinator の Run ID（複数可）')
    parser.add_argument('--automation', action='append', default=[],
                        help='見回り automation の ID（そのセッションのターミナルを常設として扱う）')
    parser.add_argument('--apply', action='store_true', help='条件を満たすものを実際に消す')
    parser.add_argument('--log', type=Path, default=LOG)
    parser.add_argument('--exit-report', action='store_true',
                        help='棚卸しをせず、log から完了後のワーカーの waitingOnHuman と exited までの時間を集計する')
    args = parser.parse_args(argv)
    if args.exit_report:
        with args.log.open(encoding='utf-8') as log:
            json.dump(exit_report(log), sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write('\n')
        return 0
    if not args.run:
        parser.error('--run is required unless --exit-report is given')
    result = inventory(args.run, args.apply, args.automation)
    result['summary'] = summary(result)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open('a', encoding='utf-8') as log:
        log.write(json.dumps(result, ensure_ascii=False) + '\n')
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write('\n')
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
