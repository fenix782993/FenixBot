import os
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


class DB:
    """PostgreSQL-first database adapter; SQLite remains available for local testing."""

    def __init__(self, path="fenix.sqlite3"):
        self.path = path
        self.use_postgres = bool(DATABASE_URL)
        self._psycopg = None
        if self.use_postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError(
                    "DATABASE_URL задан, но psycopg не установлен. "
                    "Добавь psycopg[binary] в requirements.txt."
                ) from exc
            self._psycopg = (psycopg, dict_row)

    def con(self):
        if self.use_postgres:
            psycopg, dict_row = self._psycopg
            return psycopg.connect(DATABASE_URL, row_factory=dict_row)
        import sqlite3
        folder = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(folder, exist_ok=True)
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def _now(self):
        return datetime.now(timezone.utc).isoformat()

    def init(self):
        with self.con() as c:
            if self.use_postgres:
                c.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        uid BIGINT PRIMARY KEY, username TEXT, nick TEXT UNIQUE,
                        pwhash TEXT, ref BIGINT, created TEXT
                    )
                """)
                c.execute("""
                    CREATE TABLE IF NOT EXISTS refs (
                        ref BIGINT, uid BIGINT UNIQUE, created TEXT
                    )
                """)
                c.execute("""
                    CREATE TABLE IF NOT EXISTS media (
                        id BIGSERIAL PRIMARY KEY, uid BIGINT, ch TEXT, stats TEXT,
                        contact TEXT, status TEXT, created TEXT
                    )
                """)
                c.execute("CREATE TABLE IF NOT EXISTS invites (link TEXT PRIMARY KEY, owner BIGINT)")
                c.execute("CREATE TABLE IF NOT EXISTS joins (owner BIGINT, uid BIGINT UNIQUE, created TEXT)")
                c.execute("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)")
                c.execute("CREATE TABLE IF NOT EXISTS admins (uid BIGINT PRIMARY KEY, added_by BIGINT, created TEXT)")
            else:
                c.executescript("""
                    CREATE TABLE IF NOT EXISTS users(uid INTEGER PRIMARY KEY, username TEXT, nick TEXT UNIQUE, pwhash TEXT, ref INTEGER, created TEXT);
                    CREATE TABLE IF NOT EXISTS refs(ref INTEGER, uid INTEGER UNIQUE, created TEXT);
                    CREATE TABLE IF NOT EXISTS media(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, ch TEXT, stats TEXT, contact TEXT, status TEXT, created TEXT);
                    CREATE TABLE IF NOT EXISTS invites(link TEXT PRIMARY KEY, owner INTEGER);
                    CREATE TABLE IF NOT EXISTS joins(owner INTEGER, uid INTEGER UNIQUE, created TEXT);
                    CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
                    CREATE TABLE IF NOT EXISTS admins(uid INTEGER PRIMARY KEY, added_by INTEGER, created TEXT);
                """)
            owners = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x]
            for uid in owners:
                if self.use_postgres:
                    c.execute(
                        "INSERT INTO admins(uid,added_by,created) VALUES(%s,%s,%s) ON CONFLICT(uid) DO NOTHING",
                        (uid, uid, self._now())
                    )
                else:
                    c.execute(
                        "INSERT OR IGNORE INTO admins(uid,added_by,created) VALUES(?,?,?)",
                        (uid, uid, self._now())
                    )

    def _one(self, sql, params=()):
        with self.con() as c:
            cur = c.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def _scalar(self, sql, params=()):
        with self.con() as c:
            row = c.execute(sql, params).fetchone()
            if row is None:
                return None
            # psycopg uses dict_row; SQLite returns sqlite3.Row.
            return next(iter(row.values())) if isinstance(row, dict) else row[0]

    def _all(self, sql, params=()):
        with self.con() as c:
            return [dict(x) for x in c.execute(sql, params).fetchall()]

    def _execute(self, sql, params=()):
        with self.con() as c:
            return c.execute(sql, params)

    def _ph(self):
        return "%s" if self.use_postgres else "?"

    def user(self, uid):
        return self._one(f"SELECT * FROM users WHERE uid={self._ph()}", (uid,))

    def nick_exists(self, n):
        return self._one(f"SELECT 1 AS found FROM users WHERE lower(nick)=lower({self._ph()})", (n,)) is not None

    def add_user(self, uid, un, n, pw, ref):
        with self.con() as c:
            c.execute(
                f"INSERT INTO users(uid,username,nick,pwhash,ref,created) VALUES({','.join([self._ph()]*6)})",
                (uid, un, n, pw, ref, self._now())
            )

    def add_ref(self, r, u):
        with self.con() as c:
            if self.use_postgres:
                c.execute("INSERT INTO refs(ref,uid,created) VALUES(%s,%s,%s) ON CONFLICT(uid) DO NOTHING", (r, u, self._now()))
            else:
                c.execute("INSERT OR IGNORE INTO refs(ref,uid,created) VALUES(?,?,?)", (r, u, self._now()))

    def ref_count(self, u):
        return self._scalar(f"SELECT count(*) FROM refs WHERE ref={self._ph()}", (u,))

    def top(self):
        return self._all("""
            SELECT users.nick AS nick,count(refs.uid) AS n
            FROM users LEFT JOIN refs ON refs.ref=users.uid
            GROUP BY users.uid, users.nick ORDER BY n DESC LIMIT 10
        """)

    def save_invite(self, link, owner):
        with self.con() as c:
            if self.use_postgres:
                c.execute("INSERT INTO invites(link,owner) VALUES(%s,%s) ON CONFLICT(link) DO UPDATE SET owner=EXCLUDED.owner", (link, owner))
            else:
                c.execute("INSERT OR REPLACE INTO invites(link,owner) VALUES(?,?)", (link, owner))

    def invite_owner(self, link):
        row = self._one(f"SELECT owner FROM invites WHERE link={self._ph()}", (link,))
        return row["owner"] if row else None

    def add_channel_join(self, owner, uid):
        with self.con() as c:
            if self.use_postgres:
                cur = c.execute("INSERT INTO joins(owner,uid,created) VALUES(%s,%s,%s) ON CONFLICT(uid) DO NOTHING", (owner, uid, self._now()))
            else:
                cur = c.execute("INSERT OR IGNORE INTO joins(owner,uid,created) VALUES(?,?,?)", (owner, uid, self._now()))
            return cur.rowcount > 0

    def channel_count(self, owner):
        return self._scalar(f"SELECT count(*) FROM joins WHERE owner={self._ph()}", (owner,))

    def media(self, uid, ch, stats, contact):
        with self.con() as c:
            if self.use_postgres:
                row = c.execute(
                    "INSERT INTO media(uid,ch,stats,contact,status,created) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id",
                    (uid, ch, stats, contact, "pending", self._now())
                ).fetchone()
                return row["id"]
            cur = c.execute(
                "INSERT INTO media(uid,ch,stats,contact,status,created) VALUES(?,?,?,?,?,?)",
                (uid, ch, stats, contact, "pending", self._now())
            )
            return cur.lastrowid

    def media_get(self, i):
        return self._one(f"SELECT * FROM media WHERE id={self._ph()}", (i,))

    def media_status(self, i, status):
        with self.con() as c:
            c.execute(f"UPDATE media SET status={self._ph()} WHERE id={self._ph()}", (status, i))

    def users_total(self):
        return self._scalar("SELECT count(*) FROM users")

    def refs_total(self):
        return self._scalar("SELECT count(*) FROM refs")

    def media_total(self):
        return self._scalar("SELECT count(*) FROM media")

    def user_ids(self):
        with self.con() as c:
            return [x["uid"] if self.use_postgres else x[0] for x in c.execute("SELECT uid FROM users").fetchall()]

    def set_setting(self, key, value):
        with self.con() as c:
            if self.use_postgres:
                c.execute("INSERT INTO settings(k,v) VALUES(%s,%s) ON CONFLICT(k) DO UPDATE SET v=EXCLUDED.v", (key, value))
            else:
                c.execute("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (key, value))

    def setting(self, key, default=None):
        row = self._one(f"SELECT v FROM settings WHERE k={self._ph()}", (key,))
        return row["v"] if row else default

    def admin_ids(self):
        with self.con() as c:
            return [x["uid"] if self.use_postgres else x[0] for x in c.execute("SELECT uid FROM admins").fetchall()]

    def is_admin(self, uid):
        return self._one(f"SELECT 1 AS found FROM admins WHERE uid={self._ph()}", (uid,)) is not None

    def add_admin(self, uid, by):
        with self.con() as c:
            if self.use_postgres:
                cur = c.execute("INSERT INTO admins(uid,added_by,created) VALUES(%s,%s,%s) ON CONFLICT(uid) DO NOTHING", (uid, by, self._now()))
            else:
                cur = c.execute("INSERT OR IGNORE INTO admins(uid,added_by,created) VALUES(?,?,?)", (uid, by, self._now()))
            return cur.rowcount > 0

    def remove_admin(self, uid):
        with self.con() as c:
            cur = c.execute(f"DELETE FROM admins WHERE uid={self._ph()}", (uid,))
            return cur.rowcount > 0
