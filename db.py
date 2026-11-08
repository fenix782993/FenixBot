import sqlite3, os
from datetime import datetime, timezone

class DB:
    def __init__(self, path):
        self.path = path

    def con(self):
        folder = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(folder, exist_ok=True)
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def init(self):
        with self.con() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS users(uid INTEGER PRIMARY KEY, username TEXT, nick TEXT UNIQUE, pwhash TEXT, ref INTEGER, created TEXT);
            CREATE TABLE IF NOT EXISTS refs(ref INTEGER, uid INTEGER UNIQUE, created TEXT);
            CREATE TABLE IF NOT EXISTS media(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, ch TEXT, stats TEXT, contact TEXT, status TEXT, created TEXT);
            CREATE TABLE IF NOT EXISTS invites(link TEXT PRIMARY KEY, owner INTEGER);
            CREATE TABLE IF NOT EXISTS joins(owner INTEGER, uid INTEGER UNIQUE, created TEXT);
            CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE IF NOT EXISTS admins(uid INTEGER PRIMARY KEY, added_by INTEGER, created TEXT);
            """)
            owners=[int(x) for x in os.getenv("ADMIN_IDS","").replace(" ","").split(",") if x]
            for uid in owners:
                c.execute("INSERT OR IGNORE INTO admins(uid,added_by,created) VALUES(?,?,?)",
                          (uid,uid,datetime.now(timezone.utc).isoformat()))

    def user(self, uid):
        with self.con() as c:
            r=c.execute("SELECT * FROM users WHERE uid=?", (uid,)).fetchone()
            return dict(r) if r else None

    def nick_exists(self, n):
        with self.con() as c:
            return c.execute("SELECT 1 FROM users WHERE lower(nick)=lower(?)", (n,)).fetchone() is not None

    def add_user(self, uid, un, n, pw, ref):
        with self.con() as c:
            c.execute("INSERT INTO users VALUES(?,?,?,?,?,?)",
                      (uid,un,n,pw,ref,datetime.now(timezone.utc).isoformat()))

    def add_ref(self, r, u):
        with self.con() as c:
            c.execute("INSERT OR IGNORE INTO refs VALUES(?,?,?)",
                      (r,u,datetime.now(timezone.utc).isoformat()))

    def ref_count(self, u):
        with self.con() as c:
            return c.execute("SELECT count(*) FROM refs WHERE ref=?", (u,)).fetchone()[0]

    def top(self):
        with self.con() as c:
            return [dict(x) for x in c.execute(
                "SELECT users.nick AS nick,count(refs.uid) AS n FROM users LEFT JOIN refs ON refs.ref=users.uid GROUP BY users.uid ORDER BY n DESC LIMIT 10")]

    def save_invite(self, l, o):
        with self.con() as c:
            c.execute("INSERT OR REPLACE INTO invites VALUES(?,?)",(l,o))

    def invite_owner(self, l):
        with self.con() as c:
            r=c.execute("SELECT owner FROM invites WHERE link=?", (l,)).fetchone()
            return r[0] if r else None

    def add_channel_join(self, o, u):
        with self.con() as c:
            x=c.execute("INSERT OR IGNORE INTO joins VALUES(?,?,?)",
                        (o,u,datetime.now(timezone.utc).isoformat()))
            return x.rowcount > 0

    def channel_count(self, o):
        with self.con() as c:
            return c.execute("SELECT count(*) FROM joins WHERE owner=?", (o,)).fetchone()[0]

    def media(self, u, ch, st, co):
        with self.con() as c:
            x=c.execute("INSERT INTO media(uid,ch,stats,contact,status,created) VALUES(?,?,?,?,?,?)",
                        (u,ch,st,co,"pending",datetime.now(timezone.utc).isoformat()))
            return x.lastrowid

    def media_get(self, i):
        with self.con() as c:
            r=c.execute("SELECT * FROM media WHERE id=?", (i,)).fetchone()
            return dict(r) if r else None

    def media_status(self, i, s):
        with self.con() as c:
            c.execute("UPDATE media SET status=? WHERE id=?", (s,i))

    def users_total(self):
        with self.con() as c:
            return c.execute("SELECT count(*) FROM users").fetchone()[0]

    def refs_total(self):
        with self.con() as c:
            return c.execute("SELECT count(*) FROM refs").fetchone()[0]

    def media_total(self):
        with self.con() as c:
            return c.execute("SELECT count(*) FROM media").fetchone()[0]

    def user_ids(self):
        with self.con() as c:
            return [x[0] for x in c.execute("SELECT uid FROM users")]

    def set_setting(self, k, v):
        with self.con() as c:
            c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k,v))

    def setting(self, k, default=None):
        with self.con() as c:
            r=c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
            return r[0] if r else default

    def admin_ids(self):
        with self.con() as c:
            return [r[0] for r in c.execute("SELECT uid FROM admins")]

    def is_admin(self, uid):
        with self.con() as c:
            return c.execute("SELECT 1 FROM admins WHERE uid=?", (uid,)).fetchone() is not None

    def add_admin(self, uid, by):
        with self.con() as c:
            cur=c.execute("INSERT OR IGNORE INTO admins(uid,added_by,created) VALUES(?,?,?)",
                          (uid,by,datetime.now(timezone.utc).isoformat()))
            return cur.rowcount > 0

    def remove_admin(self, uid):
        with self.con() as c:
            cur=c.execute("DELETE FROM admins WHERE uid=?", (uid,))
            return cur.rowcount > 0
