"""Reject real fault workers and external connections in the unit process."""
import os
from pathlib import Path
import sys


def install():
    denied = []

    def reject(reason):
        denied.append(reason)
        raise RuntimeError('OFFLINE_TEST_'+reason)

    def audit(event, args):
        if event == 'subprocess.Popen':
            executable, argv = args[:2]
            name = Path(os.fsdecode(executable)).name
            values = [os.fsdecode(v) for v in argv] if isinstance(argv, (list, tuple)) else []
            if name == 'git':
                allowed = {'rev-parse','ls-files','init','add','config','commit','show','diff'}
                if not any(v in allowed for v in values[1:]):
                    reject('CHILD_COMMAND_DENIED')
            elif name.startswith('python'):
                static = any(Path(v).name == 'prepare_reliability_reuse.py' for v in values[1:])
                cli = '-m' in values and 'reqlox' in values and (
                    '--help' in values or '--version' in values or '--dry-run' in values or 'inventory' in values)
                local_import = (values[1:5] == ['-m','reqlox','knowledge','import']
                    and len(values) == 9 and values[5] == '--documents'
                    and values[7] == '--state-dir'
                    and Path(values[6]).resolve().is_relative_to(Path('/tmp'))
                    and Path(values[8]).resolve().is_relative_to(Path('/tmp')))
                if not (static or cli or local_import):
                    reject('CHILD_COMMAND_DENIED')
            else:
                reject('CHILD_COMMAND_DENIED')
        elif event == 'os.system':
            reject('SHELL_DENIED')
        elif event == 'socket.connect':
            address = args[1]
            if not isinstance(address, tuple) or address[0] not in ('127.0.0.1','::1','localhost'):
                reject('EXTERNAL_CONNECTION_DENIED')
        elif event == 'socket.getaddrinfo':
            if args[0] not in ('127.0.0.1','::1','localhost',None):
                reject('EXTERNAL_DNS_DENIED')

    sys.addaudithook(audit)
    return denied
