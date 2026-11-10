#!/usr/bin/env python3
"""Check recorded PM GraphQL inventory coverage, offline and without executing input."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re


class InvalidInput(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidInput(message)


def load(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result
    def invalid_constant(value):
        raise InvalidInput(f"invalid JSON constant: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=invalid_constant)


def timestamp(value):
    require(isinstance(value, str), "at must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidInput("invalid at timestamp") from exc
    require(parsed.utcoffset() is not None, "at must include a timezone")


def ledger_names(ledger):
    require(isinstance(ledger, dict) and ledger.get("schema_version") == 1,
            "ledger schema_version must be 1")
    sources = ledger.get("sources")
    rows = ledger.get("repositories")
    require(isinstance(sources, dict) and sources, "ledger requires sources")
    require(isinstance(rows, list) and rows, "ledger repositories must be nonempty")
    names = []
    for row in rows:
        require(isinstance(row, dict), "invalid ledger row")
        repo = row.get("repo")
        require(isinstance(repo, str) and re.fullmatch(r"j5ik2o/[a-z0-9][a-z0-9-]*", repo),
                "ledger requires full j5ik2o/repo names")
        refs = row.get("sources")
        require(isinstance(refs, list) and refs, f"{repo}: missing sources")
        for ref in refs:
            require(isinstance(ref, str) and ref in sources, f"{repo}: unknown source")
            source = sources[ref]
            require(isinstance(source, dict) and all(isinstance(source.get(k), str)
                    and source[k].strip() for k in ("url", "scope")), "invalid source")
        names.append(repo)
    require(len(names) == len(set(names)), "duplicate ledger repositories")
    return sorted(names)


def pagination(value, path="repository"):
    pending = []
    if isinstance(value, dict):
        if "pageInfo" in value:
            info = value["pageInfo"]
            require(isinstance(info, dict) and info, f"{path}: invalid pageInfo")
            require(set(info) <= {"hasNextPage", "hasPreviousPage", "startCursor", "endCursor"},
                    f"{path}: unknown pageInfo fields")
            flags = [k for k in ("hasNextPage", "hasPreviousPage") if k in info]
            require(flags and all(type(info[k]) is bool for k in flags),
                    f"{path}: pagination flag must be boolean")
            if any(info[k] for k in flags):
                pending.append(path)
        for key, child in value.items():
            pending.extend(pagination(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            pending.extend(pagination(child, f"{path}[{index}]"))
    return pending


def inspect_record(row, raw):
    require(isinstance(raw, dict), "response must be an object")
    if raw.get("errors"):
        return "failed", "GraphQL errors present"
    require("errors" not in raw or raw["errors"] == [], "invalid GraphQL errors")
    data = raw.get("data")
    require(isinstance(data, dict) and isinstance(data.get("repository"), dict),
            "missing repository response")
    repo = data["repository"]
    require(repo.get("name") == row["repo"], "response repository name mismatch")
    for key in ("prs", "issues"):
        require(type(row.get(key)) is int and row[key] >= 0, f"invalid {key} count")
    require(isinstance(row.get("milestones"), list), "missing milestones summary")
    require(isinstance(row.get("pagination"), list) and all(isinstance(x, str)
            for x in row["pagination"]), "missing pagination summary")
    for key in ("pullRequests", "issues", "milestones"):
        connection = repo.get(key)
        require(isinstance(connection, dict) and isinstance(connection.get("nodes"), list)
                and all(isinstance(x, dict) for x in connection["nodes"]),
                f"invalid {key} connection")
        require(isinstance(connection.get("pageInfo"), dict)
                and type(connection["pageInfo"].get("hasNextPage")) is bool,
                f"missing {key} pagination metadata")
    require(len(repo["pullRequests"]["nodes"]) == row["prs"], "PR count mismatch")
    require(len(repo["issues"]["nodes"]) == row["issues"], "issue count mismatch")
    require(repo["milestones"]["nodes"] == row["milestones"], "milestone summary mismatch")
    pending = pagination(repo)
    if row["pagination"] or pending:
        return "incomplete", "unconsumed pagination: " + ", ".join(row["pagination"] + pending)
    return "successful", "recorded query evidence consistent"


def check(ledger, inventory, records_dir):
    expected = ledger_names(ledger)
    require(isinstance(inventory, dict), "inventory must be an object")
    timestamp(inventory.get("at"))
    rows = inventory.get("results")
    require(isinstance(rows, list) and rows, "inventory results must be nonempty")
    names = []
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get("repo"), str)
                and re.fullmatch(r"[a-z0-9][a-z0-9-]*", row["repo"]),
                "inventory repo must be a short lowercase repository name")
        names.append("j5ik2o/" + row["repo"])
    counts = Counter(names)
    result = dict(schema_version=1, status="consistent", at=inventory["at"],
                  scope="recorded PM query only; authenticity and freshness not verified",
                  expected=expected, observed=sorted(counts), successful=[],
                  missing=sorted(set(expected) - counts.keys()),
                  unexpected=sorted(counts.keys() - set(expected)),
                  duplicates=sorted(k for k, v in counts.items() if v > 1),
                  failed=[], incomplete=[], invalid_records=[], errors=[])
    for index, (name, row) in enumerate(zip(names, rows)):
        try:
            if "error" in row:
                require(bool(row["error"]), "empty acquisition error")
                category, detail = "failed", "inventory declares acquisition error"
            else:
                category, detail = inspect_record(row, load(records_dir / (row["repo"] + ".json")))
        except (InvalidInput, OSError, ValueError, UnicodeError) as exc:
            category, detail = "invalid_records", str(exc)
        if category == "successful":
            result[category].append(name)
        else:
            result[category].append(dict(repo=name, index=index, reason=detail))
    result["successful"] = sorted(set(result["successful"]) - set(result["duplicates"]))
    if result["invalid_records"]:
        result["status"] = "invalid_input"
        return result, 2
    if any(result[k] for k in ("missing", "unexpected", "duplicates", "failed", "incomplete")):
        result["status"] = "coverage_gap"
        return result, 1
    return result, 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=Path(__file__).with_name("repository_coverage_ledger.json"))
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--records-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result, code = check(load(args.ledger), load(args.inventory), args.records_dir)
    except (InvalidInput, OSError, ValueError, UnicodeError) as exc:
        result, code = dict(schema_version=1, status="invalid_input", errors=[str(exc)]), 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
