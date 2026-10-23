"""Taking and releasing the lock on one open lock file, on Windows and on the Mac.

Dan ran on Windows until 2026-10-23 and its lock files were held with msvcrt, which the Mac does not have: `import msvcrt`
raised ModuleNotFoundError there, so every change of a job's state (command_job_state), the work order (work_locks) and
Jev's budget failed on the Mac. Raises OSError while another holder has the lock, as msvcrt does."""


def lock(fd, take):
    """take=True: lock without waiting (OSError when held elsewhere); take=False: release."""
    try:
        import msvcrt
    except ModuleNotFoundError:
        import fcntl
        fcntl.flock(fd, (fcntl.LOCK_EX | fcntl.LOCK_NB) if take else fcntl.LOCK_UN)
        return
    msvcrt.locking(fd, msvcrt.LK_NBLCK if take else msvcrt.LK_UNLCK, 1)
