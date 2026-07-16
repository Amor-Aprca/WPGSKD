import os
import sqlite3
import time
from threading import Lock

class AtomicSQL:
    """Race-condition and Threading safe SQL Database Interface."""
    def __init__(self):
        self.master_lock = Lock()
        self.db = {}
        self.cursor = {}
        self.session_lock = {}

    def load(self, connection: sqlite3.Connection):
        self.master_lock.acquire()
        try:
            session_id = None
            while not session_id or session_id in self.db:
                session_id = os.urandom(16)
            self.db[session_id] = connection
            self.cursor[session_id] = self.db[session_id].cursor()
            self.session_lock[session_id] = Lock()
            return session_id
        finally:
            self.master_lock.release()

    def safe_execute(self, session_id, action):
        if session_id not in self.db:
            raise ValueError(f"Session ID {session_id!r} is invalid.")
        self.master_lock.acquire()
        self.session_lock[session_id].acquire()
        try:
            failures = 0
            while True:
                try:
                    action(db=self.db[session_id], cursor=self.cursor[session_id])
                    break
                except sqlite3.OperationalError:
                    failures += 1
                    delay = 3 * failures
                    print(f"AtomicSQL.safe_execute failed, retrying in {delay} seconds...")
                    time.sleep(delay)
                if failures == 10:
                    raise ValueError("AtomicSQL.safe_execute failed too many time's. Aborting.")
            return self.cursor[session_id]
        finally:
            self.session_lock[session_id].release()
            self.master_lock.release()

    def commit(self, session_id):
        self.safe_execute(session_id, lambda db, cursor: db.commit())
        return True