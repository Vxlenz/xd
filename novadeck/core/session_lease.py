"""OS-released lease prevents another NovaDeck process recovering a live session."""
from pathlib import Path
import sys

from ..integrations.errors import IntegrationError


class SessionLease:
    def __init__(self, path: Path):
        self.path = path
        self._stream = None

    def acquire(self) -> None:
        if self._stream is not None:
            return
        stream = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            stream = self.path.open('a+b')
            if self.path.stat().st_size == 0:
                stream.write(b'\0')
                stream.flush()
            stream.seek(0)
        except OSError as exc:
            if stream is not None:
                stream.close()
            raise IntegrationError('system_recovery_write_failed') from exc
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise IntegrationError('system_session_in_use') from exc
        self._stream = stream

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()  # Both Windows and POSIX release the OS lock here.
            self._stream = None
