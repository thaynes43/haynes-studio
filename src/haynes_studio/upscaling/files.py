"""Descriptor-relative access to preallocated attempt and job directories."""

from contextlib import contextmanager
import os
import stat

from .profile import UpscaleError

DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
CREATE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW


@contextmanager
def open_directory(path, *, dir_fd=None):
    descriptor = os.open(path, DIRECTORY, dir_fd=dir_fd)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def read_file(directory: int, name: str, limit: int, code: str) -> bytes:
    with os.fdopen(os.open(name, READ, dir_fd=directory), "rb") as source:
        facts = os.fstat(source.fileno())
        if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1 or facts.st_size > limit:
            raise UpscaleError(code)
        data = source.read(limit + 1)
        if len(data) > limit:
            raise UpscaleError(code)
        return data


def create_file(directory: int, name: str, data: bytes, *, durable=False) -> None:
    with os.fdopen(os.open(name, CREATE, 0o640, dir_fd=directory), "wb") as output:
        os.fchmod(output.fileno(), 0o640)
        output.write(data)
        if durable:
            output.flush()
            os.fsync(output.fileno())
