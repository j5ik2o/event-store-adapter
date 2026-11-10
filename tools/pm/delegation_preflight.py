#!/usr/bin/env python3
"""Manually compare delegation scope and checkout membership. Python >=3.9."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit


FIELDS = {
    "root": ["rev-parse", "--show-toplevel"],
    "origin": ["config", "--local", "--get-all", "remote.origin.url"],
    "head": ["rev-parse", "--verify", "HEAD"],
    "branch": ["symbolic-ref", "--quiet", "--short", "HEAD"],
    "status": ["status", "--porcelain=v1", "--untracked-files=all"],
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def record(value, keys, label):
    require(type(value) is dict and set(value) <= set(keys), label + ": invalid object/fields")


def strings(value, keys, nullable=()):
    for key in keys:
        item = value.get(key)
        require(item is None and key in nullable or type(item) is str,
                "invalid field type: " + key)
        if type(item) is str:
            require("\x00" not in item, "NUL in field: " + key)


def parse(data):
    record(data, ("schema_version", "requested", "scope", "assignment", "snapshot", "host_aliases"), "input")
    require(type(data.get("schema_version")) is int and data["schema_version"] == 1,
            "schema_version must be integer 1")
    requested = data.get("requested")
    record(requested, ("repo", "project_id", "environment_id"), "requested")
    require("environment_id" in requested, "requested environment_id required; null means local")
    strings(requested, ("repo", "project_id", "environment_id"), ("environment_id",))
    require(bool(requested["repo"].strip() and requested["project_id"].strip()), "empty requested target")
    scope = data.get("scope", {})
    record(scope, ("policy", "repo", "project_id", "environment_id", "source"), "scope")
    strings(scope, ("policy", "repo", "project_id", "environment_id", "source"),
            ("policy", "repo", "project_id", "environment_id", "source"))
    assignment = data.get("assignment")
    if assignment is not None:
        record(assignment, ("path", "repo", "project_id", "head", "branch", "status"), "assignment")
        strings(assignment, ("path", "repo", "project_id", "head", "branch", "status"))
        require(all(assignment[k].strip() for k in ("path", "repo", "project_id", "head", "branch")),
                "empty assignment metadata")
        require(Path(assignment["path"]).is_absolute(), "assignment path must be absolute")
        require(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", assignment["head"]) is not None,
                "assignment head must be a full git object id")
    aliases = data.get("host_aliases", {})
    require(type(aliases) is dict, "host_aliases must be object")
    for key, value in aliases.items():
        require(type(value) is str and re.fullmatch(r"[a-z0-9.-]+", key) is not None
                and re.fullmatch(r"[a-z0-9.-]+", value) is not None, "invalid host alias")
    snapshot = data.get("snapshot", {})
    record(snapshot, FIELDS, "snapshot")
    for entry in snapshot.values():
        require(type(entry) is dict and set(entry) in ({"value"}, {"error"}), "invalid observation")
        strings(entry, tuple(entry))
    return data


def identity(locator, aliases):
    """Syntactic identity only. Discard credentials, ports are not aliases."""
    try:
        if "://" in locator:
            url = urlsplit(locator)
            if url.scheme not in ("https", "ssh") or url.query or url.fragment or url.port:
                return None
            host, path = url.hostname, url.path.lstrip("/")
        else:
            match = re.fullmatch(r"(?:[^@/:\s]+@)?([a-zA-Z0-9.-]+):([^\s]+)", locator)
            if not match:
                return None
            host, path = match.groups()
        if not host:
            return None
        host = aliases.get(host.lower(), host.lower())
        if path.endswith(".git"):
            path = path[:-4]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
            return None
        # GitHub names are case insensitive. Other hosts retain path case.
        return host + "/" + (path.lower() if host == "github.com" else path)
    except ValueError:
        return None


def observe(path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    observations = {}
    for key, command in FIELDS.items():
        try:
            run = subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
                                  "-c", "core.untrackedCache=false", "-C", str(path)] + command,
                                 env=env, capture_output=True, text=True, timeout=15)
            observations[key] = ({"value": run.stdout.rstrip("\n")} if run.returncode == 0
                                 else {"error": "git exit " + str(run.returncode)})
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            observations[key] = {"error": "git observation unavailable"}
    return observations


def assess(data, observations, mode, path=None):
    target, scope = data["requested"], data.get("scope", {})
    assigned, aliases = data.get("assignment"), data.get("host_aliases", {})
    target_repo = identity(target["repo"], aliases)
    policy = scope.get("policy")
    plan = "unknown"
    reasons = []
    if policy in ("local_parent_project", "environment_project"):
        if not all(scope.get(k) and scope[k].strip() for k in ("source", "project_id", "repo")):
            plan = "incomplete"
        elif policy == "environment_project" and not scope.get("environment_id"):
            plan = "incomplete"
        else:
            expected_env = None if policy == "local_parent_project" else scope["environment_id"]
            scoped_repo = identity(scope["repo"], aliases)
            plan = ("compatible" if target_repo and target_repo == scoped_repo
                    and target["project_id"] == scope["project_id"]
                    and target.get("environment_id") == expected_env else "rejected")
    if plan != "compatible":
        reasons.append("scope_" + plan)
    assignment = "unassigned"
    checkout = "not_observed"
    if assigned is not None:
        assigned_repo = identity(assigned["repo"], aliases)
        assignment = ("matched" if target_repo and target_repo == assigned_repo
                      and target["project_id"] == assigned["project_id"] else "mismatch")
        mismatches = []
        expected = {"root": assigned["path"], "head": assigned["head"],
                    "branch": assigned["branch"], "status": assigned["status"]}
        for key, value in expected.items():
            entry = observations.get(key, {})
            if "value" in entry and entry["value"] != value:
                mismatches.append(key)
        origin = observations.get("origin", {}).get("value")
        if origin is not None and (not target_repo or identity(origin, aliases) != target_repo
                                   or identity(origin, aliases) != assigned_repo):
            mismatches.append("origin")
        if path is not None and str(path.resolve()) != assigned["path"]:
            mismatches.append("live_path")
        incomplete = any("value" not in observations.get(k, {}) for k in FIELDS)
        checkout = ("mismatch" if mismatches else "incomplete" if incomplete else mode + "_match")
        reasons.extend("checkout_" + k for k in mismatches)
    if assignment != "matched":
        reasons.append("assignment_" + assignment)
    if checkout in ("incomplete", "not_observed"):
        reasons.append("checkout_" + checkout)
    # Never echo raw origin URLs, error text or arbitrary metadata.
    public = {}
    for key, entry in observations.items():
        if "error" in entry:
            public[key] = {"error": "observation failed"}
        elif key == "origin":
            public[key] = {"identity": identity(entry["value"], aliases)}
        elif key == "status":
            public[key] = {"clean": entry["value"] == ""}
        else:
            public[key] = entry
    consistent = plan == "compatible" and assignment == "matched" and checkout == mode + "_match"
    return dict(schema_version=1, comparison="consistent" if consistent else "blocked",
                mode=mode, plan=plan, assignment=assignment, checkout=checkout,
                observations=public, reasons=reasons,
                limitation="Point-in-time membership comparison only; no launch, safety, approval or merge verdict."), 0 if consistent else 1


def load(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda _: require(False, "invalid JSON constant"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--case", help="Select a case from the bundled example collection")
    parser.add_argument("--checkout", type=Path, help="Explicit provided checkout to observe read-only")
    args = parser.parse_args()
    try:
        data = load(args.input)
        if args.case:
            require(type(data) is dict and type(data.get("cases")) is dict
                    and args.case in data["cases"], "unknown example case")
            data = data["cases"][args.case]["input"]
        data = parse(data)
        observations = data.get("snapshot", {})
        if args.checkout is not None:
            # An absent assignment must never authorize observing an arbitrary path.
            assigned = data.get("assignment")
            if assigned is None or str(args.checkout.resolve()) != assigned["path"]:
                result, code = assess(data, {}, "live", args.checkout)
            else:
                result, code = assess(data, observe(args.checkout), "live", args.checkout)
        else:
            result, code = assess(data, observations, "snapshot")
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError, RuntimeError):
        result, code = dict(schema_version=1, comparison="invalid_input",
                            errors=["Invalid input or unreadable input file; see schema documentation."]), 2
        print("Invalid preflight input", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
