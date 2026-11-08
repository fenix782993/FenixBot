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

    # FENIX staff-management extension (safe additive migrations).
    def ensure_management(self):
        with self.con() as c:
            if self.use_postgres:
                c.execute("CREATE TABLE IF NOT EXISTS staff(uid BIGINT PRIMARY KEY, nick TEXT, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, appointed_by BIGINT, appointed TEXT)")
                c.execute("CREATE TABLE IF NOT EXISTS staff_actions(id BIGSERIAL PRIMARY KEY, uid BIGINT NOT NULL, actor BIGINT NOT NULL, action TEXT NOT NULL, reason TEXT, created TEXT NOT NULL)")
                c.execute("CREATE TABLE IF NOT EXISTS shifts(id BIGSERIAL PRIMARY KEY, uid BIGINT NOT NULL, started TEXT NOT NULL, ended TEXT)")
                c.execute("CREATE TABLE IF NOT EXISTS staff_reports(id BIGSERIAL PRIMARY KEY, uid BIGINT NOT NULL, period TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', reviewer BIGINT, review_note TEXT, created TEXT NOT NULL)")
                c.execute("CREATE TABLE IF NOT EXISTS interviews(id BIGSERIAL PRIMARY KEY, candidate BIGINT NOT NULL, interviewer BIGINT NOT NULL, result TEXT NOT NULL, note TEXT, created TEXT NOT NULL)")
            else:
                c.executescript("""
                CREATE TABLE IF NOT EXISTS staff(uid INTEGER PRIMARY KEY, nick TEXT, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, appointed_by INTEGER, appointed TEXT);
                CREATE TABLE IF NOT EXISTS staff_actions(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL, actor INTEGER NOT NULL, action TEXT NOT NULL, reason TEXT, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS shifts(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL, started TEXT NOT NULL, ended TEXT);
                CREATE TABLE IF NOT EXISTS staff_reports(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL, period TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', reviewer INTEGER, review_note TEXT, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS interviews(id INTEGER PRIMARY KEY AUTOINCREMENT, candidate INTEGER NOT NULL, interviewer INTEGER NOT NULL, result TEXT NOT NULL, note TEXT, created TEXT NOT NULL);
                """)

    def staff_list(self): return self._all("SELECT * FROM staff WHERE active=1 ORDER BY role,nick")
    def staff_get(self, uid): return self._one(f"SELECT * FROM staff WHERE uid={self._ph()}", (uid,))
    def staff_set(self, uid, nick, role, actor):
        with self.con() as c:
            ph=self._ph()
            if self.use_postgres:
                c.execute("INSERT INTO staff(uid,nick,role,active,appointed_by,appointed) VALUES(%s,%s,%s,1,%s,%s) ON CONFLICT(uid) DO UPDATE SET nick=EXCLUDED.nick,role=EXCLUDED.role,active=1,appointed_by=EXCLUDED.appointed_by,appointed=EXCLUDED.appointed",(uid,nick,role,actor,self._now()))
            else:
                c.execute("INSERT INTO staff(uid,nick,role,active,appointed_by,appointed) VALUES(?,?,?,1,?,?) ON CONFLICT(uid) DO UPDATE SET nick=excluded.nick,role=excluded.role,active=1,appointed_by=excluded.appointed_by,appointed=excluded.appointed",(uid,nick,role,actor,self._now()))
        self.staff_action(uid,actor,"назначение/изменение должности",role)
    def staff_action(self, uid, actor, action, reason=None):
        with self.con() as c: c.execute(f"INSERT INTO staff_actions(uid,actor,action,reason,created) VALUES({','.join([self._ph()]*5)})",(uid,actor,action,reason,self._now()))
    def staff_remove(self, uid, actor, reason=None):
        with self.con() as c: c.execute(f"UPDATE staff SET active=0 WHERE uid={self._ph()}",(uid,))
        self.staff_action(uid,actor,"снятие с должности",reason)
    def staff_history(self, uid): return self._all(f"SELECT * FROM staff_actions WHERE uid={self._ph()} ORDER BY id DESC LIMIT 30",(uid,))
    def shift_open(self, uid):
        if self._one(f"SELECT id FROM shifts WHERE uid={self._ph()} AND ended IS NULL",(uid,)): return False
        with self.con() as c: c.execute(f"INSERT INTO shifts(uid,started) VALUES({self._ph()},{self._ph()})",(uid,self._now()))
        return True
    def shift_close(self, uid):
        row=self._one(f"SELECT id FROM shifts WHERE uid={self._ph()} AND ended IS NULL ORDER BY id DESC LIMIT 1",(uid,))
        if not row: return False
        with self.con() as c: c.execute(f"UPDATE shifts SET ended={self._ph()} WHERE id={self._ph()}",(self._now(),row['id']))
        return True
    def shift_active(self): return self._all("SELECT s.uid,COALESCE(st.nick,CAST(s.uid AS TEXT)) AS nick,st.role,s.started FROM shifts s LEFT JOIN staff st ON st.uid=s.uid WHERE s.ended IS NULL ORDER BY s.started")
    def report_add(self, uid, period, body):
        with self.con() as c:
            if self.use_postgres:
                return c.execute("INSERT INTO staff_reports(uid,period,body,created) VALUES(%s,%s,%s,%s) RETURNING id",(uid,period,body,self._now())).fetchone()['id']
            return c.execute("INSERT INTO staff_reports(uid,period,body,created) VALUES(?,?,?,?)",(uid,period,body,self._now())).lastrowid
    def reports_pending(self): return self._all("SELECT * FROM staff_reports WHERE status='pending' ORDER BY id")
    def report_review(self, rid, reviewer, status, note=''):
        with self.con() as c: c.execute(f"UPDATE staff_reports SET status={self._ph()},reviewer={self._ph()},review_note={self._ph()} WHERE id={self._ph()}",(status,reviewer,note,rid))
    def report_get(self, rid): return self._one(f"SELECT * FROM staff_reports WHERE id={self._ph()}",(rid,))
    def interview_add(self, candidate, interviewer, result, note=''):
        with self.con() as c: c.execute(f"INSERT INTO interviews(candidate,interviewer,result,note,created) VALUES({','.join([self._ph()]*5)})",(candidate,interviewer,result,note,self._now()))
