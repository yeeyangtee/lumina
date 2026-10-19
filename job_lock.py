"""Serialize each local background job across manual, timer and pipeline runs."""

import fcntl, functools, os
from catalog import DATA_DIR


def single_job(name):
    if name not in {
        'previews',
        'metadata',
        'posters',
        'semantic',
        'integration',
        'fixture',
    }:
        raise ValueError('Unknown job lock')

    def decorate(function):
        @functools.wraps(function)
        def run(*args, **kwargs):
            DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(
                DATA_DIR / (name + '.lock'),
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                0o600,
            )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                return function(*args, **kwargs)
            finally:
                os.close(fd)

        return run

    return decorate
