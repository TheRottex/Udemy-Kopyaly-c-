import sqlite3
import time
from contextlib import closing


class Db:
    """İzleme ilerlemesi ve notlar (SQLite)."""

    def __init__(self, path):
        self.path = str(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._c() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS progress(
              slug TEXT, lesson TEXT, position REAL DEFAULT 0, duration REAL DEFAULT 0,
              completed INTEGER DEFAULT 0, updated REAL, PRIMARY KEY(slug, lesson));
            CREATE TABLE IF NOT EXISTS notes(
              id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT, lesson TEXT, t REAL, text TEXT, created REAL);
            """)

    def _c(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return _Ctx(conn)

    def set_progress(self, slug, lesson, position, duration, completed):
        with self._c() as c:
            c.execute("""INSERT INTO progress VALUES(?,?,?,?,?,?)
              ON CONFLICT(slug,lesson) DO UPDATE SET position=excluded.position,
              duration=CASE WHEN excluded.duration>0 THEN excluded.duration ELSE duration END,
              completed=excluded.completed OR completed, updated=excluded.updated""",
                      (slug, lesson, position, duration, int(completed), time.time()))

    def progress(self, slug) -> dict:
        with self._c() as c:
            rows = c.execute("SELECT * FROM progress WHERE slug=?", (slug,)).fetchall()
        return {r["lesson"]: {"position": r["position"], "duration": r["duration"],
                              "completed": bool(r["completed"])} for r in rows}

    def add_note(self, slug, lesson, t, text) -> int:
        with self._c() as c:
            return c.execute("INSERT INTO notes(slug,lesson,t,text,created) VALUES(?,?,?,?,?)",
                             (slug, lesson, t, text, time.time())).lastrowid

    def notes(self, slug, lesson) -> list:
        with self._c() as c:
            rows = c.execute("SELECT id,t,text,created FROM notes WHERE slug=? AND lesson=? ORDER BY t",
                             (slug, lesson)).fetchall()
        return [dict(r) for r in rows]

    def delete_note(self, slug, note_id):
        with self._c() as c:
            c.execute("DELETE FROM notes WHERE id=? AND slug=?", (note_id, slug))


class _Ctx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *a):
        try:
            self.conn.commit()
        finally:
            self.conn.close()
