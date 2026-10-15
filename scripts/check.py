"""Run the portable unit suite; native experiments are opt-in."""
from pathlib import Path
import os
import sys
import tempfile
import unittest

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(root / "reqlox_core"), str(root / "tests")]
with tempfile.TemporaryDirectory(prefix="reqlox-unit-state-") as directory:
    os.environ["REQLOX_STATE_DIR"] = directory
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(not result.wasSuccessful())
