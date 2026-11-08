"""FENIX ONLINE wallet, donations, Robokassa and FNZ shop."""
import hashlib
import hmac
import json
import os
from urllib.parse import urlencode

PRODUCTS = [
 {"code":"bmw_m3","name":"BMW M3","description":"Спортивный BMW для городских поездок и тюнинга.","rarity":"Эпический","price":None,"image":""},
 {"code":"cybertruck","name":"Cybertruck","description":"Необычный премиальный автомобиль из каталога FENIX ONLINE.","rarity":"Легендарный","price":690,"image":""},
 {"code":"audi_tt","name":"Audi TT","description":"Компактное спортивное купе для города и тюнинга.","rarity":"Эпический","price":490,"image":"https://nemazing.com/assets/img/store-v108/audi-tt.png"},
 {"code":"lancer_evo","name":"Mitsubishi Lancer Evolution","description":"Спортивный седан для динамичной езды и доработок.","rarity":"Эпический","price":290,"image":"https://nemazing.com/assets/img/store-v108/lancer-evolution.png"},
 {"code":"stage3_chip","name":"Чип тюнинга III","description":"Продвинутый чип третьего уровня для тюнинга автомобиля.","rarity":"Легендарный","price":None,"image":"https://nemazing.com/assets/img/store-v108/chip-stage-3.png"},
 {"code":"drift_smoke","name":"Дрифт-дым","description":"Визуальный дымовой эффект для эффектного дрифта.","rarity":"Легендарный","price":790,"image":""},
 {"code":"audio_system","name":"Аудиосистема","description":"Автомобильная аудиосистема с функциями проекта.","rarity":"Легендарный","price":890,"image":"https://nemazing.com/assets/img/store-v108/audio-system.png"},
 {"code":"nitro","name":"Нитро","description":"Комплект системы закиси азота.","rarity":"Редкий","price":390,"image":"https://nemazing.com/assets/img/store-v108/nitro.png"},
 {"code":"neon","name":"Неоновая подсветка","description":"Подсветка днища с настройкой внутри игры.","rarity":"Редкий","price":490,"image":"https://nemazing.com/assets/img/store-v108/neon.png"},
 {"code":"military_id","name":"Военный билет","description":"Покупается один раз и навсегда закрепляется за аккаунтом.","rarity":"Особый","price":None,"image":""},
]
PLATE_LETTERS = "АВЕКМНОРСТУХ"
REGIONS = ["01","02","03","04","05","06","07","08","09","10","11","12","13","14","15","16","17","18","19","20","21","22","23","24","25","26","27","28","29","30","31","32","33","34","35","36","37","38","39","40","41","42","43","44","45","46","47","48","49","50","51","52","53","54","55","56","57","58","59","60","61","62","63","64","65","66","67","68","69","70","71","72","73","74","75","76","77","78","79","80","81","82","83","84","85","86","87","88","89","90","91","92","93","94","95","96","97","98","99"]

