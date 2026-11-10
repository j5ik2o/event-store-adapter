#!/usr/bin/env python3
"""Check a PM delegation export before recording a checkpoint as complete."""
import argparse
import csv
import re
import sys
from pathlib import Path

COMMENT = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/issues/\d+#issuecomment-\d+")


def read_rows(path):
    with Path(path).open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source, delimiter="\t"))


def audit(ledger, checkpoints):
    problems = []
    seen = set()
    recorded = 0
    for row in ledger:
        if row["launch"] != "started":
            continue
        task = row["task_id"]
        if not task or task in seen:
            problems.append(f"{row['delegation']}: missing or duplicate task_id; reconcile the launch export")
        seen.add(task)
        if row["issue_start_record"] != "present" or not COMMENT.search(row["issue_start_comments"]):
            problems.append(f"{row['delegation']}: missing issue start comment; recover the original evidence without inventing a past record")
        else:
            recorded += 1
    indexed = {}
    for row in checkpoints:
        key = (row["counter"], int(row["boundary"]))
        if key in indexed:
            problems.append(f"{key}: duplicate checkpoint row; reconcile the checkpoint export")
        indexed[key] = row
    for boundary in range(20, recorded + 1, 20):
        row = indexed.get(("issue-recorded-started", boundary))
        for skill in ("correct", "reflect"):
            evidence = row.get(f"{skill}_issue_evidence", "") if row else ""
            if not COMMENT.search(evidence):
                problems.append(f"recorded delegation {boundary}: {skill} completion evidence missing; finish it and record its issue comment URL")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("checkpoints", type=Path)
    args = parser.parse_args()
    try:
        problems = audit(read_rows(args.ledger), read_rows(args.checkpoints))
    except (OSError, KeyError, ValueError, csv.Error) as error:
        print(f"Invalid delegation export: {error}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"BLOCKED: {len(problems)} unresolved ledger problems", file=sys.stderr)
        return 1
    print("Delegation records and recorded-delegation checkpoints are complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
