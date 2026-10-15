"""Owned synthetic control; it is not an unused third-party target."""
import os

class OwnedFile:
    """A context that owns and deletes a temporary file.

    Args:
        path: The path of the owned temporary file.
    """
    def __init__(self, path):
        self.path = path
    def __enter__(self):
        with open(self.path, 'w') as stream:
            stream.write('owned')
        return self
    def __exit__(self, *exc):
        os.unlink(self.path)
