from app.services.file_lock import lock


def test_a_held_lock_refuses_a_second_holder(tmp_path):
    path = tmp_path / 'x.lock'
    path.write_bytes(b'0')
    with path.open('a+b') as a, path.open('a+b') as b:
        a.seek(0); lock(a.fileno(), True)
        b.seek(0)
        try:
            lock(b.fileno(), True)
            raise AssertionError('taken twice')
        except OSError:
            pass
        a.seek(0); lock(a.fileno(), False)
        b.seek(0); lock(b.fileno(), True)
        b.seek(0); lock(b.fileno(), False)
