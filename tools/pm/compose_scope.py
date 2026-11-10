#!/usr/bin/env python3
"""Compare saved Compose effective-config envelopes; never invokes Docker."""
import argparse
import json
import sys
from pathlib import Path


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("non-JSON numeric constant: " + value)


def observe(path, role, errors):
    result = {'role': role, 'argv': None, 'project': None, 'resources': [],
              'down_v_named_candidates': []}
    def error(message):
        errors.append(role + ': ' + message)
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique,
                          parse_constant=reject_constant)
    except (OSError, ValueError, RecursionError) as exc:
        error(str(exc))
        return result
    if not isinstance(data, dict):
        error('envelope must be an object')
        return result
    argv = data.get('argv')
    result['argv'] = argv
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
        error('argv must be a nonempty string array')
    if not isinstance(data.get('compose_version'), str) or not data['compose_version']:
        error('compose_version required')
    config = data.get('config')
    if not isinstance(config, dict):
        error('config object required (docker compose config --format json)')
        return result
    name = config.get('name')
    if not isinstance(name, str) or not name:
        error('effective config.name required; never infer it from argv')
    else:
        result['project'] = name
    volumes = config.get('volumes', {})
    if not isinstance(volumes, dict):
        error('volumes must be an object')
        volumes = {}
    for key, volume in volumes.items():
        if not isinstance(volume, dict) or not isinstance(volume.get('name'), str) or not volume['name']:
            error('unresolved volume identity: ' + key)
            continue
        external = volume.get('external', False)
        if type(external) is not bool:
            error('external must be boolean: ' + key)
            continue
        resource = {'kind': 'external' if external else 'named', 'identity': volume['name'],
                    'key': key, 'down_v_removal_candidate': not external}
        result['resources'].append(resource)
        if not external:
            result['down_v_named_candidates'].append(volume['name'])
        if volume.get('driver', 'local') != 'local' or volume.get('driver_opts'):
            error('volume backing storage/driver scope unknown: ' + key)
    services = config.get('services')
    if not isinstance(services, dict) or not services:
        error('nonempty services object required')
        return result
    for service, value in services.items():
        if not isinstance(value, dict):
            error('service must be object: ' + service)
            continue
        mounts = value.get('volumes', [])
        if not isinstance(mounts, list):
            error('service volumes must be array: ' + service)
            continue
        for mount in mounts:
            if not isinstance(mount, dict) or not isinstance(mount.get('target'), str) or not mount['target']:
                error('unresolved mount: ' + service)
                continue
            kind, source = mount.get('type'), mount.get('source')
            if kind == 'bind' and isinstance(source, str) and source.startswith('/'):
                result['resources'].append({'kind': 'bind', 'identity': source,
                                            'down_v_removal_candidate': False})
            elif kind == 'volume' and isinstance(source, str) and source in volumes:
                pass
            elif kind == 'tmpfs':
                pass
            else:
                error('unknown/anonymous mount identity: ' + service + ':' + mount['target'])
    return result


def compare(normal_path, e2e_path):
    errors = []
    normal = observe(normal_path, 'normal', errors)
    e2e = observe(e2e_path, 'e2e', errors)
    findings = []
    if normal['project'] and normal['project'] == e2e['project']:
        findings.append({'kind': 'project_collision', 'identity': normal['project']})
    for left in normal['resources']:
        for right in e2e['resources']:
            if (left['kind'] == 'bind') != (right['kind'] == 'bind'):
                continue
            if left['identity'] == right['identity']:
                item = {'kind': 'shared_storage', 'identity': left['identity'],
                        'normal_kind': left['kind'], 'e2e_kind': right['kind'],
                        'e2e_down_v_removal_candidate': right['down_v_removal_candidate']}
                if item not in findings:
                    findings.append(item)
    status = 'FAIL' if findings else 'UNKNOWN' if errors else 'PASS'
    return {'status': status, 'observations': [normal, e2e], 'findings': findings,
            'unknowns': errors,
            'scope': 'Saved configs on one assumed Docker daemon/host; no authenticity, live state, '
                     'anonymous-volume inventory, backing-store alias, or deletion-success guarantee.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('normal', help='JSON envelope: argv, compose_version, config')
    parser.add_argument('e2e', help='JSON envelope: argv, compose_version, config')
    args = parser.parse_args()
    report = compare(args.normal, args.e2e)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return {'PASS': 0, 'FAIL': 1, 'UNKNOWN': 2}[report['status']]


if __name__ == '__main__':
    sys.exit(main())
