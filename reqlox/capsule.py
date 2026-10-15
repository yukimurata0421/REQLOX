"""Inspect supplied wheel bytes without installing or importing their code."""
import ast
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

from . import _runtime


def _contract():
    _runtime()
    from reqlox_core import incident_reference
    return incident_reference


def _wheel(path, expected):
    c = _contract()
    path = Path(path)
    c.require(not path.is_symlink() and path.is_file() and path.suffix == '.whl', 'WHEEL_PATH')
    c.require(path.stat().st_size <= 8 * 1024 * 1024, 'WHEEL_COMPRESSED_BYTES')
    raw = path.read_bytes()
    c.require(hashlib.sha256(raw).hexdigest() == expected, 'WHEEL_HASH_DRIFT')
    files = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        c.require(1 <= len(entries) <= 1024, 'WHEEL_FILE_COUNT')
        total = 0
        seen = set()
        for item in entries:
            name = PurePosixPath(item.filename)
            total += item.file_size
            c.require(name.parts and not name.is_absolute() and '..' not in name.parts
                      and '\\' not in item.filename and item.filename not in seen
                      and str(name) == item.filename.rstrip('/')
                      and not item.flag_bits & 1 and (item.external_attr >> 16) & 0o170000 != 0o120000
                      and item.file_size <= 2 * 1024 * 1024 and total <= 16 * 1024 * 1024,
                      'WHEEL_MEMBER_BOUNDARY')
            seen.add(item.filename)
            if not item.is_dir():
                files[item.filename] = archive.read(item)
    metadata = [n for n in files if n.endswith('.dist-info/METADATA')]
    c.require(len(metadata) == 1, 'WHEEL_METADATA')
    prefix = metadata[0].rsplit('/', 1)[0]
    c.require('/' not in prefix and all('.dist-info/' not in n or n.startswith(prefix + '/') for n in files),
              'WHEEL_METADATA_IDENTITY')
    message = BytesParser().parsebytes(files[metadata[0]])
    c.require(len(message.get_all('Name', [])) == len(message.get_all('Version', [])) == 1,
              'WHEEL_NAME_VERSION')
    name = canonicalize_name(message['Name'])
    version = str(Version(message['Version']))
    filename_name, filename_version, _, filename_tags = parse_wheel_filename(path.name)
    c.require(filename_name == name and filename_version == Version(version), 'WHEEL_FILENAME_METADATA_DRIFT')
    c.require(bool(filename_tags & set(sys_tags())), 'WHEEL_INTERPRETER_TAG_UNSUPPORTED')
    wheel_metadata = BytesParser().parsebytes(files.get(prefix + '/WHEEL', b''))
    c.require(wheel_metadata.get('Root-Is-Purelib') == 'true'
              and wheel_metadata.get_all('Tag')
              and all(t.endswith('-none-any') for t in wheel_metadata.get_all('Tag')),
              'WHEEL_PURE_PYTHON_REQUIRED')
    record_name = prefix + '/RECORD'
    c.require(record_name in files, 'WHEEL_RECORD_MISSING')
    records = list(csv.reader(io.StringIO(files[record_name].decode('utf-8'))))
    c.require(all(len(r) == 3 for r in records) and len({r[0] for r in records}) == len(records)
              and {r[0] for r in records} == set(files), 'WHEEL_RECORD_COVERAGE')
    for member, digest, size in records:
        if member == record_name:
            c.require(digest == size == '', 'WHEEL_RECORD_SELF_ENTRY')
            continue
        encoded = base64.urlsafe_b64encode(hashlib.sha256(files[member]).digest()).decode().rstrip('=')
        c.require(digest == 'sha256=' + encoded and size == str(len(files[member])), 'WHEEL_RECORD_DRIFT')
    c.require(not any(n.endswith(('.so', '.pyd', '.dll', '.pth')) or '.data/' in n for n in files),
              'WHEEL_RUNTIME_LAYOUT_UNSUPPORTED')
    licenses = [n for n in files if n.rsplit('/', 1)[-1].lower().startswith(('license', 'licence', 'copying'))]
    c.require(bool(licenses), 'WHEEL_LICENSE_NOTICE_MISSING')
    if message.get('Requires-Python'):
        c.require(Version('.'.join(map(str, sys.version_info[:3]))) in SpecifierSet(message['Requires-Python']),
                  'WHEEL_PYTHON_VERSION')
    sources = {n: v.decode('utf-8') for n, v in files.items() if n.endswith('.py') and '.dist-info/' not in n}
    c.require(sources and all(len(v.encode()) <= 262144 for v in sources.values()), 'WHEEL_SOURCE_BYTES')
    return dict(project=name, version=version, wheel_sha256=expected, sources=sources,
                files_sha256={n: hashlib.sha256(v).hexdigest() for n, v in sorted(files.items())},
                requirements=message.get_all('Requires-Dist', []),
                license_notice_sha256={n: hashlib.sha256(files[n]).hexdigest() for n in licenses})


