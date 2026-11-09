import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
import secrets
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram.types import MenuButtonCommands, MenuButtonWebApp, WebAppInfo, InlineKeyboardButton
import bot as core
import store as shop

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("fenix-miniapp")
db, tg = core.db, core.bot
ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "webapp"
TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
AUTH_MAX_AGE = int(os.getenv("WEBAPP_AUTH_MAX_AGE", "86400"))


def response(data=None, status=200):
    return web.json_response({"ok": status < 400, "data": data} if status < 400 else {"ok": False, "error": data}, status=status)


def verify_init_data(raw):
    if not TOKEN or not raw:
        return None
    try:
        pairs = dict(parse_qsl(raw, keep_blank_values=True))
        received = pairs.pop("hash", "")
        if not received:
            return None
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        actual = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(actual, received):
            return None
        auth_date = int(pairs.get("auth_date", "0"))
        now = time.time()
        if auth_date <= 0 or now - auth_date > AUTH_MAX_AGE or auth_date > now + 60:
            return None
        user = json.loads(pairs.get("user", "{}"))
        return user if user.get("id") else None
    except Exception:
        log.exception("initData validation failed")
        return None


def verify_login_widget(data):
    try:
        received=str(data.get("hash",""))
        if not received:return None
        pairs={str(k):str(v) for k,v in data.items() if k!="hash"}
        check="\n".join(f"{k}={v}" for k,v in sorted(pairs.items()))
        secret=hashlib.sha256(TOKEN.encode()).digest()
        actual=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(actual,received):return None
        auth_date=int(pairs.get("auth_date","0"))
        if auth_date<=0 or time.time()-auth_date>86400 or auth_date>time.time()+60:return None
        user_id=int(pairs.get("id","0"))
        return {"id":user_id,"username":pairs.get("username"),"first_name":pairs.get("first_name"),"last_name":pairs.get("last_name"),"photo_url":pairs.get("photo_url")}
    except Exception:
        return None


