"""Owned finite example: exceptional writes leave this invocation's file."""
import os
from pathlib import Path


def persist(destination: Path, data: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(destination.name + f".tmp-{os.getpid()}")
    with pending.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    os.replace(pending, destination)
