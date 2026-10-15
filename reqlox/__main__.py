# Static CLI test children inherit the offline process fence.
import os
if os.environ.get('REQLOX_OFFLINE_TESTING') == '1':
    from .offline_testing import install
    install()

from .cli import main

raise SystemExit(main())