def make_session(uid_value):
    expires=int(time.time())+60*60*24*30
    body=f"{int(uid_value)}.{expires}"
    secret=hashlib.sha256(TOKEN.encode()).digest()
    sig=hmac.new(secret,body.encode(),hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_session(value):
    try:
        uid_value,expires,sig=value.split(".",2)
        body=f"{uid_value}.{expires}"
        secret=hashlib.sha256(TOKEN.encode()).digest()
        expected=hmac.new(secret,body.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,sig) or int(expires)<time.time():return None
        return int(uid_value)
    except Exception:
        return None


@web.middleware
async def auth(request, handler):
    if request.path.startswith("/api/") and request.path!="/api/auth/telegram":
        user=verify_init_data(request.headers.get("X-Telegram-Init-Data",""))
        if not user:
            session_uid=read_session(request.cookies.get("fenix_session",""))
            if session_uid:user={"id":session_uid}
        if not user:
            return response("Требуется вход через Telegram.",401)
        request["tg_user"]=user
        if not db.user(int(user["id"])):
            return response("Сначала запусти бота командой /start и заверши регистрацию.",403)
    return await handler(request)


async def login_telegram(req):
    data=await payload(req)
    user=verify_login_widget(data)
    if not user:return response("Telegram не подтвердил вход. Проверь домен бота и попробуй ещё раз.",401)
    if not db.user(int(user["id"])):return response("Сначала зарегистрируйся в боте FENIX ONLINE через /start.",403)
    res=response({"profile":user})
    res.set_cookie("fenix_session",make_session(user["id"]),httponly=True,secure=True,samesite="Lax",max_age=60*60*24*30,path="/")
    return res


async def logout(req):
    res=response({"logged_out":True})
    res.del_cookie("fenix_session",path="/")
    return res


def uid(req):
    return int(req["tg_user"]["id"])


def admin(req):
    return db.is_admin(uid(req))


async def payload(req):
    try:
        return await req.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON")


async def home(_):
    return web.FileResponse(WEB_DIR / "index.html")


async def serve_asset(request):
    # Explicit one-file handler keeps product images working even when the
    # hosting proxy handles the directory static mount differently.
    name = request.match_info["filename"]
    if name in (".", "..") or Path(name).name != name:
        raise web.HTTPNotFound()
    path = ROOT / "assets" / name
    if not path.is_file():
        log.warning("Asset not found: %s (ROOT=%s)", name, ROOT)
        raise web.HTTPNotFound(text="Asset not found")
    return web.FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


async def bootstrap(req):
    user_id = uid(req)
    user = db.user(user_id)
    tickets = db.tickets_for_user(user_id, 100)
    awards = db.achievements_for_user(user_id)
    media = db.media_current(user_id) or {}
    me = req["tg_user"]
    bot_info = await tg.get_me()
    return response({
        "profile": {"id": user_id, "nick": user.get("nick"), "username": me.get("username"), "first_name": me.get("first_name"), "photo_url": me.get("photo_url")},
        "admin": admin(req),
        "stats": {"referrals": db.ref_count(user_id), "channel_joins": db.channel_count(user_id), "tickets": len(tickets), "open_tickets": sum(1 for t in tickets if t.get("status") in ("open", "answered")), "notifications": db.unread_notifications(user_id), "achievements": len(awards)},
        "media_status": media.get("status", "none"),
        "referral_link": f"https://t.me/{bot_info.username}?start=r{user_id}",
        "channel_url": core.CHANNEL_URL or core.REQUIRED_CHANNEL_URL,
        "theme": read_json_setting("ui_theme", DEFAULT_THEME)
    })


async def stats(req):
    user_id = uid(req)
    return response({"referrals": db.ref_count(user_id), "channel_joins": db.channel_count(user_id)})


async def top(_):
    return response(db.top())


async def tickets(req):
    return response(db.tickets_for_user(uid(req), 50))


async def ticket_create(req):
    user_id = uid(req)
    data = await payload(req)
    subject, text = str(data.get("subject", "")).strip()[:100], str(data.get("body", "")).strip()[:4000]
    if len(subject) < 3 or len(text) < 5:
        return response("Заполни тему и сообщение (минимум 5 символов).", 400)
    ticket_id = db.create_ticket(user_id, subject, text)
    for admin_id in db.admin_ids():
        try:
            await tg.send_message(admin_id, f"🎫 Новое обращение #{ticket_id}\nОт: {user_id}\nТема: {subject}")
        except Exception:
            log.exception("Ticket notification failed")
    return response({"id": ticket_id})


async def ticket_detail(req):
    user_id, ticket_id = uid(req), int(req.match_info["ticket_id"])
    item = db.ticket_get(ticket_id)
    if not item or (int(item["uid"]) != user_id and not admin(req)):
        return response("Обращение не найдено.", 404)
    return response({"ticket": item, "messages": db.ticket_messages(ticket_id)})


async def ticket_reply(req):
    user_id, ticket_id = uid(req), int(req.match_info["ticket_id"])
    item = db.ticket_get(ticket_id)
    if not item or (int(item["uid"]) != user_id and not admin(req)):
        return response("Обращение не найдено.", 404)
    data = await payload(req)
    text = str(data.get("body", "")).strip()[:4000]
    if len(text) < 2:
        return response("Сообщение слишком короткое.", 400)
    db.ticket_reply(ticket_id, user_id, text)
    if admin(req):
        db.ticket_set_status(ticket_id, "answered")
        target = int(item["uid"])
    else:
        admins = db.admin_ids()
        target = int(admins[0]) if admins else None
    if target:
        try:
            await tg.send_message(target, f"💬 Ответ по обращению #{ticket_id}:\n{text[:1200]}")
        except Exception:
            log.exception("Ticket reply notification failed")
    return response({"sent": True})


async def ticket_close(req):
    user_id, ticket_id = uid(req), int(req.match_info["ticket_id"])
    item = db.ticket_get(ticket_id)
    if not item or (int(item["uid"]) != user_id and not admin(req)):
        return response("Обращение не найдено.", 404)
    db.ticket_set_status(ticket_id, "closed")
    return response({"closed": True})


async def notifications(req):
    user_id = uid(req)
    if req.method == "POST":
        db.mark_notifications_read(user_id)
        return response({"read": True})
    return response(db.notifications_for_user(user_id, 50))


async def achievements(req):
    return response(db.achievements_for_user(uid(req)))


async def media_info(req):
    user_id = uid(req)
    current = db.media_current(user_id) or {}
    return response({
        "application": current, "status": current.get("status", "none"),
        "active_days": min(db.media_active_days(user_id), 7),
        "total_views": db.media_video_views_total(user_id),
        "videos": db.media_video_stats_for_user(user_id, 20),
        "payouts": db.media_payouts_for_user(user_id, 20),
        "can_apply": not current or current.get("status") == "rejected"
    })


async def media_apply(req):
    user_id = uid(req)
    current = db.media_current(user_id)
    if current and current.get("status") in ("pending", "approved"):
        return response("У тебя уже есть активная заявка или статус партнёра.", 409)
    data = await payload(req)
    channel = str(data.get("channel", "")).strip()[:500]
    audience = str(data.get("audience", "")).strip()[:1000]
    contact = str(data.get("contact", "")).strip()[:300]
    if not channel.startswith(("https://", "http://")) or len(audience) < 3 or len(contact) < 3:
        return response("Проверь ссылку на канал, описание аудитории и контакт.", 400)
    app_id = db.media(user_id, channel, audience, contact)
    for admin_id in db.admin_ids():
        try:
            await tg.send_message(admin_id, f"🤝 Новая заявка медиапартнёра #{app_id}\nID: {user_id}\nКанал: {channel}")
        except Exception:
            log.exception("Media application notification failed")
    return response({"id": app_id})


async def media_video(req):
    user_id = uid(req)
    current = db.media_current(user_id)
    if not current or current.get("status") != "approved":
        return response("Раздел доступен только одобренным медиапартнёрам.", 403)
    data = await payload(req)
    url = str(data.get("url", "")).strip()[:1000]
    if not url.startswith(("https://", "http://")):
        return response("Нужна ссылка на опубликованное видео.", 400)
    added = db.media_add_day(user_id, url)
    return response({"added": added, "active_days": min(db.media_active_days(user_id), 7)})


async def media_payout(req):
    user_id = uid(req)
    eligible, reason = core.payout_eligible(user_id)
    if not eligible:
        return response(reason, 400)
    data = await payload(req)
    channel = str(data.get("channel", "")).strip()[:500]
    video = str(data.get("video", "")).strip()[:1000]
    requisites = str(data.get("requisites", "")).strip()[:1000]
    if not channel.startswith(("https://", "http://")) or not video.startswith(("https://", "http://")) or len(requisites) < 5:
        return response("Заполни ссылки на канал и видео, а также реквизиты.", 400)
    payout_id = db.media_payout(user_id, "На рассмотрении", requisites)
    db.media_payout_evidence(payout_id, channel, video)
    for admin_id in db.admin_ids():
        try:
            await tg.send_message(admin_id, f"💸 Новая заявка на выплату #{payout_id}. ID игрока: {user_id}.")
        except Exception:
            log.exception("Payout notification failed")
    return response({"id": payout_id})


async def admin_overview(req):
    if not admin(req):
        return response("Недостаточно прав.", 403)
    return response({"users": db.users_total(), "referrals": db.refs_total(), "media_applications": db.media_total(), "open_tickets": len(db.open_tickets(1000)), "pending_payouts": len(db.media_pending_payouts())})


async def admin_tickets(req):
    if not admin(req):
        return response("Недостаточно прав.", 403)
    rows = db.open_tickets(100)
    for row in rows:
        user = db.user(row["uid"]) or {}
        row["nick"] = user.get("nick", str(row["uid"]))
    return response(rows)


async def admin_apps(req):
    if not admin(req):
        return response("Недостаточно прав.", 403)
    ph = db._ph()
    return response(db._all(f"SELECT m.*,u.nick FROM media m LEFT JOIN users u ON u.uid=m.uid WHERE m.status={ph} ORDER BY m.id DESC LIMIT 100", ("pending",)))


async def admin_app_decision(req):
    if not admin(req):
        return response("Недостаточно прав.", 403)
    app_id = int(req.match_info["application_id"])
    item = db.media_get(app_id)
    if not item or item.get("status") != "pending":
        return response("Заявка уже обработана.", 409)
    data = await payload(req)
    decision = str(data.get("decision", ""))
    if decision not in ("approved", "rejected"):
        return response("Неизвестное решение.", 400)
    db.media_status(app_id, decision)
    note = str(data.get("note", "")).strip()[:700] or ("Тебе открыт кабинет медиапартнёра." if decision == "approved" else "Администрация рассмотрела заявку.")
    title = "Заявка в медиапартнёры одобрена" if decision == "approved" else "Заявка в медиапартнёры отклонена"
    db.add_notification(item["uid"], title, note)
    try:
        await tg.send_message(item["uid"], title + "\n" + note)
    except Exception:
        log.exception("Applicant notification failed")
    return response({"status": decision})


async def admin_payouts(req):
    if not admin(req):
        return response("Недостаточно прав.", 403)
    rows = db._all("SELECT p.*,u.nick FROM media_payouts p LEFT JOIN users u ON u.uid=p.uid ORDER BY p.id DESC LIMIT 100")
    for row in rows:
        row["evidence"] = db.media_payout_evidence_get(row["id"])
    return response(rows)


async def admin_payout_decision(req):
    if not admin(req):
        return response("Недостаточно прав.", 403)
    payout_id = int(req.match_info["payout_id"])
    item = db.media_payout_get(payout_id)
    if not item:
        return response("Заявка не найдена.", 404)
    data = await payload(req)
    decision = str(data.get("decision", ""))
    note = str(data.get("note", "")).strip()[:1500]
    if decision == "paid" and item["status"] == "approved":
        db.media_payout_review(payout_id, "paid", uid(req), item.get("review_note") or "")
        message = f"Выплата #{payout_id} отправлена. Сумма: {item.get('amount')}"
    elif decision == "approved" and item["status"] == "pending":
        try:
            amount = float(str(data.get("amount", "")).replace(",", "."))
            if amount < 0 or amount > 10000000:
                raise ValueError()
        except Exception:
            return response("Укажи корректную сумму в рублях.", 400)
        if not note:
            return response("Добавь комментарий к решению.", 400)
        value = f"{amount:.2f} RUB"
        db.media_payout_set_amount(payout_id, value)
        db.media_payout_review(payout_id, "approved", uid(req), note)
        message = f"Выплата #{payout_id} одобрена. Сумма: {value}. {note}"
    elif decision == "rejected" and item["status"] == "pending":
        if not note:
            return response("Укажи причину отказа.", 400)
        db.media_payout_review(payout_id, "rejected", uid(req), note)
        message = f"Выплата #{payout_id} отклонена. {note}"
    else:
        return response("Недопустимый переход статуса.", 409)
    db.add_notification(item["uid"], f"Обновление выплаты #{payout_id}", message)
    try:
        await tg.send_message(item["uid"], message)
    except Exception:
        log.exception("Payout user notification failed")
    return response({"status": decision})


async def admin_broadcast(req):
    if not admin(req):
        return response("Недостаточно прав.", 403)
    data = await payload(req)
    text = str(data.get("text", "")).strip()[:3500]
    if len(text) < 2:
        return response("Текст слишком короткий.", 400)
    asyncio.create_task(core._broadcast_worker({"text": text, "photo": None, "bt": None, "bu": None}, uid(req)))
    return response({"queued": True})


async def admin_publish(req):
    if not admin(req):
        return response("Недостаточно прав.", 403)
    if not core.CHANNEL:
        return response("CHANNEL_ID не настроен.", 400)
    data = await payload(req)
    text = str(data.get("text", "")).strip()[:3500]
    label = str(data.get("button_label", "")).strip()[:64]
    url = str(data.get("button_url", "")).strip()
    if len(text) < 2:
        return response("Текст публикации слишком короткий.", 400)
    if bool(label) != bool(url) or (url and not url.startswith(("https://", "http://"))):
        return response("Для URL-кнопки заполни оба поля.", 400)
    await core.send_composed(core.CHANNEL, {"text": text, "photo": None, "bt": label or None, "bu": url or None})
    return response({"published": True})



# --- FENIX FNZ store / donations ---
def store_prices():
    return read_json_setting("store_prices", {})

def fnz_rate():
    try:
        value=float(db.setting("fnz_per_rub","2") or 2)
        if value <= 0: value = 2
        return value if 0 < value <= 100000 else 0
    except Exception:
        return 0

def catalog():
    overrides=store_prices()
    rows=[]
    for p in shop.PRODUCTS:
        item=dict(p)
        if item["code"] in overrides:
            try:item["price"]=max(1,int(overrides[item["code"]]))
            except Exception:pass
        rows.append(item)
    return rows

async def shop_home(req):
    user_id=uid(req)
    return response({
        "products":catalog(),
        "balance":shop.balance(db,user_id),
        "history":shop.history(db,user_id,20),
        "orders":shop.list_orders(db,uid=user_id,limit=30),
        "donations":[dict(x, rub_amount=float(x["rub_amount"])) for x in db._all(f"SELECT id,rub_amount,fnz_amount,method,status,created FROM donations WHERE uid={db._ph()} ORDER BY id DESC LIMIT 20",(user_id,))],
        "fnz_per_rub":fnz_rate(),
        "manual_phone":"+79067853860",
        "manual_banks":["Сбербанк","Т-Банк"],
        "robokassa_enabled":False,
        "server":{"name":"BLACK","address":"185.207.214.14","port":4357}
    })

async def shop_buy(req):
    user_id=uid(req)
    data=await payload(req)
    code=str(data.get("code",""))[:48]
    item=next((p for p in catalog() if p["code"]==code),None)
    if not item:return response("Товар не найден.",404)
    if item["price"] is None:return response("Цена этого товара ещё не установлена. Напиши администрации.",409)
    details=data.get("details") or {}
    if not isinstance(details,dict):return response("Неверные параметры товара.",400)
    nick=(db.user(user_id) or {}).get("nick") or ""
    if not nick:return response("Сначала привяжи игровой ник.",400)
    price=int(item["price"]);product_name=item["name"]
    if code=="vehicle_plate":
        country=str(details.get("country","Россия"))
        letters=str(details.get("letters","")).upper()
        digits=str(details.get("digits",""))
        region=str(details.get("region",""))
        if country not in {"Россия","Казахстан","Беларусь","Украина","Грузия"}:
            return response("Выбери страну из списка.",400)
        if len(letters)!=3 or any(x not in shop.PLATE_LETTERS for x in letters):
            return response("Укажи ровно 3 латинские буквы A–Z.",400)
        if len(digits)!=3 or not digits.isdigit() or region not in shop.REGIONS:
            return response("Укажи 3 цифры и выбери регион.",400)
        price=700
        plate=f"{letters} {digits} {region}"
        product_name=f"Автомобильный номер {plate} · {country}"
        details={"country":country,"plate":plate,"letters":letters,"digits":digits,"region":region}
        try:
            with db.con() as conn:
                conn.execute(f"INSERT INTO vehicle_plates(plate,uid,country,created) VALUES({db._ph()},{db._ph()},{db._ph()},{db._ph()})",(plate,user_id,country,db._now()))
        except Exception:
            return response("Этот автомобильный номер уже занят. Выбери другую комбинацию.",409)
    order_id=shop.create_order(db,user_id,nick,code,product_name,price,json.dumps(details,ensure_ascii=False)[:1500])
    if not order_id:
        if code=="vehicle_plate":
            db._execute(f"DELETE FROM vehicle_plates WHERE plate={db._ph()} AND uid={db._ph()}",(plate,user_id))
        return response("Недостаточно FNZ. Сначала пополни кошелёк.",409)
    msg=f"Покупка #{order_id} завершена. {product_name} добавлен в инвентарь. Стоимость: {price} FNZ. Запроси выдачу предмета в игре."
    db.add_notification(user_id,"Покупка оформлена",msg)
    return response({"id":order_id,"balance":shop.balance(db,user_id)})

async def audio_tracks(req):
    user_id=uid(req)
    scope=req.query.get("scope","public")
    if scope=="mine":
        rows=db._all("SELECT a.id,a.uid,a.title,a.artist,a.audio_url,a.visibility,a.created,u.nick FROM audio_tracks a LEFT JOIN users u ON u.uid=a.uid WHERE a.uid=? ORDER BY a.id DESC LIMIT 100" if not db.use_postgres else "SELECT a.id,a.uid,a.title,a.artist,a.audio_url,a.visibility,a.created,u.nick FROM audio_tracks a LEFT JOIN users u ON u.uid=a.uid WHERE a.uid=%s ORDER BY a.id DESC LIMIT 100",(user_id,))
    else:
        rows=db._all("SELECT a.id,a.uid,a.title,a.artist,a.audio_url,a.visibility,a.created,u.nick FROM audio_tracks a LEFT JOIN users u ON u.uid=a.uid WHERE a.visibility='public' ORDER BY a.id DESC LIMIT 100")
    return response({"tracks":[dict(x) for x in rows]})

async def audio_track_add(req):
    user_id=uid(req)
    if not db.user(user_id):
        return response("Сначала зарегистрируй игровой аккаунт.",403)
    data=await payload(req)
    title=str(data.get("title","")).strip()[:100]
    artist=str(data.get("artist","")).strip()[:100]
    url=str(data.get("url","")).strip()[:1000]
    visibility=str(data.get("visibility","private"))
    if len(title)<2:return response("Название должно содержать минимум 2 символа.",400)
    if not (url.startswith("https://") or url.startswith("http://")):return response("Укажи прямую HTTP(S)-ссылку на аудиофайл.",400)
    if visibility not in ("private","public"):visibility="private"
    ph=db._ph()
    if db.use_postgres:
        row=db._one("INSERT INTO audio_tracks(uid,title,artist,audio_url,visibility,created) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id",(user_id,title,artist,url,visibility,db._now()))
    else:
        cur=db._execute("INSERT INTO audio_tracks(uid,title,artist,audio_url,visibility,created) VALUES(?,?,?,?,?,?)",(user_id,title,artist,url,visibility,db._now()))
        row={"id":cur.lastrowid}
    return response({"id":row["id"]})

async def audio_track_delete(req):
    user_id=uid(req)
    track_id=int(req.match_info["track_id"])
    ph=db._ph()
    row=db._one(f"SELECT id FROM audio_tracks WHERE id={ph} AND uid={ph}",(track_id,user_id))
    if not row:return response("Запись не найдена.",404)
    db._execute(f"DELETE FROM audio_tracks WHERE id={ph} AND uid={ph}",(track_id,user_id))
    return response({"deleted":True})


# FENIX Wheel: 100 FNZ equals the requested 50 RUB at the current 1 RUB = 2 FNZ rate.
WHEEL_ITEMS = [p for p in shop.PRODUCTS if p.get("code") not in ("vehicle_plate",)]
_wheel_items_weight = 35.0 / max(1, len(WHEEL_ITEMS))
WHEEL_WEIGHTS = []
# Prizes now occupy 70% of the wheel; empty sectors are only 30%.
# Interleave every prize group so gifts appear all around the circumference.
for _i in range(max(7, len(WHEEL_ITEMS))):
    if _i < 6:
        WHEEL_WEIGHTS.append(("nothing", 5.0))
    if _i in (0, 2, 4, 6):
        WHEEL_WEIGHTS.append(("fnz500", 5.0))
    if _i in (1, 3, 5):
        WHEEL_WEIGHTS.append(("cash", 5.0))
    if _i < len(WHEEL_ITEMS):
        WHEEL_WEIGHTS.append((WHEEL_ITEMS[_i]["code"], _wheel_items_weight))

async def wheel_home(req):
    user_id=uid(req)
    return response({
        "cost_fnz":100,
        "cost_rub":50,
        "balance":shop.balance(db,user_id),
        "history":db._all(f"SELECT id,prize_type,prize_name,prize_value,created FROM wheel_spins WHERE uid={db._ph()} ORDER BY id DESC LIMIT 20",(user_id,)),
        "items":[{"code":p["code"],"name":p["name"],"image":{ "bmw_m3":"/assets/bmw-m3.png","cybertruck":"/assets/cybertruck.png","audi_tt":"/assets/audi-tt.png","lancer_evo":"/assets/lancer-evolution.png","stage3_chip":"/assets/chip-stage-3.png","drift_smoke":"/assets/drift-smoke.svg","audio_system":"/assets/audio-system.png","nitro":"/assets/nitro.png","neon":"/assets/neon.png","military_id":"/assets/military-id.png"}.get(p["code"],"/assets/vehicle-number.png"),"weight":round(_wheel_items_weight,3)} for p in WHEEL_ITEMS],
        "sectors":[
            {"code":code,"name":("Пусто" if code=="nothing" else "500 FNZ" if code=="fnz500" else "1–5 млн игровой валюты" if code=="cash" else next((p["name"] for p in WHEEL_ITEMS if p["code"]==code),"Приз")),
             "image":("/assets/prize-empty.svg" if code=="nothing" else "/assets/prize-fnz.svg" if code=="fnz500" else "/assets/prize-cash.svg" if code=="cash" else { "bmw_m3":"/assets/bmw-m3.png","cybertruck":"/assets/cybertruck.png","audi_tt":"/assets/audi-tt.png","lancer_evo":"/assets/lancer-evolution.png","stage3_chip":"/assets/chip-stage-3.png","drift_smoke":"/assets/drift-smoke.svg","audio_system":"/assets/audio-system.png","nitro":"/assets/nitro.png","neon":"/assets/neon.png","military_id":"/assets/military-id.png"}.get(code,"/assets/vehicle-number.png")),
             "type":("nothing" if code=="nothing" else "fnz" if code=="fnz500" else "game_cash" if code=="cash" else "item"),
             "weight":round(weight,3)}
            for code,weight in WHEEL_WEIGHTS
        ],
        "probabilities":{"nothing":30,"fnz500":20,"cash":15,"shop_items_total":35},"special_images":{"nothing":"/assets/prize-empty.svg","fnz500":"/assets/prize-fnz.svg","cash":"/assets/prize-cash.svg"}
    })

async def wheel_spin(req):
    user_id=uid(req)
    user=db.user(user_id)
    if not user:return response("Сначала зарегистрируй игровой аккаунт.",403)
    import random
    # Charge and reward are committed together; duplicate requests cannot spin for free.
    with db.con() as c:
        if db.use_postgres:
            row=c.execute("SELECT balance FROM wallets WHERE uid=%s FOR UPDATE",(user_id,)).fetchone()
        else:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT balance FROM wallets WHERE uid=?",(user_id,)).fetchone()
        if not row or int(row["balance"])<100:
            return response("Для вращения нужно 100 FNZ (эквивалент 50 ₽). Пополни баланс.",409)
        c.execute("UPDATE wallets SET balance=balance-100 WHERE uid="+db._ph(),(user_id,))
        now=db._now()
        prize=random.choices([x[0] for x in WHEEL_WEIGHTS],weights=[x[1] for x in WHEEL_WEIGHTS],k=1)[0]
        prize_type,prize_name,prize_value="nothing","Ничего",0
        if prize=="fnz500":
            prize_type,prize_name,prize_value="fnz","500 FNZ",500
            if db.use_postgres:
                c.execute("INSERT INTO wallet_ledger(uid,delta,reason,ref_key,created) VALUES(%s,%s,%s,%s,%s)",(user_id,500,"Выигрыш в колесе фортуны",f"wheel:{secrets.token_hex(16)}",now))
                c.execute("INSERT INTO wallets(uid,balance) VALUES(%s,%s) ON CONFLICT(uid) DO UPDATE SET balance=wallets.balance+EXCLUDED.balance",(user_id,500))
            else:
                c.execute("INSERT INTO wallet_ledger(uid,delta,reason,ref_key,created) VALUES(?,?,?,?,?)",(user_id,500,"Выигрыш в колесе фортуны",f"wheel:{secrets.token_hex(16)}",now))
                c.execute("UPDATE wallets SET balance=balance+500 WHERE uid=?",(user_id,))
        elif prize=="cash":
            prize_type,prize_value="game_cash",random.randint(1_000_000,5_000_000)
            prize_name=f"{prize_value:,} игровой валюты".replace(","," ")
        elif prize=="nothing":
            # Empty result is a valid outcome: charge the spin and save it,
            # but do not try to look it up as a shop product.
            pass
        else:
            item=next(p for p in WHEEL_ITEMS if p["code"]==prize)
            prize_type,prize_name,prize_value="item",item["name"],item["code"]
            details=json.dumps({"source":"wheel"},ensure_ascii=False)
            if db.use_postgres:
                c.execute("INSERT INTO shop_orders(uid,nick,product_code,product_name,price_fnz,status,details,created,updated) VALUES(%s,%s,%s,%s,0,'purchased',%s,%s,%s)",(user_id,user["nick"],prize,item["name"],details,now,now))
            else:
                c.execute("INSERT INTO shop_orders(uid,nick,product_code,product_name,price_fnz,status,details,created,updated) VALUES(?,?,?,?,0,'purchased',?,?,?)",(user_id,user["nick"],prize,item["name"],details,now,now))
        if db.use_postgres:
            saved=c.execute("INSERT INTO wheel_spins(uid,prize_type,prize_name,prize_value,created) VALUES(%s,%s,%s,%s,%s) RETURNING id",(user_id,prize_type,prize_name,str(prize_value),now)).fetchone()
            spin_id=int(saved["id"])
        else:
            saved=c.execute("INSERT INTO wheel_spins(uid,prize_type,prize_name,prize_value,created) VALUES(?,?,?,?,?)",(user_id,prize_type,prize_name,str(prize_value),now))
            spin_id=int(saved.lastrowid)
    return response({"id":spin_id,"prize_type":prize_type,"prize_name":prize_name,"prize_value":prize_value,"balance":shop.balance(db,user_id)})

async def wallet_payment_details(req):
    user_id=uid(req)
    if not db.user(user_id):
        return response("Сначала зарегистрируй игровой аккаунт в боте.",403)
    details=(db.setting("manual_payment_details", "") or "").strip()
    if not details or "УКАЖИТЕ" in details.upper():
        details=os.getenv("MANUAL_PAYMENT_DETAILS", "").strip()
    if not details or "УКАЖИТЕ" in details.upper():
        return response("Владелец ещё не настроил реквизиты ручного пополнения.",503)
    return response({"payment_details":details,"minimum_rub":100,"rate":fnz_rate() or 2})

async def wallet_donate(req):
    user_id=uid(req)
    data=await payload(req)
    try:rub=round(float(str(data.get("rub","")).replace(",",".")),2)
    except Exception:return response("Укажи сумму в рублях.",400)
    if rub<100 or rub>100000:return response("Сумма должна быть от 100 до 100 000 ₽.",400)
    rate=fnz_rate()
    if not rate:return response("Курс FNZ не настроен. Используется базовый курс 1 ₽ = 2 FNZ.",503)
    nmz=int(round(rub*rate))
    if nmz<1:return response("Сумма слишком мала для начисления FNZ.",400)
    method=str(data.get("method","manual"))
    if method != "manual":return response("Доступно только ручное пополнение.",400)
    proof=str(data.get("proof","")).strip()[:500]
    if method=="manual" and len(proof)<3:return response("Укажи комментарий к переводу или последние 4 цифры операции.",400)
    manual_details=(db.setting("manual_payment_details", "") or "").strip()
    if not manual_details or "УКАЖИТЕ" in manual_details.upper():
        manual_details=os.getenv("MANUAL_PAYMENT_DETAILS", "").strip()
    if not manual_details or "УКАЖИТЕ" in manual_details.upper():
        return response("Владелец ещё не настроил реквизиты ручного пополнения. Попробуй позже.",503)
    did=shop.new_donation(db,user_id,rub,nmz,method,proof)
    text=f"💳 Новое ручное пополнение #{did}\nИгрок: {user_id}\nСумма: {rub:.2f} ₽\nНачисление после проверки: {nmz} FNZ\nПодтверждение: {proof}"
    keyboard=core.markup([[InlineKeyboardButton(text="Одобрить",callback_data=f"donation_paid:{did}"),InlineKeyboardButton(text="Отклонить",callback_data=f"donation_rejected:{did}")]])
    for aid in core.OWNER_IDS:
        try:await tg.send_message(aid,text,reply_markup=keyboard)
        except Exception:log.exception("Manual donation owner notification failed")
    return response({"id":did,"fnz":nmz,"rub":rub,"payment_details":manual_details})


async def public_manual_donation(req):
    # Public site must never accept a user-supplied Telegram ID as proof of identity.
    # Redirect the player to the authenticated bot flow instead.
    return response({"message":"Для безопасного оформления заявки открой бота FENIX ONLINE и создай заявку там.",
                     "bot_url":"https://t.me/FenixMediarobot?start=donate"},401)

async def admin_store(req):
    if not admin(req):return response("Недостаточно прав.",403)
    if req.method=="GET":
        return response({"orders":shop.list_orders(db,limit=150),"donations":shop.donations(db,"all",150),"balance_rate":fnz_rate(),"prices":store_prices(),"catalog":catalog()})
    data=await payload(req)
    try:rate=float(data.get("fnz_per_rub",2))
    except Exception:return response("Некорректный курс FNZ.",400)
    if rate<0 or rate>100000:return response("Курс вне допустимого диапазона.",400)
    prices=data.get("prices") or {}
    if not isinstance(prices,dict):return response("Неверный список цен.",400)
    clean={}
    allowed={p["code"] for p in shop.PRODUCTS}
    for key,value in prices.items():
        if key not in allowed:continue
        try:
            price=int(value)
            if not 1<=price<=100000000:raise ValueError()
            clean[key]=price
        except Exception:return response(f"Некорректная цена для {key}.",400)
    db.set_setting("fnz_per_rub",str(rate))
    db.set_setting("store_prices",json.dumps(clean,ensure_ascii=False))
    return response({"saved":True,"fnz_per_rub":rate,"prices":clean})

async def admin_donation_decision(req):
    if uid(req) not in core.OWNER_IDS:return response("Подтверждать и отклонять пополнения может только владелец проекта.",403)
    did=int(req.match_info["donation_id"]);data=await payload(req)
    decision=str(data.get("decision",""));note=str(data.get("note","")).strip()[:500]
    item=db._one(f"SELECT * FROM donations WHERE id={db._ph()}",(did,))
    if not item:return response("Платёж не найден.",404)
    if item["status"]!="pending":return response("Платёж уже обработан.",409)
    if decision=="paid":ok=shop.mark_paid(db,did,uid(req),note or "Подтверждено администратором")
    elif decision=="rejected":ok=shop.reject_donation(db,did,uid(req),note)
    else:return response("Неизвестное решение.",400)
    if not ok:return response("Не удалось изменить платёж.",409)
    text=(f"Пополнение #{did} подтверждено. Зачислено {int(item['fnz_amount'])} FNZ." if decision=="paid" else f"Пополнение #{did} отклонено. {note}")
    db.add_notification(item["uid"],"Статус пополнения",text)
    try:await tg.send_message(item["uid"],text)
    except Exception:log.exception("Donation decision notification failed")
    return response({"status":decision})

async def admin_order_decision(req):
    if not admin(req):return response("Недостаточно прав.",403)
    oid=int(req.match_info["order_id"]);data=await payload(req)
    decision=str(data.get("decision",""));note=str(data.get("note","")).strip()[:700]
    if decision not in {"processing","delivered"}:return response("Неизвестный статус.",400)
    item=db._one(f"SELECT * FROM shop_orders WHERE id={db._ph()}",(oid,))
    if not item:return response("Заказ не найден.",404)
    if not shop.update_order(db,oid,decision,uid(req),note):return response("Статус заказа уже изменён.",409)
    text=f"Заказ #{oid}: {'в обработке' if decision=='processing' else 'товар выдан'}."
    if note:text+=" "+note
    db.add_notification(item["uid"],"Обновление заказа",text)
    try:await tg.send_message(item["uid"],text)
    except Exception:log.exception("Shop order notification failed")
    return response({"status":decision})

DEFAULT_THEME = {
    "accent": "#f06a3d",
    "background": "#08090c",
    "panel": "#17191f",
    "text": "#f5f3ef",
    "muted": "#92949d",
}

def read_json_setting(key, default):
    try:
        value = json.loads(db.setting(key, json.dumps(default, ensure_ascii=False)) or "{}")
        return value if isinstance(value, type(default)) else default
    except Exception:
        return default

async def admin_design(req):
    if not admin(req):
        return response("Недостаточно прав.", 403)
    if req.method == "GET":
        pack = read_json_setting("premium_emoji_pack", [])
        styles = read_json_setting("button_style_map", {})
        icons = read_json_setting("button_custom_emoji_map", {})
        label_defaults = {
            "cab_label": "👤 Личный кабинет",
            "ref_label": "🔗 Моя реферальная ссылка",
            "stats_label": "📊 Статистика",
            "top_label": "🏆 Рейтинг",
            "media_label": "🤝 Стать медиапартнёром",
            "owner_label": "⚙️ Панель владельца",
            "home_label": "📢 Новости FENIX ONLINE",
        }
        for key, default in label_defaults.items():
            current = db.setting(key, default)
            if current in styles:
                styles[default] = styles[current]
            if current in icons:
                icons[default] = icons[current]
        return response({
            "theme": read_json_setting("ui_theme", DEFAULT_THEME),
            "button_styles": styles,
            "button_icons": icons,
            "emoji_pack": pack,
            "buttons": core.PREMIUM_BUTTON_CATALOG,
            "welcome_text": db.setting("welcome_text", "🔥 FENIX ONLINE\nТвой личный кабинет."),
            "registration_text": db.setting("registration_text", "🔥 FENIX ONLINE — регистрация\n\nВведи игровой никнейм (3–24 символа, латиница, цифры и _)."),
            "labels": {key: db.setting(key, default) for key, default in {
                "cab_label": "👤 Личный кабинет",
                "ref_label": "🔗 Моя реферальная ссылка",
                "stats_label": "📊 Статистика",
                "top_label": "🏆 Рейтинг",
                "media_label": "🤝 Стать медиапартнёром",
                "owner_label": "⚙️ Панель владельца",
                "home_label": "📢 Новости FENIX ONLINE",
            }.items()}
        })
    data = await payload(req)
    theme = data.get("theme") or {}
    if not isinstance(theme, dict):
        return response("Неверный формат цветовой темы.", 400)
    clean_theme = {}
    for key, fallback in DEFAULT_THEME.items():
        value = str(theme.get(key, fallback)).strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            return response(f"Некорректный цвет: {key}. Используй HEX вида #F06A3D.", 400)
        clean_theme[key] = value.lower()
    allowed = set(core.PREMIUM_BUTTON_CATALOG)
    styles_in = data.get("button_styles") or {}
    icons_in = data.get("button_icons") or {}
    if not isinstance(styles_in, dict) or not isinstance(icons_in, dict):
        return response("Неверный формат настроек кнопок.", 400)
    styles = {}
    for label, style in styles_in.items():
        if label in allowed and style in ("primary", "success", "danger"):
            styles[label] = style
    pack = read_json_setting("premium_emoji_pack", [])
    pack_ids = {str(item.get("id")) for item in pack if isinstance(item, dict) and item.get("id")}
    icons = {}
    for label, custom_id in icons_in.items():
        custom_id = str(custom_id or "")
        if label in allowed and custom_id and custom_id in pack_ids:
            icons[label] = custom_id
    labels = data.get("labels") or {}
    if not isinstance(labels, dict):
        return response("Неверный формат названий кнопок.", 400)
    label_defaults = {
        "cab_label": "👤 Личный кабинет",
        "ref_label": "🔗 Моя реферальная ссылка",
        "stats_label": "📊 Статистика",
        "top_label": "🏆 Рейтинг",
        "media_label": "🤝 Стать медиапартнёром",
        "owner_label": "⚙️ Панель владельца",
        "home_label": "📢 Новости FENIX ONLINE",
    }
    label_keys = set(label_defaults)
    label_remap = {}
    for key, value in labels.items():
        if key in label_keys:
            value = str(value).strip()
            if not value or len(value) > 64:
                return response(f"Проверь название кнопки {key}: от 1 до 64 символов.", 400)
            old_label = db.setting(key, label_defaults[key])
            label_remap[old_label] = value
            label_remap[label_defaults[key]] = value
            db.set_setting(key, value)
    for key, limit in (("welcome_text", 900), ("registration_text", 900)):
        if key in data:
            value = str(data[key]).strip()
            if len(value) < 2 or len(value) > limit:
                return response(f"Поле {key} должно содержать от 2 до {limit} символов.", 400)
            db.set_setting(key, value)
    for old_label, new_label in label_remap.items():
        if old_label in styles:
            styles[new_label] = styles.pop(old_label)
        if old_label in icons:
            icons[new_label] = icons.pop(old_label)
    db.set_setting("ui_theme", json.dumps(clean_theme, ensure_ascii=False))
    db.set_setting("button_style_map", json.dumps(styles, ensure_ascii=False))
    db.set_setting("button_custom_emoji_map", json.dumps(icons, ensure_ascii=False))
    return response({"saved": True, "theme": clean_theme, "styles": len(styles), "icons": len(icons)})


async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN не задан")
    db.init()
    shop.init(db)
    # Register the chat manager on the actual Render entrypoint before polling.
    # bot.py delegates startup to miniapp.main(), so registering only in bot.main()
    # leaves all chat-manager commands and callback buttons without handlers.
    from telegram_store import register as register_telegram_store
    register_telegram_store(core.dp, tg, db)
    from iris_features import register as register_iris_features
    register_iris_features(core.dp, tg, db)
    from iris_modules import register as register_iris_modules
    register_iris_modules(core.dp, tg, db, core.OWNER_IDS)
    from iris_social import register as register_iris_social
    register_iris_social(core.dp, tg, db, core.OWNER_IDS)
    from chat_manager import register_chat_manager
    register_chat_manager(core.dp, tg, db, core.OWNER_IDS)
    # Load the exact OutlineEmoji custom-emoji pack in the real Render entrypoint.
    # bot.py's standalone main() is not used here; miniapp.main() owns startup.
    try:
        sticker_set = await tg.get_sticker_set("OutlineEmoji")
        pack_items = [
            {"id": str(sticker.custom_emoji_id), "emoji": getattr(sticker, "emoji", None) or "💎"}
            for sticker in sticker_set.stickers
            if getattr(sticker, "custom_emoji_id", None)
        ]
        if not pack_items:
            raise RuntimeError("OutlineEmoji returned zero custom_emoji_id values")
        db.set_setting("premium_emoji_pack", json.dumps(pack_items, ensure_ascii=False))
        log.info("FENIX Premium Emoji: imported %s IDs from OutlineEmoji", len(pack_items))
    except Exception:
        log.exception("FENIX Premium Emoji: OutlineEmoji import failed; existing icon map retained")
    try:
        await tg.set_chat_menu_button(menu_button=MenuButtonCommands())
        log.info("Mini App menu button disabled; standalone website mode")
    except Exception:
        log.exception("Could not remove Mini App menu button")
    app = web.Application(middlewares=[auth], client_max_size=1024 * 1024)
    app.router.add_get("/", lambda _: web.FileResponse(WEB_DIR / "index.html"))
    app.router.add_get("/account", lambda _: web.FileResponse(WEB_DIR / "account.html"))
    app.router.add_get("/inventory", lambda _: web.FileResponse(WEB_DIR / "account.html"))
    app.router.add_get("/orders", lambda _: web.FileResponse(WEB_DIR / "account.html"))
    app.router.add_get("/app", home)
    app.router.add_get("/store", lambda _: web.FileResponse(WEB_DIR / "store.html"))
    app.router.add_get("/audio", lambda _: web.FileResponse(WEB_DIR / "audio.html"))
    app.router.add_get("/wheel", lambda _: web.FileResponse(WEB_DIR / "wheel.html"))
    app.router.add_get("/health", lambda _: web.json_response({"status": "ok", "service": "fenix-miniapp"}))
    app.router.add_get("/assets/{filename}", serve_asset)
    app.router.add_static("/assets/", ROOT / "assets", show_index=False)
    expected_assets = ("bmw-m3.png", "cybertruck.png", "audi-tt.png", "lancer-evolution.png", "home-v748-world.webp")
    missing_assets = [name for name in expected_assets if not (ROOT / "assets" / name).is_file()]
    if missing_assets:
        log.error("FENIX asset files missing from deployment: %s", ", ".join(missing_assets))
    else:
        log.info("FENIX assets verified: %s product/hero images available", len(expected_assets))
    app.router.add_post("/api/auth/telegram", login_telegram)
    app.router.add_post("/api/auth/logout", logout)
    app.router.add_get("/api/bootstrap", bootstrap)
    app.router.add_get("/api/stats", stats)
    app.router.add_get("/api/top", top)
    app.router.add_get("/api/tickets", tickets)
    app.router.add_post("/api/tickets", ticket_create)
    app.router.add_get("/api/tickets/{ticket_id}", ticket_detail)
    app.router.add_post("/api/tickets/{ticket_id}/reply", ticket_reply)
    app.router.add_post("/api/tickets/{ticket_id}/close", ticket_close)
    app.router.add_get("/api/notifications", notifications)
    app.router.add_post("/api/notifications/read", notifications)
    app.router.add_get("/api/achievements", achievements)
    app.router.add_get("/api/media", media_info)
    app.router.add_post("/api/media/apply", media_apply)
    app.router.add_post("/api/media/video", media_video)
    app.router.add_post("/api/media/payout", media_payout)
    app.router.add_get("/api/admin/overview", admin_overview)
    app.router.add_get("/api/admin/tickets", admin_tickets)
    app.router.add_get("/api/admin/media-applications", admin_apps)
    app.router.add_post("/api/admin/media-applications/{application_id}", admin_app_decision)
    app.router.add_get("/api/admin/payouts", admin_payouts)
    app.router.add_post("/api/admin/payouts/{payout_id}", admin_payout_decision)
    app.router.add_post("/api/admin/broadcast", admin_broadcast)
    app.router.add_post("/api/admin/publish", admin_publish)
    app.router.add_get("/api/wheel", wheel_home)
    app.router.add_post("/api/wheel/spin", wheel_spin)
    app.router.add_get("/api/shop", shop_home)
    app.router.add_post("/api/shop/buy", shop_buy)
    app.router.add_get("/api/audio", audio_tracks)
    app.router.add_post("/api/audio", audio_track_add)
    app.router.add_delete("/api/audio/{track_id}", audio_track_delete)
    app.router.add_get("/api/wallet/payment-details", wallet_payment_details)
    app.router.add_post("/api/wallet/donate", wallet_donate)
    app.router.add_get("/api/admin/store", admin_store)
    app.router.add_post("/api/admin/store", admin_store)
    app.router.add_post("/api/admin/donations/{donation_id}", admin_donation_decision)
    app.router.add_post("/api/admin/orders/{order_id}", admin_order_decision)
    app.router.add_get("/api/admin/design", admin_design)
    app.router.add_post("/api/admin/design", admin_design)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("FENIX Mini App + bot running on port %s", port)
    try:
        await core.dp.start_polling(tg, allowed_updates=core.dp.resolve_used_update_types())
    finally:
        await runner.cleanup()
        await tg.session.close()


if __name__ == "__main__":
    asyncio.run(main())
