"""Taking and releasing the lock on one open lock file, on Windows and on the Mac.

Dan ran on Windows until 2026-10-23 and its lock files were held with msvcrt, which the Mac does not have. On the Mac
this takes flock on the whole file: a lock belongs to the opened file, so a second opening refuses it even in the same
process, as msvcrt does. (The msvcrt stand-in of app/_posix_compat uses lockf, whose locks belong to the process: two
holders in one process both got the lock.) Raises OSError while another holder has the lock."""
import sys


def lock(fd, take):
    """take=True: lock without waiting (OSError when held elsewhere); take=False: release."""
    if sys.platform == 'win32':
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_NBLCK if take else msvcrt.LK_UNLCK, 1)
        return
    import fcntl
    fcntl.flock(fd, (fcntl.LOCK_EX | fcntl.LOCK_NB) if take else fcntl.LOCK_UN)
