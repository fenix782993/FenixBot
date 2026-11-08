import os
import time
import logging
from functools import lru_cache
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


class DB:
    """PostgreSQL-first database adapter; SQLite remains available for local testing."""

    def __init__(self, path="fenix.sqlite3"):
        self.path = path
        self.use_postgres = bool(DATABASE_URL)
        self._psycopg = None
        self._pool = None
        self._settings_cache = {}
        if self.use_postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
                try:
                    from psycopg_pool import ConnectionPool
                except ImportError:
                    ConnectionPool = None
            except ImportError as exc:
                raise RuntimeError(
                    "DATABASE_URL задан, но psycopg не установлен. "
                    "Добавь psycopg[binary] в requirements.txt."
                ) from exc
            self._psycopg = (psycopg, dict_row)
            if ConnectionPool is not None:
                self._pool = ConnectionPool(
                    conninfo=DATABASE_URL,
                    min_size=1,
                    max_size=8,
                    timeout=10,
                    kwargs={"row_factory": dict_row, "connect_timeout": 12,
                            "keepalives": 1, "keepalives_idle": 30,
                            "keepalives_interval": 10, "keepalives_count": 3},
                    open=True,
                )

    def con(self):
        if self.use_postgres:
            if self._pool is not None:
                return self._pool.connection()
            psycopg, dict_row = self._psycopg
            return psycopg.connect(
                DATABASE_URL, row_factory=dict_row, connect_timeout=12,
                keepalives=1, keepalives_idle=30,
                keepalives_interval=10, keepalives_count=3,
            )
        import sqlite3
        folder = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(folder, exist_ok=True)
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def _now(self):
        return datetime.now(timezone.utc).isoformat()

    def init(self):
        """Initialize schema; retry transient Neon/network disconnects safely."""
        if not self.use_postgres:
            return self._init_once()

        psycopg, _ = self._psycopg
        retry_errors = (psycopg.OperationalError, psycopg.InterfaceError)
        last_error = None

        for attempt in range(1, 9):
            try:
                self._init_once()
                logging.info("PostgreSQL schema initialized successfully.")
                return
            except retry_errors as exc:
                last_error = exc
                logging.warning(
                    "Neon PostgreSQL connection failed during DB initialization "
                    "(attempt %s/8): %s",
                    attempt, exc
                )
                if attempt < 8:
                    time.sleep(min(2 ** (attempt - 1), 20))

        raise RuntimeError(
            "Не удалось подключиться к Neon PostgreSQL после 8 попыток. "
            "Проверь DATABASE_URL, SSL и состояние Neon."
        ) from last_error

    def _init_once(self):
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
                c.execute("CREATE TABLE IF NOT EXISTS staff_roles (uid BIGINT, kind TEXT, title TEXT, assigned_by BIGINT, updated TEXT, PRIMARY KEY(uid,kind))")
                # Upgrade legacy Neon installations without dropping existing staff data.
                # Older schemas may contain only uid, or lack some of the newer fields.
                c.execute("ALTER TABLE staff_roles ADD COLUMN IF NOT EXISTS kind TEXT")
                c.execute("ALTER TABLE staff_roles ADD COLUMN IF NOT EXISTS title TEXT")
                c.execute("ALTER TABLE staff_roles ADD COLUMN IF NOT EXISTS assigned_by BIGINT")
                c.execute("ALTER TABLE staff_roles ADD COLUMN IF NOT EXISTS updated TEXT")
                c.execute("UPDATE staff_roles SET kind='admin' WHERE kind IS NULL OR kind=''")
                c.execute("UPDATE staff_roles SET title='Администратор' WHERE title IS NULL OR title=''")
                c.execute("UPDATE staff_roles SET updated=%s WHERE updated IS NULL OR updated=''", (self._now(),))
                # Ensure ON CONFLICT(uid,kind) works even when the legacy primary key differs.
                c.execute("""
                    DELETE FROM staff_roles a USING staff_roles b
                    WHERE a.ctid < b.ctid AND a.uid=b.uid AND a.kind=b.kind
                """)
                c.execute("CREATE UNIQUE INDEX IF NOT EXISTS staff_roles_uid_kind_uq ON staff_roles(uid,kind)")
                c.execute("CREATE TABLE IF NOT EXISTS media_payouts (id BIGSERIAL PRIMARY KEY, uid BIGINT, amount TEXT, requisites TEXT, status TEXT, created TEXT, reviewed_by BIGINT, review_note TEXT)")
                c.execute("CREATE TABLE IF NOT EXISTS media_activity (uid BIGINT, day TEXT, video_url TEXT, PRIMARY KEY(uid,day))")
                c.execute("CREATE TABLE IF NOT EXISTS media_payout_evidence (payout_id BIGINT PRIMARY KEY, channel_url TEXT, video_url TEXT)")
                c.execute("CREATE TABLE IF NOT EXISTS tickets (id BIGSERIAL PRIMARY KEY, uid BIGINT, subject TEXT, body TEXT, status TEXT, created TEXT, updated TEXT)")
                c.execute("CREATE TABLE IF NOT EXISTS ticket_messages (id BIGSERIAL PRIMARY KEY, ticket_id BIGINT, sender BIGINT, body TEXT, created TEXT)")
                c.execute("CREATE TABLE IF NOT EXISTS notifications (id BIGSERIAL PRIMARY KEY, uid BIGINT, title TEXT, body TEXT, created TEXT, is_read INTEGER DEFAULT 0)")
                c.execute("CREATE TABLE IF NOT EXISTS achievements (uid BIGINT, code TEXT, title TEXT, earned TEXT, PRIMARY KEY(uid,code))")
                c.execute("CREATE TABLE IF NOT EXISTS media_video_stats (id BIGSERIAL PRIMARY KEY, uid BIGINT, video_url TEXT, views BIGINT DEFAULT 0, checked_by BIGINT, created TEXT)")
            else:
                c.executescript("""
                    CREATE TABLE IF NOT EXISTS users(uid INTEGER PRIMARY KEY, username TEXT, nick TEXT UNIQUE, pwhash TEXT, ref INTEGER, created TEXT);
                    CREATE TABLE IF NOT EXISTS refs(ref INTEGER, uid INTEGER UNIQUE, created TEXT);
                    CREATE TABLE IF NOT EXISTS media(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, ch TEXT, stats TEXT, contact TEXT, status TEXT, created TEXT);
                    CREATE TABLE IF NOT EXISTS invites(link TEXT PRIMARY KEY, owner INTEGER);
                    CREATE TABLE IF NOT EXISTS joins(owner INTEGER, uid INTEGER UNIQUE, created TEXT);
                    CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
                    CREATE TABLE IF NOT EXISTS admins(uid INTEGER PRIMARY KEY, added_by INTEGER, created TEXT);
                    CREATE TABLE IF NOT EXISTS staff_roles(uid INTEGER, kind TEXT, title TEXT, assigned_by INTEGER, updated TEXT, PRIMARY KEY(uid,kind));
                    CREATE TABLE IF NOT EXISTS media_payouts(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, amount TEXT, requisites TEXT, status TEXT, created TEXT, reviewed_by INTEGER, review_note TEXT);
                    CREATE TABLE IF NOT EXISTS media_activity(uid INTEGER, day TEXT, video_url TEXT, PRIMARY KEY(uid,day));
                    CREATE TABLE IF NOT EXISTS media_payout_evidence(payout_id INTEGER PRIMARY KEY, channel_url TEXT, video_url TEXT);
                    CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, subject TEXT, body TEXT, status TEXT, created TEXT, updated TEXT);
                    CREATE TABLE IF NOT EXISTS ticket_messages(id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER, sender INTEGER, body TEXT, created TEXT);
                    CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, title TEXT, body TEXT, created TEXT, is_read INTEGER DEFAULT 0);
                    CREATE TABLE IF NOT EXISTS achievements(uid INTEGER, code TEXT, title TEXT, earned TEXT, PRIMARY KEY(uid,code));
                    CREATE TABLE IF NOT EXISTS media_video_stats(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, video_url TEXT, views INTEGER DEFAULT 0, checked_by INTEGER, created TEXT);
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

    def _run_read(self, sql, params, mode):
        # Neon can close an idle pooled SSL connection between requests.
        # Retry a read once on a fresh pool connection instead of failing the
        # Telegram update and making a valid player look logged out.
        attempts = 2 if self.use_postgres else 1
        last_error = None
        for attempt in range(attempts):
            try:
                with self.con() as c:
                    cur = c.execute(sql, params)
                    if mode == "one":
                        row = cur.fetchone()
                        return dict(row) if row is not None else None
                    if mode == "scalar":
                        row = cur.fetchone()
                        if row is None:
                            return None
                        return next(iter(row.values())) if isinstance(row, dict) else row[0]
                    return [dict(x) for x in cur.fetchall()]
            except Exception as exc:
                last_error = exc
                if not self.use_postgres or attempt + 1 >= attempts:
                    raise
                psycopg, _ = self._psycopg
                if not isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)):
                    raise
                logging.warning("Retrying read after stale PostgreSQL connection: %s", exc)
        raise last_error

    def _one(self, sql, params=()):
        return self._run_read(sql, params, "one")

    def _scalar(self, sql, params=()):
        return self._run_read(sql, params, "scalar")

    def _all(self, sql, params=()):
        return self._run_read(sql, params, "all")

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

    def media_current(self, uid):
        return self._one(f"SELECT * FROM media WHERE uid={self._ph()} AND status IN ('pending','approved') ORDER BY id DESC LIMIT 1", (uid,))

    def media_payout(self, uid, amount, requisites):
        with self.con() as c:
            if self.use_postgres:
                row=c.execute("INSERT INTO media_payouts(uid,amount,requisites,status,created) VALUES(%s,%s,%s,'pending',%s) RETURNING id", (uid,amount,requisites,self._now())).fetchone()
                return row['id']
            cur=c.execute("INSERT INTO media_payouts(uid,amount,requisites,status,created) VALUES(?,?,?,'pending',?)", (uid,amount,requisites,self._now()))
            return cur.lastrowid

    def media_payout_pending(self, uid):
        return self._one(f"SELECT * FROM media_payouts WHERE uid={self._ph()} AND status='pending' ORDER BY id DESC LIMIT 1", (uid,))

    def media_payout_get(self, payout_id):
        return self._one(f"SELECT * FROM media_payouts WHERE id={self._ph()}", (payout_id,))

    def media_payout_review(self, payout_id, status, reviewer, note=''):
        with self.con() as c:
            c.execute(f"UPDATE media_payouts SET status={self._ph()}, reviewed_by={self._ph()}, review_note={self._ph()} WHERE id={self._ph()}", (status,reviewer,note,payout_id))

    def media_payouts_for_user(self, uid, limit=10):
        return self._all(f"SELECT * FROM media_payouts WHERE uid={self._ph()} ORDER BY id DESC LIMIT {int(limit)}", (uid,))

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
        self._settings_cache.pop(key, None)
        with self.con() as c:
            if self.use_postgres:
                c.execute("INSERT INTO settings(k,v) VALUES(%s,%s) ON CONFLICT(k) DO UPDATE SET v=EXCLUDED.v", (key, value))
            else:
                c.execute("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (key, value))

    def setting(self, key, default=None):
        cached = self._settings_cache.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < 15:
            return cached[1] if cached[1] is not None else default
        row = self._one(f"SELECT v FROM settings WHERE k={self._ph()}", (key,))
        value = row["v"] if row else None
        self._settings_cache[key] = (now, value)
        return value if value is not None else default

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

    def user_by_nick(self, nick):
        return self._one(f"SELECT * FROM users WHERE lower(nick)=lower({self._ph()})", (nick,))

    def staff_display(self, uid):
        user = self.user(uid)
        if not user:
            return f"ID {uid}"
        nick = user.get("nick") or "Без игрового ника"
        username = ("@" + user["username"]) if user.get("username") else "@username не указан"
        return f"{nick} ({username})"

    def set_staff_role(self, uid, kind, title, assigned_by):
        with self.con() as c:
            if self.use_postgres:
                c.execute("""INSERT INTO staff_roles(uid,kind,title,assigned_by,updated)
                    VALUES(%s,%s,%s,%s,%s)
                    ON CONFLICT(uid,kind) DO UPDATE SET title=EXCLUDED.title, assigned_by=EXCLUDED.assigned_by, updated=EXCLUDED.updated""",
                    (uid, kind, title, assigned_by, self._now()))
            else:
                c.execute("""INSERT INTO staff_roles(uid,kind,title,assigned_by,updated)
                    VALUES(?,?,?,?,?) ON CONFLICT(uid,kind) DO UPDATE SET title=excluded.title, assigned_by=excluded.assigned_by, updated=excluded.updated""",
                    (uid, kind, title, assigned_by, self._now()))

    def staff_role(self, uid, kind):
        row = self._one(f"SELECT title FROM staff_roles WHERE uid={self._ph()} AND kind={self._ph()}", (uid, kind))
        return row["title"] if row else None

    def staff_list(self, kind):
        return self._all(f"SELECT uid,title,assigned_by,updated FROM staff_roles WHERE kind={self._ph()} ORDER BY updated", (kind,))

    def remove_staff_role(self, uid, kind):
        with self.con() as c:
            cur = c.execute(f"DELETE FROM staff_roles WHERE uid={self._ph()} AND kind={self._ph()}", (uid, kind))
            return cur.rowcount > 0

    def media_add_day(self, uid, video_url):
        # UTC calendar day, one report per day. The admin must independently verify publications.
        day=datetime.now(timezone.utc).date().isoformat()
        with self.con() as c:
            if self.use_postgres:
                cur=c.execute("INSERT INTO media_activity(uid,day,video_url) VALUES(%s,%s,%s) ON CONFLICT(uid,day) DO NOTHING",(uid,day,video_url))
            else:
                cur=c.execute("INSERT OR IGNORE INTO media_activity(uid,day,video_url) VALUES(?,?,?)",(uid,day,video_url))
            return cur.rowcount>0

    def media_active_days(self, uid):
        return int(self._scalar(f"SELECT COUNT(*) FROM media_activity WHERE uid={self._ph()}",(uid,)) or 0)

    def media_last_payout_request(self, uid):
        return self._one(f"SELECT created FROM media_payouts WHERE uid={self._ph()} ORDER BY id DESC LIMIT 1",(uid,))

    def media_payout_evidence(self, payout_id, channel_url, video_url):
        with self.con() as c:
            if self.use_postgres:
                c.execute("INSERT INTO media_payout_evidence(payout_id,channel_url,video_url) VALUES(%s,%s,%s) ON CONFLICT(payout_id) DO UPDATE SET channel_url=EXCLUDED.channel_url,video_url=EXCLUDED.video_url",(payout_id,channel_url,video_url))
            else:
                c.execute("INSERT OR REPLACE INTO media_payout_evidence(payout_id,channel_url,video_url) VALUES(?,?,?)",(payout_id,channel_url,video_url))

    def media_payout_evidence_get(self, payout_id):
        return self._one(f"SELECT channel_url,video_url FROM media_payout_evidence WHERE payout_id={self._ph()}",(payout_id,)) or {}

    def media_pending_payouts(self):
        return self._all("SELECT id,uid,created FROM media_payouts WHERE status='pending' ORDER BY id ASC")

    def media_payout_set_amount(self, payout_id, amount):
        with self.con() as c:
            c.execute(f"UPDATE media_payouts SET amount={self._ph()} WHERE id={self._ph()}",(amount,payout_id))


    # --- FENIX ONLINE 2.0: user cabinet, support, notifications and media stats ---
    def create_ticket(self, uid, subject, body):
        now = self._now()
        with self.con() as c:
            if self.use_postgres:
                row = c.execute("INSERT INTO tickets(uid,subject,body,status,created,updated) VALUES(%s,%s,%s,'open',%s,%s) RETURNING id", (uid,subject,body,now,now)).fetchone()
                tid = row["id"]
                c.execute("INSERT INTO ticket_messages(ticket_id,sender,body,created) VALUES(%s,%s,%s,%s)", (tid,uid,body,now))
                return tid
            cur = c.execute("INSERT INTO tickets(uid,subject,body,status,created,updated) VALUES(?,?,?,'open',?,?)", (uid,subject,body,now,now))
            tid = cur.lastrowid
            c.execute("INSERT INTO ticket_messages(ticket_id,sender,body,created) VALUES(?,?,?,?)", (tid,uid,body,now))
            return tid

    def tickets_for_user(self, uid, limit=20):
        return self._all(f"SELECT * FROM tickets WHERE uid={self._ph()} ORDER BY id DESC LIMIT {int(limit)}", (uid,))

    def ticket_get(self, tid):
        return self._one(f"SELECT * FROM tickets WHERE id={self._ph()}", (tid,))

    def ticket_messages(self, tid):
        return self._all(f"SELECT * FROM ticket_messages WHERE ticket_id={self._ph()} ORDER BY id ASC", (tid,))

    def ticket_reply(self, tid, sender, body):
        now = self._now()
        with self.con() as c:
            c.execute(f"INSERT INTO ticket_messages(ticket_id,sender,body,created) VALUES({self._ph()},{self._ph()},{self._ph()},{self._ph()})", (tid,sender,body,now))
            c.execute(f"UPDATE tickets SET updated={self._ph()} WHERE id={self._ph()}", (now,tid))

    def ticket_set_status(self, tid, status):
        with self.con() as c:
            c.execute(f"UPDATE tickets SET status={self._ph()},updated={self._ph()} WHERE id={self._ph()}", (status,self._now(),tid))

    def add_notification(self, uid, title, body):
        with self.con() as c:
            c.execute(f"INSERT INTO notifications(uid,title,body,created,is_read) VALUES({','.join([self._ph()]*4)},0)", (uid,title,body,self._now()))

    def notifications_for_user(self, uid, limit=20):
        return self._all(f"SELECT * FROM notifications WHERE uid={self._ph()} ORDER BY id DESC LIMIT {int(limit)}", (uid,))

    def unread_notifications(self, uid):
        return int(self._scalar(f"SELECT COUNT(*) FROM notifications WHERE uid={self._ph()} AND is_read=0", (uid,)) or 0)

    def mark_notifications_read(self, uid):
        with self.con() as c:
            c.execute(f"UPDATE notifications SET is_read=1 WHERE uid={self._ph()}", (uid,))

    def achievement_award(self, uid, code, title):
        with self.con() as c:
            if self.use_postgres:
                cur=c.execute("INSERT INTO achievements(uid,code,title,earned) VALUES(%s,%s,%s,%s) ON CONFLICT(uid,code) DO NOTHING", (uid,code,title,self._now()))
            else:
                cur=c.execute("INSERT OR IGNORE INTO achievements(uid,code,title,earned) VALUES(?,?,?,?)", (uid,code,title,self._now()))
            return cur.rowcount > 0

    def achievements_for_user(self, uid):
        return self._all(f"SELECT * FROM achievements WHERE uid={self._ph()} ORDER BY earned DESC", (uid,))

    def add_media_video_stat(self, uid, video_url, views, checked_by):
        with self.con() as c:
            if self.use_postgres:
                cur=c.execute("INSERT INTO media_video_stats(uid,video_url,views,checked_by,created) VALUES(%s,%s,%s,%s,%s) RETURNING id", (uid,video_url,views,checked_by,self._now()))
                return cur.fetchone()["id"]
            cur=c.execute("INSERT INTO media_video_stats(uid,video_url,views,checked_by,created) VALUES(?,?,?,?,?)", (uid,video_url,views,checked_by,self._now()))
            return cur.lastrowid

    def media_video_stats_for_user(self, uid, limit=20):
        return self._all(f"SELECT * FROM media_video_stats WHERE uid={self._ph()} ORDER BY id DESC LIMIT {int(limit)}", (uid,))

    def media_video_views_total(self, uid):
        return int(self._scalar(f"SELECT COALESCE(SUM(views),0) FROM media_video_stats WHERE uid={self._ph()}", (uid,)) or 0)

    def open_tickets(self, limit=30):
        return self._all("SELECT id,uid,subject,status,created,updated FROM tickets WHERE status IN ('open','answered') ORDER BY updated DESC LIMIT " + str(int(limit)))
