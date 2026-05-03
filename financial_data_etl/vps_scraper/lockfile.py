"""
Process-level lockfile via fcntl.flock (Linux/Unix).

If a previous scrape is still running, we exit cleanly with a log line
instead of double-executing. systemd Type=oneshot already prevents
overlap of the same timer; this is defense in depth for manual triggers.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def file_lock(path: str):
    """
    Context manager that acquires an exclusive non-blocking flock on `path`.

    On Windows fcntl is not available — we fall back to a no-op so the
    rest of the module remains importable in dev/test environments.
    """
    try:
        import fcntl  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("fcntl unavailable (likely Windows). Lockfile is a no-op.")
        yield None
        return

    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.warning("Another VPS scraper run already holds %s. Exiting.", path)
            os.close(fd)
            raise SystemExit(0)
        try:
            yield fd
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                pass
    finally:
        try:
            os.close(fd)
        except Exception:
            pass
