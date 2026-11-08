import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram.types import MenuButtonWebApp, WebAppInfo, InlineKeyboardButton
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


@web.middleware
async def auth(request, handler):
    if request.path.startswith("/api/"):
        user = verify_init_data(request.headers.get("X-Telegram-Init-Data", ""))
        if not user:
            return response("Telegram-сессия не подтверждена. Перезапусти Mini App из Telegram.", 401)
        request["tg_user"] = user
        if not db.user(int(user["id"])):
            return response("Сначала запусти бота командой /start и заверши регистрацию.", 403)
    return await handler(request)


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



# --- FENIX NMZ store / donations ---
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
        first=str(details.get("first","")).upper()
        digits=str(details.get("digits",""))
        last=str(details.get("last","")).upper()
        region=str(details.get("region",""))
        if country not in {"Россия","Казахстан","Беларусь","Украина","Грузия"}:
            return response("Выбери страну из списка.",400)
        if len(first)!=1 or first not in shop.PLATE_LETTERS or len(last)!=2 or any(x not in shop.PLATE_LETTERS for x in last):
            return response("Недопустимые буквы номера.",400)
        if len(digits)!=3 or not digits.isdigit() or region not in shop.REGIONS:
            return response("Проверь цифры и регион.",400)
        multiplier=1.0
        if len(set(digits))==1:multiplier+=1.0
        if len(set(first+last))==1:multiplier+=1.5
        if len(set(region))==1:multiplier+=0.2
        price=int(round(700*multiplier))
        plate=f"{first}{digits}{last} {region}"
        product_name=f"Автомобильный номер {plate} · {country}"
        details={"country":country,"plate":plate,"first":first,"digits":digits,"last":last,"region":region,"price_formula":"700 NMZ + бонусы за повторения"}
    order_id=shop.create_order(db,user_id,nick,code,product_name,price,json.dumps(details,ensure_ascii=False)[:1500])
    if not order_id:return response("Недостаточно NMZ. Сначала пополни кошелёк.",409)
    msg=f"🛒 Заказ #{order_id} принят. Товар: {product_name} · {price} NMZ. Ник: {nick}. Ожидает выдачи администрацией."
    db.add_notification(user_id,"Покупка оформлена",msg)
    for aid in db.admin_ids():
        try:await tg.send_message(aid,f"🛒 <b>НОВЫЙ ЗАКАЗ #{order_id}</b>\nИгрок: <code>{nick}</code>\nТовар: {product_name}\nЦена: {price} NMZ\nДетали: {json.dumps(details,ensure_ascii=False)}",parse_mode="HTML")
        except Exception:log.exception("Shop order admin notification failed")
    return response({"id":order_id,"balance":shop.balance(db,user_id)})

async def wallet_donate(req):
    user_id=uid(req)
    data=await payload(req)
    try:rub=round(float(str(data.get("rub","")).replace(",",".")),2)
    except Exception:return response("Укажи сумму в рублях.",400)
    if rub<10 or rub>100000:return response("Сумма должна быть от 10 до 100 000 ₽.",400)
    rate=fnz_rate()
    if not rate:return response("Курс NMZ не настроен. Используется базовый курс 1 ₽ = 2 NMZ.",503)
    nmz=int(round(rub*rate))
    if nmz<1:return response("Сумма слишком мала для начисления NMZ.",400)
    method=str(data.get("method","manual"))
    if method != "manual":return response("Доступно только ручное пополнение.",400)
    proof=str(data.get("proof","")).strip()[:500]
    if method=="manual" and len(proof)<3:return response("Укажи комментарий к переводу или последние 4 цифры операции.",400)
    did=shop.new_donation(db,user_id,rub,nmz,method,proof)
    text=f"💳 Новое ручное пополнение #{did}\nИгрок: {user_id}\nСумма: {rub:.2f} ₽\nНачисление после проверки: {nmz} NMZ\nПодтверждение: {proof}"
    keyboard=core.markup([[InlineKeyboardButton(text="Одобрить",callback_data=f"donation_paid:{did}"),InlineKeyboardButton(text="Отклонить",callback_data=f"donation_rejected:{did}")]])
    for aid in db.admin_ids():
        try:await tg.send_message(aid,text,reply_markup=keyboard)
        except Exception:log.exception("Manual donation notification failed")
    return response({"id":did,"fnz":nmz,"rub":rub,"phone":"+79067853860","banks":["Сбербанк","Т-Банк"]})


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
    except Exception:return response("Некорректный курс NMZ.",400)
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
    if not admin(req):return response("Недостаточно прав.",403)
    did=int(req.match_info["donation_id"]);data=await payload(req)
    decision=str(data.get("decision",""));note=str(data.get("note","")).strip()[:500]
    item=db._one(f"SELECT * FROM donations WHERE id={db._ph()}",(did,))
    if not item:return response("Платёж не найден.",404)
    if item["status"]!="pending":return response("Платёж уже обработан.",409)
    if decision=="paid":ok=shop.mark_paid(db,did,uid(req),note or "Подтверждено администратором")
    elif decision=="rejected":ok=shop.reject_donation(db,did,uid(req),note)
    else:return response("Неизвестное решение.",400)
    if not ok:return response("Не удалось изменить платёж.",409)
    text=(f"Пополнение #{did} подтверждено. Зачислено {int(item['fnz_amount'])} NMZ." if decision=="paid" else f"Пополнение #{did} отклонено. {note}")
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
    try:
        await tg.set_chat_menu_button(menu_button=MenuButtonCommands())
        log.info("Mini App menu button disabled; standalone website mode")
    except Exception:
        log.exception("Could not remove Mini App menu button")
    app = web.Application(middlewares=[auth], client_max_size=1024 * 1024)
    app.router.add_get("/", home)
    app.router.add_get("/app", home)
    app.router.add_get("/store", lambda _: web.FileResponse(WEB_DIR / "store.html"))
    app.router.add_get("/health", lambda _: web.json_response({"status": "ok", "service": "fenix-miniapp"}))
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
    app.router.add_get("/api/shop", shop_home)
    app.router.add_post("/api/shop/buy", shop_buy)
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
