"""Session storage."""
import sys
import threading

from afh.engine.sessions import Store


def test_threads_can_read_at_the_same_time(tmp_path):
    """Opening a thread sends several requests at once, and every one uses the same connection."""
    store = Store(tmp_path / "sessions.db")
    sid = store.create_session("project", title="A thread")["id"]
    store.add_message(sid, {"id": "m1", "type": "user", "content": []})
    faults = []

    def read() -> None:
        try:
            for _ in range(300):
                assert store.get_session(sid)["title"] == "A thread"
                assert len(store.list_messages(sid)) == 1
        except Exception as err:  # noqa: BLE001
            faults.append(repr(err))

    switching = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)
    try:
        threads = [threading.Thread(target=read) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(switching)
        store.db.db.close()
    assert not faults, faults[:3]