def init(db):
    with db.con() as c:
        if db.use_postgres:
            c.execute("CREATE TABLE IF NOT EXISTS wallets(uid BIGINT PRIMARY KEY,balance BIGINT NOT NULL DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS wallet_ledger(id BIGSERIAL PRIMARY KEY,uid BIGINT NOT NULL,delta BIGINT NOT NULL,reason TEXT,ref_key TEXT UNIQUE,actor BIGINT,created TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS donations(id BIGSERIAL PRIMARY KEY,uid BIGINT NOT NULL,rub_amount NUMERIC(12,2) NOT NULL,fnz_amount BIGINT NOT NULL,method TEXT NOT NULL,status TEXT NOT NULL,proof TEXT,invoice_id TEXT UNIQUE,created TEXT,reviewed_by BIGINT,review_note TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS shop_orders(id BIGSERIAL PRIMARY KEY,uid BIGINT NOT NULL,nick TEXT NOT NULL,product_code TEXT NOT NULL,product_name TEXT NOT NULL,price_fnz BIGINT NOT NULL,status TEXT NOT NULL,details TEXT,created TEXT,updated TEXT,reviewed_by BIGINT,review_note TEXT)")
        else:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS wallets(uid INTEGER PRIMARY KEY,balance INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS wallet_ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,uid INTEGER NOT NULL,delta INTEGER NOT NULL,reason TEXT,ref_key TEXT UNIQUE,actor INTEGER,created TEXT);
            CREATE TABLE IF NOT EXISTS donations(id INTEGER PRIMARY KEY AUTOINCREMENT,uid INTEGER NOT NULL,rub_amount REAL NOT NULL,fnz_amount INTEGER NOT NULL,method TEXT NOT NULL,status TEXT NOT NULL,proof TEXT,invoice_id TEXT UNIQUE,created TEXT,reviewed_by INTEGER,review_note TEXT);
            CREATE TABLE IF NOT EXISTS shop_orders(id INTEGER PRIMARY KEY AUTOINCREMENT,uid INTEGER NOT NULL,nick TEXT NOT NULL,product_code TEXT NOT NULL,product_name TEXT NOT NULL,price_fnz INTEGER NOT NULL,status TEXT NOT NULL,details TEXT,created TEXT,updated TEXT,reviewed_by INTEGER,review_note TEXT);
            """)

def balance(db, uid):
    row=db._one(f"SELECT balance FROM wallets WHERE uid={db._ph()}",(uid,))
    return int(row["balance"]) if row else 0

def history(db, uid, limit=25):
    return db._all(f"SELECT delta,reason,created FROM wallet_ledger WHERE uid={db._ph()} ORDER BY id DESC LIMIT {int(limit)}",(uid,))

def new_donation(db, uid, rub, fnz, method, proof=""):
    with db.con() as c:
        values=(uid,rub,fnz,method,"pending",proof,db._now())
        if db.use_postgres:
            row=c.execute("INSERT INTO donations(uid,rub_amount,fnz_amount,method,status,proof,created) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id",values).fetchone()
            did=int(row["id"])
        else:
            cur=c.execute("INSERT INTO donations(uid,rub_amount,fnz_amount,method,status,proof,created) VALUES(?,?,?,?,?,?,?)",values)
            did=int(cur.lastrowid)
        c.execute(f"UPDATE donations SET invoice_id={db._ph()} WHERE id={db._ph()}",(str(did),did))
        return did

def donation_by_invoice(db, inv):
    return db._one(f"SELECT * FROM donations WHERE invoice_id={db._ph()}",(str(inv),))

def donations(db, status="pending", limit=100):
    if status=="all":
        return db._all(f"SELECT d.*,u.nick FROM donations d LEFT JOIN users u ON u.uid=d.uid ORDER BY d.id DESC LIMIT {int(limit)}")
    return db._all(f"SELECT d.*,u.nick FROM donations d LEFT JOIN users u ON u.uid=d.uid WHERE d.status={db._ph()} ORDER BY d.id DESC LIMIT {int(limit)}",(status,))

def credit(db, uid, amount, reason, ref, actor=None):
    amount=int(amount)
    if amount<=0: return False
    with db.con() as c:
        if db.use_postgres:
            row=c.execute("INSERT INTO wallet_ledger(uid,delta,reason,ref_key,actor,created) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(ref_key) DO NOTHING RETURNING id",(uid,amount,reason,ref,actor,db._now())).fetchone()
            if not row:return False
            c.execute("INSERT INTO wallets(uid,balance) VALUES(%s,%s) ON CONFLICT(uid) DO UPDATE SET balance=wallets.balance+EXCLUDED.balance",(uid,amount))
        else:
            cur=c.execute("INSERT OR IGNORE INTO wallet_ledger(uid,delta,reason,ref_key,actor,created) VALUES(?,?,?,?,?,?)",(uid,amount,reason,ref,actor,db._now()))
            if not cur.rowcount:return False
            c.execute("INSERT INTO wallets(uid,balance) VALUES(?,?) ON CONFLICT(uid) DO UPDATE SET balance=balance+excluded.balance",(uid,amount))
    return True

def mark_paid(db, donation_id, actor=None, note=""):
    with db.con() as c:
        row=c.execute(f"SELECT * FROM donations WHERE id={db._ph()}",(donation_id,)).fetchone()
        if not row:return False
        d=dict(row)
        if d["status"]!="pending":return False
        cur=c.execute(f"UPDATE donations SET status='paid',reviewed_by={db._ph()},review_note={db._ph()} WHERE id={db._ph()} AND status='pending'",(actor,note,donation_id))
        if cur.rowcount!=1:return False
        uid,amount=int(d["uid"]),int(d["fnz_amount"])
        ref=f"donation:{donation_id}"
        if db.use_postgres:
            inserted=c.execute("INSERT INTO wallet_ledger(uid,delta,reason,ref_key,actor,created) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(ref_key) DO NOTHING RETURNING id",(uid,amount,"Пополнение кошелька",ref,actor,db._now())).fetchone()
            if inserted:c.execute("INSERT INTO wallets(uid,balance) VALUES(%s,%s) ON CONFLICT(uid) DO UPDATE SET balance=wallets.balance+EXCLUDED.balance",(uid,amount))
        else:
            inserted=c.execute("INSERT OR IGNORE INTO wallet_ledger(uid,delta,reason,ref_key,actor,created) VALUES(?,?,?,?,?,?)",(uid,amount,"Пополнение кошелька",ref,actor,db._now()))
            if inserted.rowcount:c.execute("INSERT INTO wallets(uid,balance) VALUES(?,?) ON CONFLICT(uid) DO UPDATE SET balance=balance+excluded.balance",(uid,amount))
    return True

def reject_donation(db, donation_id, actor, note=""):
    with db.con() as c:
        cur=c.execute(f"UPDATE donations SET status='rejected',reviewed_by={db._ph()},review_note={db._ph()} WHERE id={db._ph()} AND status='pending'",(actor,note,donation_id))
        return cur.rowcount==1

def create_order(db, uid, nick, code, name, price, details=""):
    with db.con() as c:
        if db.use_postgres: row=c.execute("SELECT balance FROM wallets WHERE uid=%s FOR UPDATE",(uid,)).fetchone()
        else: row=c.execute("SELECT balance FROM wallets WHERE uid=?",(uid,)).fetchone()
        if not row or int(row["balance"])<int(price):return None
        now=db._now()
        if db.use_postgres:
            cur=c.execute("INSERT INTO shop_orders(uid,nick,product_code,product_name,price_fnz,status,details,created,updated) VALUES(%s,%s,%s,%s,%s,'pending_delivery',%s,%s,%s) RETURNING id",(uid,nick,code,name,price,details,now,now))
            oid=int(cur.fetchone()["id"])
            c.execute("INSERT INTO wallet_ledger(uid,delta,reason,ref_key,created) VALUES(%s,%s,%s,%s,%s)",(uid,-int(price),f"Покупка: {name}",f"shop:{oid}",now))
            c.execute("UPDATE wallets SET balance=balance-%s WHERE uid=%s",(price,uid))
        else:
            cur=c.execute("INSERT INTO shop_orders(uid,nick,product_code,product_name,price_fnz,status,details,created,updated) VALUES(?,?,?,?,?,'pending_delivery',?,?,?)",(uid,nick,code,name,price,details,now,now))
            oid=int(cur.lastrowid)
            c.execute("INSERT INTO wallet_ledger(uid,delta,reason,ref_key,created) VALUES(?,?,?,?,?)",(uid,-int(price),f"Покупка: {name}",f"shop:{oid}",now))
            c.execute("UPDATE wallets SET balance=balance-? WHERE uid=?",(price,uid))
    return oid

def list_orders(db, uid=None, status="all", limit=100):
    where=[];params=[]
    if uid is not None:where.append(f"o.uid={db._ph()}");params.append(uid)
    if status!="all":where.append(f"o.status={db._ph()}");params.append(status)
    clause=(" WHERE "+" AND ".join(where)) if where else ""
    return db._all(f"SELECT o.*,u.username FROM shop_orders o LEFT JOIN users u ON u.uid=o.uid{clause} ORDER BY o.id DESC LIMIT {int(limit)}",tuple(params))

def update_order(db, order_id, status, actor, note=""):
    if status not in {"processing","delivered"}:return False
    with db.con() as c:
        cur=c.execute(f"UPDATE shop_orders SET status={db._ph()},reviewed_by={db._ph()},review_note={db._ph()},updated={db._ph()} WHERE id={db._ph()} AND status IN ('pending_delivery','processing')",(status,actor,note,db._now(),order_id))
        return cur.rowcount==1

def robokassa_url(db, donation_id, base_url):
    d=db._one(f"SELECT * FROM donations WHERE id={db._ph()}",(donation_id,))
    login=os.getenv("ROBOKASSA_MERCHANT_LOGIN","").strip()
    password=os.getenv("ROBOKASSA_PASSWORD1","").strip()
    if not d or not login or not password:return None
    amount=f"{float(d['rub_amount']):.2f}"
    raw=f"{login}:{amount}:{d['invoice_id']}:{password}"
    algo=os.getenv("ROBOKASSA_HASH_ALGORITHM","md5").lower()
    signature=hashlib.new(algo,raw.encode()).hexdigest()
    params={"MerchantLogin":login,"OutSum":amount,"InvId":str(d["invoice_id"]),"Description":f"FENIX ONLINE · пополнение #{donation_id}","SignatureValue":signature,"Culture":"ru","Encoding":"utf-8","Shp_uid":str(d["uid"])}
    if os.getenv("ROBOKASSA_TEST_MODE","0").lower() in {"1","true","yes"}:params["IsTest"]="1"
    return "https://auth.robokassa.ru/Merchant/Index.aspx?"+urlencode(params)

def verify_result(db, params):
    password=os.getenv("ROBOKASSA_PASSWORD2","").strip()
    if not password:return None
    inv=str(params.get("InvId",""))
    d=donation_by_invoice(db,inv)
    if not d:return None
    amount=str(params.get("OutSum",""))
    try:
        if round(float(amount),2)!=round(float(d["rub_amount"]),2):return None
    except Exception:return None
    extra=[]
    for k in sorted(k for k in params if k.startswith("Shp_")):
        extra.append(f"{k}={params[k]}")
    raw=":".join([amount,inv,password]+extra)
    algo=os.getenv("ROBOKASSA_HASH_ALGORITHM","md5").lower()
    expected=hashlib.new(algo,raw.encode()).hexdigest().upper()
    if not hmac.compare_digest(expected,str(params.get("SignatureValue","")).upper()):return None
    return d
