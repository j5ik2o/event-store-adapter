"""CLI behavior tests. Real captures can also be replayed with ci_status.py."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('ci_status.py')
HEAD = 'a' * 40
ROOT = 'repos/example/repo'


def sample():
    row = {'id': 1, 'name': 'test', 'head_sha': HEAD, 'status': 'completed',
           'conclusion': 'success', 'app': {'id': 15368}, 'check_suite': {'id': 2}}
    run = {'id': 3, 'head_sha': HEAD, 'status': 'completed', 'conclusion': 'success',
           'run_attempt': 1, 'check_suite_id': 2}
    job = dict(row, id=4, run_id=3, run_attempt=1, steps=[
        {'name': 'Run tests', 'status': 'completed', 'conclusion': 'success'}])
    capture = {'schema_version': 1, 'repository': 'example/repo', 'head': HEAD,
               'branch': 'main', 'captured_at': 'synthetic', 'responses': {}}
    def add(path, body):
        capture['responses'][ROOT + path] = {'http_status': 200, 'body': body, 'next': None}
    add('/branches/main', {'protected': True})
    add('/branches/main/protection', {'required_status_checks': {'checks': [{'context': 'test', 'app_id': 15368}]}})
    add('/rules/branches/main?per_page=100', [])
    add('/commits/' + HEAD + '/check-runs?per_page=100&filter=latest', {'total_count': 1, 'check_runs': [row]})
    add('/commits/' + HEAD + '/status?per_page=100', {'sha': HEAD, 'total_count': 0, 'statuses': []})
    add('/commits/' + HEAD + '/check-suites?per_page=100', {'total_count': 1, 'check_suites': [dict(row, id=2)]})
    add('/actions/runs?head_sha=' + HEAD + '&per_page=100', {'total_count': 1, 'workflow_runs': [run]})
    add('/actions/runs/3/attempts/1/jobs?per_page=100', {'total_count': 1, 'jobs': [job]})
    return capture


def response(capture, fragment):
    return next(v for k, v in capture['responses'].items() if fragment in k)


# Projections of live GET captures; exact collection counts and result fields retained.
RECORDED = json.loads(r'''
{
"php35": {
  "schema_version": 1,
  "repository": "j5ik2o/event-store-adapter-php",
  "head": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110",
  "branch": "main",
  "captured_at": "2026-11-10T18:38:37.814530+00:00",
  "responses": {
    "repos/j5ik2o/event-store-adapter-php/branches/main": {"http_status": 200, "next": null, "body":
      {"name": "main", "protected": true}
    },
    "repos/j5ik2o/event-store-adapter-php/rules/branches/main?per_page=100": {"http_status": 200, "next": null, "body":
      []
    },
    "repos/j5ik2o/event-store-adapter-php/branches/main/protection": {"http_status": 200, "next": null, "body":
      {"required_status_checks": {"contexts": ["test"], "checks": [{"context": "test", "app_id": 15368}]}}
    },
    "repos/j5ik2o/event-store-adapter-php/commits/7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110/check-runs?per_page=100&filter=latest": {"http_status": 200, "next": null, "body":
      {"total_count": 5, "check_runs": [
        {"id": 129980835139, "name": "test", "head_sha": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110", "status": "completed", "conclusion": "skipped", "check_suite": {"id": 116072835024}, "app": {"id": 15368, "name": "GitHub Actions"}},
        {"id": 129980646156, "name": "lint", "head_sha": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110", "status": "completed", "conclusion": "failure", "check_suite": {"id": 116072835024}, "app": {"id": 15368, "name": "GitHub Actions"}},
        {"id": 129980189628, "name": "CodeRabbit", "head_sha": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110", "status": "completed", "conclusion": "success", "check_suite": {"id": 116072872486}, "app": {"id": 347564, "name": "coderabbitai"}},
        {"id": 129980129297, "name": "review", "head_sha": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110", "status": "completed", "conclusion": "failure", "check_suite": {"id": 116072814400}, "app": {"id": 15368, "name": "GitHub Actions"}},
        {"id": 129980114755, "name": "GitGuardian Security Checks", "head_sha": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110", "status": "completed", "conclusion": "success", "check_suite": {"id": 116072813702}, "app": {"id": 46505, "name": "GitGuardian"}}
      ]}
    },
    "repos/j5ik2o/event-store-adapter-php/commits/7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110/check-suites?per_page=100": {"http_status": 200, "next": null, "body":
      {"total_count": 4, "check_suites": [
        {"id": 116072813702, "head_sha": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110", "status": "completed", "conclusion": "success", "app": {"id": 46505, "name": "GitGuardian"}},
        {"id": 116072814400, "head_sha": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110", "status": "completed", "conclusion": "failure", "app": {"id": 15368, "name": "GitHub Actions"}},
        {"id": 116072835024, "head_sha": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110", "status": "completed", "conclusion": "failure", "app": {"id": 15368, "name": "GitHub Actions"}},
        {"id": 116072872486, "head_sha": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110", "status": "completed", "conclusion": "success", "app": {"id": 347564, "name": "coderabbitai"}}
      ]}
    },
    "repos/j5ik2o/event-store-adapter-php/actions/runs?head_sha=7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110&per_page=100": {"http_status": 200, "next": null, "body":
      {"total_count": 2, "workflow_runs": [
        {"id": 42859122306, "name": "CI", "head_sha": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110", "status": "completed", "conclusion": "failure", "check_suite_id": 116072835024, "run_attempt": 2},
        {"id": 42859114075, "name": "OpenAI Reviewer", "head_sha": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110", "status": "completed", "conclusion": "failure", "check_suite_id": 116072814400, "run_attempt": 1}
      ]}
    },
    "repos/j5ik2o/event-store-adapter-php/actions/runs/42859122306/attempts/2/jobs?per_page=100": {"http_status": 200, "next": null, "body":
      {"total_count": 2, "jobs": [
        {"id": 129980646156, "run_id": 42859122306, "run_attempt": 2, "head_sha": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110", "status": "completed", "conclusion": "failure", "name": "lint", "steps": [{"name": "Set up job", "status": "completed", "conclusion": "success"}, {"name": "Run actions/checkout@v4", "status": "completed", "conclusion": "success"}, {"name": "Validate composer.json and composer.lock", "status": "completed", "conclusion": "success"}, {"name": "Cache Composer packages", "status": "completed", "conclusion": "success"}, {"name": "Install dependencies", "status": "completed", "conclusion": "success"}, {"name": "Run test suite", "status": "completed", "conclusion": "failure"}, {"name": "Post Cache Composer packages", "status": "completed", "conclusion": "skipped"}, {"name": "Post Run actions/checkout@v4", "status": "completed", "conclusion": "success"}, {"name": "Complete job", "status": "completed", "conclusion": "success"}]},
        {"id": 129980835139, "run_id": 42859122306, "run_attempt": 2, "head_sha": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110", "status": "completed", "conclusion": "skipped", "name": "test", "steps": []}
      ]}
    },
    "repos/j5ik2o/event-store-adapter-php/actions/runs/42859114075/attempts/1/jobs?per_page=100": {"http_status": 200, "next": null, "body":
      {"total_count": 1, "jobs": [
        {"id": 129980129297, "run_id": 42859114075, "run_attempt": 1, "head_sha": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110", "status": "completed", "conclusion": "failure", "name": "review", "steps": [{"name": "Set up job", "status": "completed", "conclusion": "failure"}]}
      ]}
    },
    "repos/j5ik2o/event-store-adapter-php/commits/7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110/status?per_page=100": {"http_status": 200, "next": null, "body":
      {"state": "pending", "sha": "7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110", "total_count": 0, "statuses": [
      ]}
    }
  }
},
"common138": {
  "schema_version": 1,
  "repository": "j5ik2o/event-store-adapter",
  "head": "c4a181a4d43bc21394bbe33ebf2887dbf73c1365",
  "branch": "main",
  "captured_at": "2026-11-10T18:38:46.027847+00:00",
  "responses": {
    "repos/j5ik2o/event-store-adapter/branches/main": {"http_status": 200, "next": null, "body":
      {"name": "main", "protected": false}
    },
    "repos/j5ik2o/event-store-adapter/rules/branches/main?per_page=100": {"http_status": 200, "next": null, "body":
      []
    },
    "repos/j5ik2o/event-store-adapter/commits/c4a181a4d43bc21394bbe33ebf2887dbf73c1365/check-runs?per_page=100&filter=latest": {"http_status": 200, "next": null, "body":
      {"total_count": 2, "check_runs": [
        {"id": 129992188476, "name": "CodeRabbit", "head_sha": "c4a181a4d43bc21394bbe33ebf2887dbf73c1365", "status": "completed", "conclusion": "neutral", "check_suite": {"id": 116082050178}, "app": {"id": 347564, "name": "coderabbitai"}},
        {"id": 129992055726, "name": "GitGuardian Security Checks", "head_sha": "c4a181a4d43bc21394bbe33ebf2887dbf73c1365", "status": "completed", "conclusion": "success", "check_suite": {"id": 116082049633}, "app": {"id": 46505, "name": "GitGuardian"}}
      ]}
    },
    "repos/j5ik2o/event-store-adapter/commits/c4a181a4d43bc21394bbe33ebf2887dbf73c1365/check-suites?per_page=100": {"http_status": 200, "next": null, "body":
      {"total_count": 10, "check_suites": [
        {"id": 116082046627, "head_sha": "c4a181a4d43bc21394bbe33ebf2887dbf73c1365", "status": "queued", "conclusion": null, "app": {"id": 12526, "name": "SonarQubeCloud"}},
        {"id": 116082047518, "head_sha": "c4a181a4d43bc21394bbe33ebf2887dbf73c1365", "status": "queued", "conclusion": null, "app": {"id": 8329, "name": "Vercel"}},
        {"id": 116082048215, "head_sha": "c4a181a4d43bc21394bbe33ebf2887dbf73c1365", "status": "queued", "conclusion": null, "app": {"id": 2740, "name": "Renovate"}},
        {"id": 116082049005, "head_sha": "c4a181a4d43bc21394bbe33ebf2887dbf73c1365", "status": "queued", "conclusion": null, "app": {"id": 56611, "name": "Codacy Production"}},
        {"id": 116082049633, "head_sha": "c4a181a4d43bc21394bbe33ebf2887dbf73c1365", "status": "completed", "conclusion": "success", "app": {"id": 46505, "name": "GitGuardian"}},
        {"id": 116082050178, "head_sha": "c4a181a4d43bc21394bbe33ebf2887dbf73c1365", "status": "completed", "conclusion": "neutral", "app": {"id": 347564, "name": "coderabbitai"}},
        {"id": 116082050799, "head_sha": "c4a181a4d43bc21394bbe33ebf2887dbf73c1365", "status": "queued", "conclusion": null, "app": {"id": 1236702, "name": "Claude"}},
        {"id": 116082051465, "head_sha": "c4a181a4d43bc21394bbe33ebf2887dbf73c1365", "status": "queued", "conclusion": null, "app": {"id": 1210556, "name": "Cursor"}},
        {"id": 116082052088, "head_sha": "c4a181a4d43bc21394bbe33ebf2887dbf73c1365", "status": "queued", "conclusion": null, "app": {"id": 254, "name": "Codecov"}},
        {"id": 116082052708, "head_sha": "c4a181a4d43bc21394bbe33ebf2887dbf73c1365", "status": "queued", "conclusion": null, "app": {"id": 811515, "name": "Devin.ai Integration"}}
      ]}
    },
    "repos/j5ik2o/event-store-adapter/actions/runs?head_sha=c4a181a4d43bc21394bbe33ebf2887dbf73c1365&per_page=100": {"http_status": 200, "next": null, "body":
      {"total_count": 0, "workflow_runs": [
      ]}
    },
    "repos/j5ik2o/event-store-adapter/commits/c4a181a4d43bc21394bbe33ebf2887dbf73c1365/status?per_page=100": {"http_status": 200, "next": null, "body":
      {"state": "pending", "sha": "c4a181a4d43bc21394bbe33ebf2887dbf73c1365", "total_count": 0, "statuses": [
      ]}
    }
  }
},
"js1127": {
  "schema_version": 1,
  "repository": "j5ik2o/event-store-adapter-js",
  "head": "f1cde8989835f43421df5b605e0d1ef5a93d44ed",
  "branch": "main",
  "captured_at": "2026-11-10T18:38:48.874192+00:00",
  "responses": {
    "repos/j5ik2o/event-store-adapter-js/branches/main": {"http_status": 200, "next": null, "body":
      {"name": "main", "protected": true}
    },
    "repos/j5ik2o/event-store-adapter-js/rules/branches/main?per_page=100": {"http_status": 200, "next": null, "body":
      []
    },
    "repos/j5ik2o/event-store-adapter-js/branches/main/protection": {"http_status": 200, "next": null, "body":
      {"required_status_checks": {"contexts": ["CI Success"], "checks": [{"context": "CI Success", "app_id": 15368}]}}
    },
    "repos/j5ik2o/event-store-adapter-js/commits/f1cde8989835f43421df5b605e0d1ef5a93d44ed/check-runs?per_page=100&filter=latest": {"http_status": 200, "next": null, "body":
      {"total_count": 13, "check_runs": [
        {"id": 130037296618, "name": "CI Success", "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "check_suite": {"id": 116113649547}, "app": {"id": 15368, "name": "GitHub Actions"}},
        {"id": 130037178305, "name": "codecov/patch", "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "check_suite": {"id": 116113628299}, "app": {"id": 254, "name": "Codecov"}},
        {"id": 130037162791, "name": "codecov/project", "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "check_suite": {"id": 116113628299}, "app": {"id": 254, "name": "Codecov"}},
        {"id": 130036585693, "name": "Codecov Status", "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "check_suite": {"id": 116113649547}, "app": {"id": 15368, "name": "GitHub Actions"}},
        {"id": 130033124883, "name": "test (26.x)", "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "check_suite": {"id": 116113649547}, "app": {"id": 15368, "name": "GitHub Actions"}},
        {"id": 130033124615, "name": "test (24.x)", "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "check_suite": {"id": 116113649547}, "app": {"id": 15368, "name": "GitHub Actions"}},
        {"id": 130033124402, "name": "Run examples", "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "check_suite": {"id": 116113649547}, "app": {"id": 15368, "name": "GitHub Actions"}},
        {"id": 130033124299, "name": "Run package tests", "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "check_suite": {"id": 116113649547}, "app": {"id": 15368, "name": "GitHub Actions"}},
        {"id": 130032816111, "name": "CodeRabbit", "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "neutral", "check_suite": {"id": 116113626791}, "app": {"id": 347564, "name": "coderabbitai"}},
        {"id": 130032776306, "name": "Run lint", "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "check_suite": {"id": 116113649547}, "app": {"id": 15368, "name": "GitHub Actions"}},
        {"id": 130032758693, "name": "GitGuardian Security Checks", "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "check_suite": {"id": 116113626297}, "app": {"id": 46505, "name": "GitGuardian"}},
        {"id": 130032670824, "name": "Check version bump automation", "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "check_suite": {"id": 116113649547}, "app": {"id": 15368, "name": "GitHub Actions"}},
        {"id": 130032670314, "name": "Detect CI-relevant changes", "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "check_suite": {"id": 116113649547}, "app": {"id": 15368, "name": "GitHub Actions"}}
      ]}
    },
    "repos/j5ik2o/event-store-adapter-js/commits/f1cde8989835f43421df5b605e0d1ef5a93d44ed/check-suites?per_page=100": {"http_status": 200, "next": null, "body":
      {"total_count": 11, "check_suites": [
        {"id": 116113624057, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "queued", "conclusion": null, "app": {"id": 12526, "name": "SonarQubeCloud"}},
        {"id": 116113624666, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "queued", "conclusion": null, "app": {"id": 8329, "name": "Vercel"}},
        {"id": 116113625262, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "queued", "conclusion": null, "app": {"id": 2740, "name": "Renovate"}},
        {"id": 116113625821, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "queued", "conclusion": null, "app": {"id": 56611, "name": "Codacy Production"}},
        {"id": 116113626297, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "app": {"id": 46505, "name": "GitGuardian"}},
        {"id": 116113626791, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "neutral", "app": {"id": 347564, "name": "coderabbitai"}},
        {"id": 116113627335, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "queued", "conclusion": null, "app": {"id": 1236702, "name": "Claude"}},
        {"id": 116113627807, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "queued", "conclusion": null, "app": {"id": 1210556, "name": "Cursor"}},
        {"id": 116113628299, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "app": {"id": 254, "name": "Codecov"}},
        {"id": 116113628791, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "queued", "conclusion": null, "app": {"id": 811515, "name": "Devin.ai Integration"}},
        {"id": 116113649547, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "app": {"id": 15368, "name": "GitHub Actions"}}
      ]}
    },
    "repos/j5ik2o/event-store-adapter-js/actions/runs?head_sha=f1cde8989835f43421df5b605e0d1ef5a93d44ed&per_page=100": {"http_status": 200, "next": null, "body":
      {"total_count": 1, "workflow_runs": [
        {"id": 42874083629, "name": "CI", "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "check_suite_id": 116113649547, "run_attempt": 1}
      ]}
    },
    "repos/j5ik2o/event-store-adapter-js/actions/runs/42874083629/attempts/1/jobs?per_page=100": {"http_status": 200, "next": null, "body":
      {"total_count": 9, "jobs": [
        {"id": 130032670314, "run_id": 42874083629, "run_attempt": 1, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "name": "Detect CI-relevant changes", "steps": [{"name": "Set up job", "status": "completed", "conclusion": "success"}, {"name": "Checkout source", "status": "completed", "conclusion": "success"}, {"name": "Detect changed paths", "status": "completed", "conclusion": "success"}, {"name": "Post Checkout source", "status": "completed", "conclusion": "success"}, {"name": "Complete job", "status": "completed", "conclusion": "success"}]},
        {"id": 130032670824, "run_id": 42874083629, "run_attempt": 1, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "name": "Check version bump automation", "steps": [{"name": "Set up job", "status": "completed", "conclusion": "success"}, {"name": "Checkout source", "status": "completed", "conclusion": "success"}, {"name": "Setup Python", "status": "completed", "conclusion": "success"}, {"name": "Verify conformance data", "status": "completed", "conclusion": "success"}, {"name": "Test semver detection", "status": "completed", "conclusion": "success"}, {"name": "Setup Go", "status": "completed", "conclusion": "success"}, {"name": "Check workflows", "status": "completed", "conclusion": "success"}, {"name": "Post Setup Go", "status": "completed", "conclusion": "success"}, {"name": "Post Setup Python", "status": "completed", "conclusion": "success"}, {"name": "Post Checkout source", "status": "completed", "conclusion": "success"}, {"name": "Complete job", "status": "completed", "conclusion": "success"}]},
        {"id": 130032776306, "run_id": 42874083629, "run_attempt": 1, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "name": "Run lint", "steps": [{"name": "Set up job", "status": "completed", "conclusion": "success"}, {"name": "Checkout source", "status": "completed", "conclusion": "success"}, {"name": "Setup pnpm", "status": "completed", "conclusion": "success"}, {"name": "Setup Node.js", "status": "completed", "conclusion": "success"}, {"name": "Enable Corepack", "status": "completed", "conclusion": "success"}, {"name": "Install dependencies", "status": "completed", "conclusion": "success"}, {"name": "Run lint", "status": "completed", "conclusion": "success"}, {"name": "Post Setup Node.js", "status": "completed", "conclusion": "success"}, {"name": "Post Setup pnpm", "status": "completed", "conclusion": "success"}, {"name": "Post Checkout source", "status": "completed", "conclusion": "success"}, {"name": "Complete job", "status": "completed", "conclusion": "success"}]},
        {"id": 130033124299, "run_id": 42874083629, "run_attempt": 1, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "name": "Run package tests", "steps": [{"name": "Set up job", "status": "completed", "conclusion": "success"}, {"name": "Checkout source", "status": "completed", "conclusion": "success"}, {"name": "Setup pnpm", "status": "completed", "conclusion": "success"}, {"name": "Setup Node.js", "status": "completed", "conclusion": "success"}, {"name": "Enable Corepack", "status": "completed", "conclusion": "success"}, {"name": "Install dependencies", "status": "completed", "conclusion": "success"}, {"name": "Run package tests", "status": "completed", "conclusion": "success"}, {"name": "Post Setup Node.js", "status": "completed", "conclusion": "success"}, {"name": "Post Setup pnpm", "status": "completed", "conclusion": "success"}, {"name": "Post Checkout source", "status": "completed", "conclusion": "success"}, {"name": "Complete job", "status": "completed", "conclusion": "success"}]},
        {"id": 130033124402, "run_id": 42874083629, "run_attempt": 1, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "name": "Run examples", "steps": [{"name": "Set up job", "status": "completed", "conclusion": "success"}, {"name": "Checkout source", "status": "completed", "conclusion": "success"}, {"name": "Setup pnpm", "status": "completed", "conclusion": "success"}, {"name": "Setup Node.js", "status": "completed", "conclusion": "success"}, {"name": "Enable Corepack", "status": "completed", "conclusion": "success"}, {"name": "Install dependencies", "status": "completed", "conclusion": "success"}, {"name": "Run examples", "status": "completed", "conclusion": "success"}, {"name": "Post Setup Node.js", "status": "completed", "conclusion": "success"}, {"name": "Post Setup pnpm", "status": "completed", "conclusion": "success"}, {"name": "Post Checkout source", "status": "completed", "conclusion": "success"}, {"name": "Complete job", "status": "completed", "conclusion": "success"}]},
        {"id": 130033124615, "run_id": 42874083629, "run_attempt": 1, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "name": "test (24.x)", "steps": [{"name": "Set up job", "status": "completed", "conclusion": "success"}, {"name": "Checkout source", "status": "completed", "conclusion": "success"}, {"name": "Setup pnpm", "status": "completed", "conclusion": "success"}, {"name": "Use Node.js 24.x", "status": "completed", "conclusion": "success"}, {"name": "Enable Corepack", "status": "completed", "conclusion": "success"}, {"name": "Install dependencies", "status": "completed", "conclusion": "success"}, {"name": "Build", "status": "completed", "conclusion": "success"}, {"name": "Generate coverage", "status": "completed", "conclusion": "success"}, {"name": "Verify coverage file exists", "status": "completed", "conclusion": "success"}, {"name": "Upload conformance report", "status": "completed", "conclusion": "success"}, {"name": "Summarize conformance per rule", "status": "completed", "conclusion": "success"}, {"name": "Upload coverage to Codecov", "status": "completed", "conclusion": "success"}, {"name": "Post Use Node.js 24.x", "status": "completed", "conclusion": "success"}, {"name": "Post Setup pnpm", "status": "completed", "conclusion": "success"}, {"name": "Post Checkout source", "status": "completed", "conclusion": "success"}, {"name": "Complete job", "status": "completed", "conclusion": "success"}]},
        {"id": 130033124883, "run_id": 42874083629, "run_attempt": 1, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "name": "test (26.x)", "steps": [{"name": "Set up job", "status": "completed", "conclusion": "success"}, {"name": "Checkout source", "status": "completed", "conclusion": "success"}, {"name": "Setup pnpm", "status": "completed", "conclusion": "success"}, {"name": "Use Node.js 26.x", "status": "completed", "conclusion": "success"}, {"name": "Enable Corepack", "status": "completed", "conclusion": "success"}, {"name": "Install dependencies", "status": "completed", "conclusion": "success"}, {"name": "Build", "status": "completed", "conclusion": "success"}, {"name": "Generate coverage", "status": "completed", "conclusion": "success"}, {"name": "Verify coverage file exists", "status": "completed", "conclusion": "success"}, {"name": "Upload conformance report", "status": "completed", "conclusion": "success"}, {"name": "Summarize conformance per rule", "status": "completed", "conclusion": "success"}, {"name": "Upload coverage to Codecov", "status": "completed", "conclusion": "success"}, {"name": "Post Use Node.js 26.x", "status": "completed", "conclusion": "success"}, {"name": "Post Setup pnpm", "status": "completed", "conclusion": "success"}, {"name": "Post Checkout source", "status": "completed", "conclusion": "success"}, {"name": "Complete job", "status": "completed", "conclusion": "success"}]},
        {"id": 130036585693, "run_id": 42874083629, "run_attempt": 1, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "name": "Codecov Status", "steps": [{"name": "Set up job", "status": "completed", "conclusion": "success"}, {"name": "Wait for Codecov status checks", "status": "completed", "conclusion": "success"}, {"name": "Complete job", "status": "completed", "conclusion": "success"}]},
        {"id": 130037296618, "run_id": 42874083629, "run_attempt": 1, "head_sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "status": "completed", "conclusion": "success", "name": "CI Success", "steps": [{"name": "Set up job", "status": "completed", "conclusion": "success"}, {"name": "All checks passed", "status": "completed", "conclusion": "success"}, {"name": "Complete job", "status": "completed", "conclusion": "success"}]}
      ]}
    },
    "repos/j5ik2o/event-store-adapter-js/commits/f1cde8989835f43421df5b605e0d1ef5a93d44ed/status?per_page=100": {"http_status": 200, "next": null, "body":
      {"state": "success", "sha": "f1cde8989835f43421df5b605e0d1ef5a93d44ed", "total_count": 1, "statuses": [
        {"id": 58555472520, "state": "success", "context": "Devin Review"}
      ]}
    }
  }
}
}
''')

class CliTests(unittest.TestCase):
    def cli(self, capture):
        return self.raw_cli(json.dumps(capture))

    def raw_cli(self, payload):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.json'
            path.write_text(payload)
            proc = subprocess.run([sys.executable, str(SCRIPT), '--replay', str(path)], capture_output=True, text=True)
        return proc.returncode, json.loads(proc.stdout), proc.stderr

    def test_duplicate_status_context_preserves_every_observation(self):
        for states in [('success', 'failure'), ('failure', 'success')]:
            with self.subTest(states=states):
                capture = sample()
                response(capture, '/status?')['body'] = {
                    'sha': HEAD, 'total_count': 2,
                    'statuses': [{'id': i + 7, 'context': 'other', 'state': state}
                                 for i, state in enumerate(states)]}
                code, report, _ = self.cli(capture)
                self.assertEqual(code, 2)
                self.assertTrue(report['execution']['observed_failure'])
                self.assertEqual(report['execution']['state'], 'unknown')
                self.assertEqual(len(report['commit_statuses']), 2)

    def test_missing_response_body_preserves_prior_failure(self):
        capture = copy.deepcopy(RECORDED['php35'])
        del response(capture, '/jobs?')['body']
        code, report, _ = self.cli(capture)
        self.assertEqual(code, 2)
        self.assertEqual(report['execution'].get('observed_failure'), True)
        self.assertTrue(report['acquisition_errors'])
        self.assertGreater(report['counts']['check_runs'], 0)

    def test_missing_collection_ids_preserve_failure_evidence(self):
        for fragment, key in [('/check-runs?', 'check_runs'), ('/check-suites?', 'check_suites'),
                              ('/actions/runs?', 'workflow_runs'), ('/jobs?', 'jobs'),
                              ('/status?', 'statuses')]:
            with self.subTest(collection=key):
                capture = copy.deepcopy(RECORDED['php35'])
                body = response(capture, fragment)['body']
                if key == 'statuses':
                    body.update(total_count=1, statuses=[{'id': 7, 'context': 'other', 'state': 'failure'}])
                del body[key][0]['id']
                code, report, _ = self.cli(capture)
                self.assertEqual(code, 2)
                self.assertEqual(report['execution'].get('observed_failure'), True)
                self.assertTrue(report['acquisition_errors'])

    def test_successful_job_missing_id_retains_all_evidence(self):
        capture = copy.deepcopy(RECORDED['js1127'])
        jobs = response(capture, '/jobs?')['body']['jobs']
        del jobs[0]['id']
        response(capture, '/check-runs?')['body']['check_runs'][0]['conclusion'] = 'failure'
        code, report, _ = self.cli(capture)
        self.assertEqual(code, 2)
        self.assertEqual(report['execution'].get('observed_failure'), True)
        self.assertEqual(report['counts']['jobs'], len(jobs))
        self.assertEqual(len(report['jobs']), len(jobs))
        self.assertTrue(report['acquisition_errors'])
        self.assertEqual(report['test_execution']['successful_job_ids'],
                         [row['id'] for row in jobs if 'id' in row])

    def test_invalid_lifecycle_cannot_establish_success(self):
        for fragment, key in [('/check-runs?', 'check_runs'),
                              ('/check-suites?', 'check_suites'),
                              ('/actions/runs?', 'workflow_runs'), ('/jobs?', 'jobs')]:
            for invalid in ['success', 'failure', None, True, [], {}]:
                if invalid is None and key in ('check_suites', 'workflow_runs'):
                    continue
                with self.subTest(collection=key, status=invalid):
                    capture = sample()
                    row = response(capture, fragment)['body'][key][0]
                    row.update(status=invalid, conclusion='failure')
                    code, report, _ = self.cli(capture)
                    self.assertEqual(code, 2)
                    self.assertEqual(report['execution']['state'], 'unknown')
                    self.assertEqual(report['execution'].get('observed_failure'), True)
                    self.assertTrue(report['acquisition_errors'])
                    self.assertNotEqual(report['required_gate']['state'], 'accepted')

    def test_pending_lifecycle_statuses_remain_incomplete(self):
        for fragment, key in [('/check-runs?', 'check_runs'),
                              ('/check-suites?', 'check_suites'),
                              ('/actions/runs?', 'workflow_runs'), ('/jobs?', 'jobs')]:
            for pending in ['queued', 'in_progress', 'waiting', 'requested', 'pending']:
                with self.subTest(collection=key, status=pending):
                    capture = sample()
                    response(capture, fragment)['body'][key][0].update(status=pending, conclusion=None)
                    code, report, _ = self.cli(capture)
                    self.assertEqual(code, 1)
                    self.assertEqual(report['execution']['state'], 'incomplete')
                    self.assertEqual(report['acquisition_errors'], [])
                    self.assertFalse(report['execution']['observed_failure'])

    def test_nullable_suite_and_run_statuses_remain_incomplete(self):
        for fragment, key in [('/check-suites?', 'check_suites'),
                              ('/actions/runs?', 'workflow_runs')]:
            with self.subTest(collection=key):
                capture = sample()
                response(capture, fragment)['body'][key][0].update(status=None, conclusion=None)
                code, report, _ = self.cli(capture)
                self.assertEqual(code, 1)
                self.assertEqual(report['execution']['state'], 'incomplete')
                self.assertEqual(report['acquisition_errors'], [])

    def test_nullable_lifecycle_requires_the_status_field(self):
        for fragment, key in [('/check-suites?', 'check_suites'),
                              ('/actions/runs?', 'workflow_runs')]:
            with self.subTest(collection=key):
                capture = sample()
                del response(capture, fragment)['body'][key][0]['status']
                response(capture, '/status?')['body'] = {
                    'sha': HEAD, 'total_count': 1,
                    'statuses': [{'id': 7, 'context': 'other', 'state': 'failure'}]}
                code, report, _ = self.cli(capture)
                self.assertEqual(code, 2)
                self.assertEqual(report['execution']['state'], 'unknown')
                self.assertTrue(report['execution']['observed_failure'])
                self.assertEqual(report['required_gate']['state'], 'unknown')
                self.assertTrue(report['acquisition_errors'])
                self.assertEqual(report['counts']['suites' if key == 'check_suites' else key], 1)

    def test_invalid_run_suite_reference_preserves_evidence(self):
        for identifier in [None, True, [], 0]:
            with self.subTest(identifier=identifier):
                capture = sample()
                response(capture, '/actions/runs?')['body']['workflow_runs'][0]['check_suite_id'] = identifier
                code, report, _ = self.cli(capture)
                self.assertEqual(code, 2)
                self.assertEqual(report['execution']['state'], 'unknown')
                self.assertEqual(report['counts']['jobs'], 1)
                self.assertTrue(report['acquisition_errors'])

    def test_optional_run_suite_reference_can_be_absent(self):
        capture = sample()
        del response(capture, '/actions/runs?')['body']['workflow_runs'][0]['check_suite_id']
        code, report, _ = self.cli(capture)
        self.assertEqual(code, 0)
        self.assertEqual(report['acquisition_errors'], [])
        self.assertEqual(report['suites'][0]['observed_actions_job_count'], 0)

    def test_capture_time_requires_a_nonempty_string(self):
        for value in [None, False, 100, '']:
            with self.subTest(captured_at=value):
                capture = sample()
                capture['captured_at'] = value
                code, report, _ = self.cli(capture)
                self.assertEqual(code, 2)
                self.assertEqual(report['execution']['state'], 'unknown')

    def test_pagination_terminator_must_be_null(self):
        for marker in [False, 0, '', [], {}]:
            with self.subTest(marker=marker):
                capture = sample()
                response(capture, '/check-runs?')['next'] = marker
                code, report, _ = self.cli(capture)
                self.assertEqual(code, 2)
                self.assertEqual(report['execution']['state'], 'unknown')
                self.assertTrue(report['acquisition_errors'])

    def test_duplicate_json_key_is_rejected(self):
        payload = json.dumps(sample()).replace(
            '"conclusion": "success"',
            '"conclusion": "failure", "conclusion": "success"', 1)
        code, report, stderr = self.raw_cli(payload)
        self.assertEqual(code, 2)
        self.assertEqual(report['execution']['state'], 'unknown')
        self.assertIn('duplicate JSON key', stderr)

    def test_nonfinite_json_constants_are_rejected(self):
        for constant in ['NaN', 'Infinity', '-Infinity']:
            with self.subTest(constant=constant):
                payload = json.dumps(sample()).replace('"conclusion": "success"',
                                                       '"conclusion": ' + constant, 1)
                code, report, _ = self.raw_cli(payload)
                self.assertEqual(code, 2)
                self.assertEqual(report['execution']['state'], 'unknown')

    def test_overflowing_json_numbers_do_not_produce_infinity(self):
        for number in ['1e999', '-1e999']:
            with self.subTest(number=number):
                payload = json.dumps(sample()).replace(
                    '"name": "test"', '"metric": ' + number + ', "name": "test"', 1)
                code, report, _ = self.raw_cli(payload)
                self.assertEqual(code, 2)
                self.assertEqual(report['execution']['state'], 'unknown')
        capture = sample()
        response(capture, '/check-runs?')['body']['check_runs'][0]['metric'] = 0.125
        code, report, _ = self.cli(capture)
        self.assertEqual(code, 0)
        self.assertEqual(report['check_runs'][0]['metric'], 0.125)

    def test_malformed_policy_preserves_failure_evidence(self):
        for checks in [True, [], {}, {'checks': None},
                       {'checks': [{'context': 1}]}, {'contexts': [1]}]:
            with self.subTest(checks=checks):
                capture = copy.deepcopy(RECORDED['php35'])
                response(capture, '/protection')['body']['required_status_checks'] = checks
                code, report, _ = self.cli(capture)
                self.assertEqual(code, 2)
                self.assertEqual(report['execution'].get('observed_failure'), True)
                self.assertEqual(report['configuration']['state'], 'unknown')
                self.assertTrue(report['acquisition_errors'])
        for rule in [{}, {'type': []},
                     {'type': 'required_status_checks', 'parameters': None}]:
            with self.subTest(rule=rule):
                capture = copy.deepcopy(RECORDED['php35'])
                response(capture, '/rules/')['body'] = [rule]
                code, report, _ = self.cli(capture)
                self.assertEqual(code, 2)
                self.assertEqual(report['execution'].get('observed_failure'), True)
        capture = sample()
        response(capture, '/protection')['body']['required_status_checks'] = None
        response(capture, '/rules/')['body'] = [{'type': 'future_rule', 'parameters': {}}]
        code, report, _ = self.cli(capture)
        self.assertEqual((code, report['required_gate']['state']), (0, 'none'))
        self.assertEqual(report['acquisition_errors'], [])

    def test_malformed_collection_and_identity_preserve_failure(self):
        for kind in ['row', 'id', 'app', 'check_suite', 'app-id', 'attempt', 'envelope']:
            with self.subTest(kind=kind):
                capture = copy.deepcopy(RECORDED['php35'])
                if kind == 'row':
                    value = response(capture, '/check-runs?')['body']
                    value['check_runs'].append(None)
                    value['total_count'] += 1
                elif kind in ['id', 'app', 'check_suite']:
                    response(capture, '/check-runs?')['body']['check_runs'][0][kind] = []
                elif kind == 'app-id':
                    response(capture, '/check-runs?')['body']['check_runs'][0]['app']['id'] = True
                elif kind == 'attempt':
                    del response(capture, '/actions/runs?')['body']['workflow_runs'][0]['run_attempt']
                else:
                    path = next(k for k in capture['responses'] if '/jobs?' in k)
                    capture['responses'][path] = True
                code, report, _ = self.cli(capture)
                self.assertEqual(code, 2)
                self.assertEqual(report['execution'].get('observed_failure'), True)
                self.assertTrue(report['acquisition_errors'])

    def test_target_and_file_errors_identify_missing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / 'missing.capture.json')
            for args, expected in [([], ['--repo', '--head', '--branch']),
                                   (['--replay', missing], ['missing.capture.json'])]:
                with self.subTest(args=args):
                    proc = subprocess.run([sys.executable, str(SCRIPT), *args],
                                          capture_output=True, text=True)
                    self.assertEqual(proc.returncode, 2)
                    self.assertEqual(json.loads(proc.stdout)['execution']['state'], 'unknown')
                    for text in expected:
                        self.assertIn(text, proc.stderr)

    def test_schema_version_rejects_boolean_and_float(self):
        for version in [True, 1.0]:
            with self.subTest(version=version):
                capture = sample()
                capture['schema_version'] = version
                code, report, stderr = self.cli(capture)
                self.assertEqual(code, 2)
                self.assertEqual(report['execution']['state'], 'unknown')
                self.assertTrue(stderr)

    def test_deep_response_returns_structured_unknown(self):
        payload = json.dumps(sample()).replace(
            '"check_runs": [',
            '"extra": ' + '[' * 5000 + '0' + ']' * 5000 + ', "check_runs": [', 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.json'
            path.write_text(payload)
            proc = subprocess.run([sys.executable, str(SCRIPT), '--replay', str(path)],
                                  capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)['execution']['state'], 'unknown')
        self.assertTrue(proc.stderr)
        self.assertNotIn('Traceback', proc.stderr)

    def test_live_capture_projections(self):
        expected = {'php35': (1, 'accepted', 'failure', 3),
                    'common138': (1, 'none', 'absent', 0),
                    'js1127': (1, 'accepted', 'success', 9)}
        for name, (exit_code, gate, jobs, count) in expected.items():
            with self.subTest(case=name):
                code, report, stderr = self.cli(RECORDED[name])
                self.assertEqual(code, exit_code)
                self.assertTrue(stderr)
                self.assertEqual(report['required_gate']['state'], gate)
                self.assertEqual(report['actual_jobs']['state'], jobs)
                self.assertEqual(report['counts']['jobs'], count)
                self.assertEqual(report['acquisition_errors'], [])
                self.assertEqual(report['test_execution']['state'], 'unverified')
                if name == 'common138':
                    empty = [x for x in report['suites'] if x['status'] == 'queued'
                             and x['observed_check_count'] == 0 and x['observed_actions_job_count'] == 0]
                    self.assertEqual(len(empty), 8)
                    self.assertFalse(report['execution']['observed_failure'])

    def test_success_is_job_evidence_not_test_contents(self):
        code, report, stderr = self.cli(sample())
        self.assertEqual((code, stderr), (0, ''))
        self.assertEqual(report['actual_jobs']['state'], 'success')
        self.assertEqual(report['test_execution']['state'], 'unverified')

    def test_skip_neutral_unknown_and_failure_are_not_execution_success(self):
        for conclusion in ['skipped', 'neutral', None, 'failure', 'timed_out']:
            with self.subTest(conclusion=conclusion):
                capture = sample()
                response(capture, '/check-runs?')['body']['check_runs'][0]['conclusion'] = conclusion
                response(capture, '/jobs?')['body']['jobs'][0]['conclusion'] = conclusion
                code, report, stderr = self.cli(capture)
                self.assertEqual(code, 1)
                self.assertTrue(stderr)
                self.assertEqual(report['required_gate']['state'], 'accepted' if conclusion in ['skipped', 'neutral'] else 'not_accepted')
                self.assertNotEqual(report['actual_jobs']['state'], 'success')

    def test_empty_and_queued_external_suite_are_not_failed_actions(self):
        capture = sample()
        for fragment, key in [('/check-runs?', 'check_runs'), ('/actions/runs?', 'workflow_runs')]:
            response(capture, fragment)['body'] = {'total_count': 0, key: []}
        suite = response(capture, '/check-suites?')['body']['check_suites'][0]
        suite.update(status='queued', conclusion=None, app={'id': 999})
        code, report, _ = self.cli(capture)
        self.assertEqual(code, 1)
        self.assertFalse(report['execution']['observed_failure'])
        self.assertEqual(report['actual_jobs']['state'], 'absent')
        self.assertEqual(report['suites'][0]['observed_actions_job_count'], 0)
        self.assertEqual(report['required_gate']['contexts'][0]['observed'], ['absent'])

    def test_unprotected_is_distinct_from_forbidden_and_not_found(self):
        capture = sample()
        response(capture, '/branches/main')['body']['protected'] = False
        _, report, _ = self.cli(capture)
        self.assertEqual(report['required_gate']['state'], 'none')
        for status in [403, 404, None]:
            broken = copy.deepcopy(capture)
            response(broken, '/rules/')['http_status'] = status
            code, report, _ = self.cli(broken)
            self.assertEqual(code, 2)
            self.assertEqual(report['configuration']['state'], 'unknown')
            self.assertEqual(report['required_gate']['state'], 'unknown')

    def test_pagination_missing_page_total_duplicate_foreign_head(self):
        for mode in ['missing_page', 'count', 'duplicate', 'foreign', 'no_metadata']:
            capture = sample()
            value = response(capture, '/check-runs?')
            if mode == 'missing_page':
                value['next'] = ROOT + '/missing?page=2'
            elif mode == 'count':
                value['body']['total_count'] = 2
            elif mode == 'duplicate':
                value['body']['check_runs'] *= 2
                value['body']['total_count'] = 2
            elif mode == 'foreign':
                value['body']['check_runs'][0]['head_sha'] = 'b' * 40
            else:
                del value['next']
            code, report, _ = self.cli(capture)
            self.assertEqual(code, 2, mode)
            self.assertEqual(report['execution']['state'], 'unknown')

    def test_status_head_and_job_attempt_must_match(self):
        for target in ['status', 'job']:
            capture = sample()
            if target == 'status':
                response(capture, '/status?')['body']['sha'] = 'b' * 40
            else:
                response(capture, '/jobs?')['body']['jobs'][0]['run_attempt'] = 2
            self.assertEqual(self.cli(capture)[0], 2)

    def test_active_rules_require_absent_context_and_protection_unavailable(self):
        capture = sample()
        response(capture, '/rules/')['body'] = [{'type': 'required_status_checks',
            'parameters': {'required_status_checks': [{'context': 'other', 'integration_id': 15368}]}}]
        self.assertEqual(self.cli(capture)[1]['required_gate']['state'], 'not_accepted')
        for status in [403, 404]:
            response(capture, '/protection')['http_status'] = status
            code, report, _ = self.cli(capture)
            self.assertEqual(code, 2)
            self.assertEqual(report['configuration']['state'], 'unknown')

    def test_follow_next_page(self):
        capture = sample()
        value = response(capture, '/check-runs?')
        row = value['body']['check_runs'].pop()
        value['next'] = ROOT + '/checks?page=2'
        capture['responses'][value['next']] = {'http_status': 200, 'next': None,
                                             'body': {'total_count': 1, 'check_runs': [row]}}
        self.assertEqual(self.cli(capture)[0], 0)

    def test_no_data(self):
        capture = sample()
        for value in capture['responses'].values():
            body = value['body']
            if isinstance(body, dict) and 'total_count' in body:
                key = next(k for k in body if k not in ('total_count', 'sha'))
                value['body'] = dict(body, total_count=0, **{key: []})
        code, report, _ = self.cli(capture)
        self.assertEqual(code, 1)
        self.assertEqual(report['actual_jobs']['state'], 'absent')

    def test_required_app_mismatch_and_same_name_status(self):
        capture = sample()
        response(capture, '/check-runs?')['body']['check_runs'][0]['app']['id'] = 999
        self.assertEqual(self.cli(capture)[1]['required_gate']['state'], 'not_accepted')
        capture = sample()
        response(capture, '/status?')['body'] = {'sha': HEAD, 'total_count': 1, 'statuses': [{'id': 7, 'context': 'test', 'state': 'failure'}]}
        self.assertEqual(self.cli(capture)[1]['required_gate']['state'], 'not_accepted')


if __name__ == '__main__':
    unittest.main()
