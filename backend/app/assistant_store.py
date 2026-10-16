"""Local durable conversation/job journal, separate from the existing notes database."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


class AssistantStore:
    def __init__(self, directory):
        self.path = directory / 'assistant.sqlite3'
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS turns(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                    conversation_id TEXT NOT NULL, text TEXT NOT NULL,
                    status TEXT NOT NULL, response TEXT NOT NULL DEFAULT '',
                    error TEXT, created_at TEXT NOT NULL,
                    context TEXT NOT NULL DEFAULT '[]', events TEXT NOT NULL DEFAULT '[]',
                    citations TEXT NOT NULL DEFAULT '[]', steps INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS turns_conversation ON turns(conversation_id, seq);
                CREATE TABLE IF NOT EXISTS calls(
                    turn_id TEXT NOT NULL, call_id TEXT NOT NULL, name TEXT NOT NULL,
                    arguments TEXT NOT NULL, result TEXT,
                    PRIMARY KEY(turn_id,call_id));
                CREATE TABLE IF NOT EXISTS memories(
                    key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self, tid, cid, text):
        with self.lock, self.connect() as db:
            existing = db.execute('SELECT * FROM turns WHERE id=?', (tid,)).fetchone()
            if existing:
                if existing['text'] != text or existing['conversation_id'] != cid:
                    raise ValueError('Этот идентификатор уже относится к другому сообщению')
                return self.view(existing)
            db.execute('INSERT INTO turns(id,conversation_id,text,status,created_at) VALUES(?,?,?,?,?)',
                       (tid, cid, text, 'queued', now()))
        return self.get(tid)

    @staticmethod
    def view(row):
        if row is None:
            return None
        out = dict(row)
        out.pop('context', None)
        for key in ('events', 'citations'):
            out[key] = json.loads(out[key])
        return out

    def get(self, tid, internal=False):
        with self.connect() as db:
            row = db.execute('SELECT * FROM turns WHERE id=?', (tid,)).fetchone()
            return dict(row) if internal and row else self.view(row)

    def list(self, cid=None, limit=60):
        with self.connect() as db:
            if cid:
                rows = db.execute('SELECT * FROM turns WHERE conversation_id=? ORDER BY seq DESC LIMIT ?', (cid, limit)).fetchall()
            else:
                rows = db.execute('SELECT * FROM turns ORDER BY seq DESC LIMIT ?', (limit,)).fetchall()
            return [self.view(r) for r in reversed(rows)]

    def save(self, tid, **values):
        allowed = {'status','response','error','context','events','citations','steps'}
        if not values or not set(values) <= allowed:
            raise ValueError('Invalid job update')
        for key in ('context','events','citations'):
            if key in values:
                values[key] = json.dumps(values[key], ensure_ascii=False)
        with self.lock, self.connect() as db:
            db.execute('UPDATE turns SET '+','.join(k+'=?' for k in values)+' WHERE id=?', (*values.values(), tid))

    def claim(self):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM turns WHERE status='queued' ORDER BY seq LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE turns SET status='running',error=NULL WHERE id=?", (row['id'],))
                return dict(row)

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE turns SET status='queued' WHERE status='running'")

    def call_result(self, tid, call):
        with self.connect() as db:
            row = db.execute('SELECT * FROM calls WHERE turn_id=? AND call_id=?', (tid,call['call_id'])).fetchone()
            return json.loads(row['result']) if row and row['result'] is not None else None

    def save_call(self, tid, call, result=None):
        with self.lock, self.connect() as db:
            db.execute('INSERT OR IGNORE INTO calls(turn_id,call_id,name,arguments) VALUES(?,?,?,?)',
                       (tid,call['call_id'],call['name'],call['arguments']))
            if result is not None:
                db.execute('UPDATE calls SET result=? WHERE turn_id=? AND call_id=?',
                           (json.dumps(result,ensure_ascii=False),tid,call['call_id']))

    def memories(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM memories ORDER BY updated_at DESC LIMIT 100')]

    def remember(self, key, value):
        with self.connect() as db:
            db.execute('INSERT INTO memories VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at',
                       (key,value,now()))

    def forget(self, key):
        with self.connect() as db:
            db.execute('DELETE FROM memories WHERE key=?', (key,))