def inspect_wheels(specifications, *, target_project):
    """Bind a complete pure-Python dependency closure or retain a static hold."""
    c = _contract()
    c.require(type(specifications) is list and 1 <= len(specifications) <= 8, 'CAPSULE_WHEEL_COUNT')
    distributions = {}
    for spec in specifications:
        c.require(set(spec) == {'path', 'sha256'} and re.fullmatch('[a-f0-9]{64}', spec['sha256']),
                  'CAPSULE_WHEEL_SPECIFICATION')
        try:
            value = _wheel(spec['path'], spec['sha256'])
        except (zipfile.BadZipFile, UnicodeError) as exc:
            raise ValueError('WHEEL_ARCHIVE_OR_ENCODING_INVALID') from exc
        c.require(value['project'] not in distributions, 'CAPSULE_DUPLICATE_DISTRIBUTION')
        distributions[value['project']] = value
    target_project = canonicalize_name(target_project)
    c.require(target_project in distributions, 'CAPSULE_TARGET_MISSING')
    holds = []
    sources = {}
    member_distribution = {}
    edges = {}
    environment = default_environment()
    environment['extra'] = ''
    for project, distribution in distributions.items():
        edges[project] = []
        for line in distribution['requirements']:
            requirement = Requirement(line)
            if requirement.marker and not requirement.marker.evaluate(environment):
                continue
            dependency = canonicalize_name(requirement.name)
            edges[project].append(dependency)
            if requirement.url or requirement.extras:
                holds.append(dict(project=project, reason='DEPENDENCY_URL_OR_EXTRAS_UNSUPPORTED'))
            elif dependency not in distributions:
                holds.append(dict(project=project, dependency=dependency, reason='DEPENDENCY_WHEEL_MISSING'))
            elif Version(distributions[dependency]['version']) not in requirement.specifier:
                holds.append(dict(project=project, dependency=dependency, reason='DEPENDENCY_VERSION_MISMATCH'))
        for member, text in distribution['sources'].items():
            c.require(member not in sources, 'CAPSULE_SOURCE_MEMBER_COLLISION')
            sources[member] = text
            member_distribution[member] = project
    reachable = {target_project}
    pending = [target_project]
    while pending:
        for dependency in edges.get(pending.pop(), []):
            if dependency not in reachable:
                reachable.add(dependency)
                pending.append(dependency)
    if set(distributions) - reachable:
        holds.append(dict(reason='UNRELATED_SUPPLIED_DISTRIBUTION'))
    import_roots = {PurePosixPath(n).parts[0].removesuffix('.py') for n in sources}
    c.require(len(sources) <= 1024 and sum(len(v.encode()) for v in sources.values()) <= 16 * 1024 * 1024,
              'CAPSULE_SOURCE_TOTAL_BOUND')
    if import_roots & set(sys.stdlib_module_names):
        holds.append(dict(reason='STANDARD_MODULE_SHADOWING'))
    for member, text in sources.items():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            holds.append(dict(member=member, reason='SOURCE_SYNTAX_UNSUPPORTED'))
            continue
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and not node.level and node.module else [])
            for module in names:
                if module.split('.')[0] not in import_roots | set(sys.stdlib_module_names):
                    holds.append(dict(member=member, module=module, reason='UNPINNED_IMPORT'))
    distributions = {n: {k: v for k, v in d.items() if k != 'sources'} for n, d in distributions.items()}
    return c.seal(dict(kind='LOCAL_PURE_PYTHON_WHEEL_CAPSULE_V1', target_project=target_project,
        status='HELD' if holds else 'READY_STATICALLY', distributions=distributions,
        dependency_edges=edges, sources=sources, member_distribution=member_distribution,
        holds=holds, runtime_python=list(sys.version_info[:3]), runtime_marker_environment=environment,
        runtime_executable_sha256=hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest(),
        package_code_imported=False, build_or_install_executed=False, network_requests=0,
        license_notices_bound=True, rights_approval_inferred=False,
        independent_generalization_certified=False, execution_authority=False))
