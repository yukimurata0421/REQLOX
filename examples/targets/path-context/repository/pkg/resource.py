from pathlib import Path
from tempfile import gettempdir


class Resource:
    def __enter__(self):
        self.path = Path(gettempdir()) / 'owned-resource'
        self.path.touch()
        return self.path

    def __exit__(self, kind, value, traceback):
        self.path.unlink()
