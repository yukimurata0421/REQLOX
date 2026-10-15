"""Process-wide guard for offline tests; this grants no native authority."""
import os
from pathlib import Path
import sys

_installed = False
_denied = []


def command_allowed(executable, argv, cwd=None):
    """Recognize only local fixture Git commands and static Python entry points."""
    name = Path(os.fsdecode(executable)).name
    values = [os.fsdecode(v) for v in argv] if isinstance(argv, (list, tuple)) else []
    if name == 'git':
        args = values[1:]
        root = Path(cwd or os.getcwd()).resolve()
        while args and args[0] == '-C' and len(args) > 1:
            root = (root / args[1]).resolve()
            args = args[2:]
        if not args:
            return False
        if args[0] in {'rev-parse', 'ls-files', 'show', 'diff'}:
            return True
        if args[0] == 'init' and len(args) > 1:
            root = (root / args[-1]).resolve()
        return (args[0] in {'init', 'add', 'config', 'commit'}
                and root.is_relative_to(Path('/tmp'))
                and '--global' not in args and '--system' not in args)
    if not name.startswith('python') or any(v in values for v in ('-c', '--command')):
        return False
    args = values[1:]
    while args and args[0] in ('-B', '-I', '-S', '-s', '-E'):
        args = args[1:]
    if args:
        repository = Path(__file__).resolve().parents[1]
        static_scripts = {repository / package / filename
                          for package in ('tools', 'reqlox_core')
                          for filename in ('prepare_reliability_reuse.py', 'audit_reliability_reuse.py')}
        if Path(args[0]).resolve() in static_scripts:
            return True
    if args[:2] != ['-m', 'reqlox']:
        return False
    tail = args[2:]
    if tail in (['--version'], ['--help']):
        return True
    if tail and tail[0] == 'inventory':
        return True
    if tail and tail[0] in ('target', 'run') and '--dry-run' in tail:
        return True
    if (len(tail) == 6 and tail[:2] == ['knowledge', 'import']
            and tail[2] == '--documents' and tail[4] == '--state-dir'):
        return all(Path(tail[i]).resolve().is_relative_to(Path('/tmp')) for i in (3, 5))
    return False


def check_event(event, args):
    """Return a refusal reason without starting a child or making a connection."""
    if event == 'subprocess.Popen' and not command_allowed(*args[:3]):
        return 'CHILD_COMMAND_DENIED'
    if event == 'os.posix_spawn':
        if len(args) < 2 or not command_allowed(*args[:2]):
            return 'PROCESS_ESCAPE_DENIED'
        return None
    if event in ('os.system', 'os.exec', 'os.fork', 'os.forkpty'):
        return 'PROCESS_ESCAPE_DENIED'
    if event == 'socket.connect':
        address = args[1]
        if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1', 'localhost'):
            return 'EXTERNAL_CONNECTION_DENIED'
    if event == 'socket.getaddrinfo' and args[0] not in ('127.0.0.1', '::1', 'localhost', None):
        return 'EXTERNAL_DNS_DENIED'
    return None


def install():
    """Install before test imports; inherited static CLI children install it too."""
    global _installed
    if _installed:
        return _denied
    if os.environ.get('REQLOX_RUN_NATIVE_TESTS') == '1':
        raise RuntimeError('OFFLINE_TEST_NATIVE_FLAG_REQUIRES_SEPARATE_AUTHORIZED_HARNESS')

    def audit(event, args):
        reason = check_event(event, args)
        if reason:
            _denied.append(reason)
            raise RuntimeError('OFFLINE_TEST_' + reason)

    sys.addaudithook(audit)
    _installed = True
    os.environ['REQLOX_OFFLINE_TESTING'] = '1'
    return _denied
