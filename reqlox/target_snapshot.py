"""Copy a selected Target into private data without importing repository code."""
import json
import os
from pathlib import Path
from . import targets, target_audit

SCHEMA = 'reqlox.target-snapshot.v1'
MAX_BYTES = 67108864
MAX_FILES = 4096


def check(condition, reason):
    if not condition:
        raise ValueError(reason)


def build(target, repositories, all_repositories=False):
    from reqlox_core import run_reliability_reuse as runner
    from reqlox_core import reliability_reuse as reuse
    verify_target(target)
    path, manifest, roots = targets.load(target)
    check('authorization' not in manifest, 'TARGET_SNAPSHOT_COPY_BEFORE_AUTHORIZATION')
    selected = list(roots) if all_repositories else list(repositories)
    check(not (all_repositories and repositories) and bool(selected)
          and len(set(selected)) == len(selected) and not set(selected) - set(roots), 'TARGET_SNAPSHOT_SELECTION')
    entries = []; payload = {}; total = 0
    copied = dict(schema=targets.SCHEMA, name=manifest['name'], snapshot_receipt='snapshot.json', repositories={})
    for name in selected:
        row = manifest['repositories'][name]
        configuration = targets.path_at(row['configuration'], path.parent)
        raw_config = configuration.read_bytes()
        config = targets.validate_configuration(targets.read_json(configuration))
        sources = runner.load_snapshot(roots[name])
        source_files = {}
        for member in sources:
            raw = (roots[name] / member).read_bytes()
            check(raw.decode().replace('\r\n', '\n').replace('\r', '\n') == sources[member], 'TARGET_SNAPSHOT_SOURCE_CHANGED')
            source_files[member] = raw
            payload[f'repositories/{name}/{member}'] = raw
        config_name = f'contracts/{name}.json'
        payload[config_name] = raw_config
        copied['repositories'][name] = dict(path=f'repositories/{name}', configuration=config_name)
        dependency = None; dependency_raw = None
        if 'dependency' in row:
            dependency = targets.path_at(row['dependency'], path.parent)
            check(dependency.suffix == '.whl' and dependency.stat().st_size <= 16777216, 'TARGET_SNAPSHOT_DEPENDENCY_BOUND')
            dependency_raw = dependency.read_bytes()
            dependency_name = f'dependencies/{name}/{dependency.name}'
            payload[dependency_name] = dependency_raw
            copied['repositories'][name]['dependency'] = dependency_name
        total += sum(len(v) for v in source_files.values()) + len(raw_config) + len(dependency_raw or b'')
        check(total <= MAX_BYTES and len(payload) <= MAX_FILES, 'TARGET_SNAPSHOT_COPY_BOUND')
        entries.append(dict(name=name, root=roots[name], configuration=configuration, raw_config=raw_config,
            config=config, sources=sources, source_files=source_files, dependency=dependency, dependency_raw=dependency_raw))
    return path, manifest, roots, copied, entries, payload


def unchanged(path, manifest, entries):
    check(targets.read_json(path) == manifest, 'TARGET_SNAPSHOT_MANIFEST_CHANGED')
    for entry in entries:
        check(entry['configuration'].read_bytes() == entry['raw_config'], 'TARGET_SNAPSHOT_CONFIGURATION_CHANGED')
        from reqlox_core import run_reliability_reuse as runner
        check(runner.load_snapshot(entry['root']) == entry['sources'] and all(
            (entry['root'] / member).read_bytes() == raw for member, raw in entry['source_files'].items()),
            'TARGET_SNAPSHOT_SOURCE_CHANGED')
        if entry['dependency'] is not None:
            check(entry['dependency'].read_bytes() == entry['dependency_raw'], 'TARGET_SNAPSHOT_DEPENDENCY_CHANGED')


def save_bundle(target, repositories, output, all_repositories=False):
    from reqlox_core import run_reliability_reuse as runner
    from reqlox_core import reliability_reuse as reuse
    path, original, roots, copied, entries, payload = build(target, repositories, all_repositories)
    output = runner.private(Path(os.path.abspath(output)), new=True)
    check(not any(output.is_relative_to(root) or root.is_relative_to(output) for root in roots.values()), 'TARGET_SNAPSHOT_OVERLAP')
    check(output.parent.is_dir() and output.parent.stat().st_uid == os.getuid()
          and not output.parent.stat().st_mode & 0o077, 'TARGET_SNAPSHOT_PRIVATE_PARENT')
    unchanged(path, original, entries)
    output.mkdir(mode=0o700)
    # Failures retain this new directory. An existing snapshot is never overwritten.
    for relative, raw in payload.items():
        destination = output / relative
        parent = output
        for part in Path(relative).parts[:-1]:
            parent = parent / part
            parent.mkdir(mode=0o700, exist_ok=True)
            check(not parent.is_symlink() and parent.stat().st_uid == os.getuid()
                  and not parent.stat().st_mode & 0o077, 'TARGET_SNAPSHOT_PRIVATE_DIRECTORY')
        with destination.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
    # Mapping order determines --all dispatch order; preserve the selection.
    with (output / 'target.json').open('x') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(json.dumps(copied, ensure_ascii=False, indent=2) + '\n')
    unchanged(path, original, entries)
    repositories = [dict(name=e['name'], original_root=str(e['root']), original_configuration=str(e['configuration']),
        sources_sha256=targets.digest(e['sources']), configuration_sha256=targets.digest(e['config']),
        dependency_sha256=None if e['dependency_raw'] is None else reuse.sha(e['dependency_raw']),
        copied_python_files=len(e['sources'])) for e in entries]
    record = reuse.c.seal(dict(schema=SCHEMA, status='SNAPSHOTTED', output=str(output),
        origin_manifest_sha256=targets.digest(original), target_manifest_sha256=targets.digest(copied),
        selected_repositories=list(copied['repositories']), repositories=repositories,
        files=target_audit.files(output), copied_bytes=sum(len(v) for v in payload.values()),
        original_selected_inputs_unchanged=True, checkout_write_authority=False,
        native_attempts=0, provider_calls=0, independent_generalization_certified=False,
        unselected_files_copied=False, implicit_home_copy=False))
    runner.save(output / 'snapshot.json', record)
    verify(output)
    return dict(status='SNAPSHOTTED', output=str(output), target=str(output / 'target.json'), repositories=repositories,
        copied_bytes=record['copied_bytes'], native_attempts=0, provider_calls=0,
        original_selected_inputs_unchanged=True, checkout_write_authority=False, independent_generalization_certified=False)


def verify(output):
    from reqlox_core import run_reliability_reuse as runner
    from reqlox_core import reliability_reuse as reuse
    output = runner.private(Path(os.path.abspath(output)))
    check(output.is_dir() and output.stat().st_uid == os.getuid() and not output.stat().st_mode & 0o077,
          'TARGET_SNAPSHOT_PRIVATE_DIRECTORY')
    record = target_audit.read(output / 'snapshot.json'); reuse.c.check_seal(record)
    check(record['schema'] == SCHEMA and record['status'] == 'SNAPSHOTTED' and record['output'] == str(output),
          'TARGET_SNAPSHOT_RECEIPT')
    for field in ('checkout_write_authority', 'independent_generalization_certified', 'unselected_files_copied',
                  'implicit_home_copy'):
        check(record[field] is False, 'TARGET_SNAPSHOT_CLAIM_DRIFT')
    check(record['original_selected_inputs_unchanged'] is True
          and type(record['native_attempts']) is int and record['native_attempts'] == 0
          and type(record['provider_calls']) is int and record['provider_calls'] == 0, 'TARGET_SNAPSHOT_CLAIM_DRIFT')
    current_files = target_audit.files(output); current_files.pop('snapshot.json')
    check(current_files == record['files'], 'TARGET_SNAPSHOT_FILE_DRIFT')
    _, manifest, roots = targets.load(output / 'target.json')
    check(manifest.get('snapshot_receipt') == 'snapshot.json', 'TARGET_SNAPSHOT_RECEIPT_PATH')
    selected = list(manifest['repositories'])
    check(record['target_manifest_sha256'] == targets.digest(manifest)
          and record['selected_repositories'] == selected
          and [r['name'] for r in record['repositories']] == selected, 'TARGET_SNAPSHOT_MANIFEST_DRIFT')
    expected = {'target.json'}; total = 0
    for row in record['repositories']:
        name = row['name']; config_name = f'contracts/{name}.json'
        copied = manifest['repositories'][name]
        check(copied['path'] == f'repositories/{name}' and copied['configuration'] == config_name,
              'TARGET_SNAPSHOT_PATH_DRIFT')
        sources = runner.load_snapshot(roots[name])
        config = targets.validate_configuration(targets.read_json(output / config_name))
        check(targets.digest(sources) == row['sources_sha256'] and targets.digest(config) == row['configuration_sha256']
              and len(sources) == row['copied_python_files'], 'TARGET_SNAPSHOT_INPUT_DRIFT')
        expected.add(config_name)
        expected.update(f'repositories/{name}/{member}' for member in sources)
        dependency = copied.get('dependency')
        if dependency is None:
            check(row['dependency_sha256'] is None, 'TARGET_SNAPSHOT_DEPENDENCY_DRIFT')
        else:
            check(dependency.startswith(f'dependencies/{name}/') and len(Path(dependency).parts) == 3
                  and Path(dependency).suffix == '.whl', 'TARGET_SNAPSHOT_DEPENDENCY_PATH')
            raw = (output / dependency).read_bytes()
            check(len(raw) <= 16777216 and reuse.sha(raw) == row['dependency_sha256'], 'TARGET_SNAPSHOT_DEPENDENCY_DRIFT')
            expected.add(dependency)
    check(set(current_files) == expected and len(current_files)-1 <= MAX_FILES, 'TARGET_SNAPSHOT_FILE_SET')
    for name in expected - {'target.json'}:
        total += (output / name).stat().st_size
    check(total == record['copied_bytes'] <= MAX_BYTES, 'TARGET_SNAPSHOT_COPY_BOUND')
    return dict(status='VERIFIED', snapshot_status='SNAPSHOTTED', selected_repositories=selected,
        snapshot_inputs_verified=True, original_repository_rechecked=False, original_checkout_write_authority=False,
        fault_injection_verified=False, repair_verified=False, new_native_campaigns=0, new_provider_calls=0,
        archived_code_executed=False, independent_generalization_certified=False)


def verify_target(target):
    """Prepared manifests retain the copy receipt and cannot redirect its roots."""
    path, manifest, roots = targets.load(target)
    if 'snapshot_receipt' not in manifest:
        return
    receipt = targets.path_at(manifest['snapshot_receipt'], path.parent)
    verify(receipt.parent)
    _, _, copied_roots = targets.load(receipt.parent / 'target.json')
    check(all(name in copied_roots and root == copied_roots[name] for name, root in roots.items()),
          'TARGET_SNAPSHOT_ROOT_REDIRECT')
