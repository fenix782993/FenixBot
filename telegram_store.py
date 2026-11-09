"""FENIX Manager: Telegram Gifts store paid in Stars and admin gifting."""
import logging, os, secrets
from datetime import datetime, timezone
import aiohttp
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton

log = logging.getLogger("fenix.telegram_store")
TOKEN = os.getenv("BOT_TOKEN", "").strip()
MARKUP_STARS = 5

def ph(db): return "%s" if db.use_postgres else "?"
def run(db, sql, args=()):
    with db.con() as c:
        cur=c.execute(sql,args)
        return cur.rowcount
def one(db, sql, args=()):
    with db.con() as c:
        row=c.execute(sql,args).fetchone()
        return dict(row) if row else None

def init(db):
    with db.con() as c:
        if db.use_postgres:
            c.execute("""CREATE TABLE IF NOT EXISTS tg_store_items(token TEXT PRIMARY KEY,owner_uid BIGINT NOT NULL,recipient_uid BIGINT NOT NULL,gift_id TEXT NOT NULL,title TEXT,stars INTEGER NOT NULL,created TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS tg_store_orders(id TEXT PRIMARY KEY,payload TEXT UNIQUE NOT NULL,buyer_uid BIGINT NOT NULL,recipient_uid BIGINT NOT NULL,kind TEXT NOT NULL,item_id TEXT NOT NULL,title TEXT NOT NULL,stars INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'invoice',charge_id TEXT UNIQUE,error TEXT,created TEXT NOT NULL,delivered TEXT,note TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS tg_store_favorites(uid BIGINT NOT NULL,gift_id TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(uid,gift_id))""")
            c.execute("""CREATE TABLE IF NOT EXISTS tg_store_promos(code TEXT PRIMARY KEY,discount INTEGER NOT NULL,uses_left INTEGER NOT NULL,active INTEGER NOT NULL DEFAULT 1,created TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS tg_store_promo_uses(code TEXT NOT NULL,uid BIGINT NOT NULL,order_id TEXT NOT NULL UNIQUE,created TEXT NOT NULL,PRIMARY KEY(code,uid,order_id))""")
            try: c.execute("ALTER TABLE tg_store_orders ADD COLUMN IF NOT EXISTS note TEXT")
            except Exception: pass
        else:
            c.executescript("""CREATE TABLE IF NOT EXISTS tg_store_items(token TEXT PRIMARY KEY,owner_uid INTEGER NOT NULL,recipient_uid INTEGER NOT NULL,gift_id TEXT NOT NULL,title TEXT,stars INTEGER NOT NULL,created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tg_store_orders(id TEXT PRIMARY KEY,payload TEXT UNIQUE NOT NULL,buyer_uid INTEGER NOT NULL,recipient_uid INTEGER NOT NULL,kind TEXT NOT NULL,item_id TEXT NOT NULL,title TEXT NOT NULL,stars INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'invoice',charge_id TEXT UNIQUE,error TEXT,created TEXT NOT NULL,delivered TEXT,note TEXT);
            CREATE TABLE IF NOT EXISTS tg_store_favorites(uid INTEGER NOT NULL,gift_id TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(uid,gift_id));
            CREATE TABLE IF NOT EXISTS tg_store_promos(code TEXT PRIMARY KEY,discount INTEGER NOT NULL,uses_left INTEGER NOT NULL,active INTEGER NOT NULL DEFAULT 1,created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tg_store_promo_uses(code TEXT NOT NULL,uid INTEGER NOT NULL,order_id TEXT NOT NULL UNIQUE,created TEXT NOT NULL,PRIMARY KEY(code,uid,order_id));""")
            try: c.execute("ALTER TABLE tg_store_orders ADD COLUMN note TEXT")
            except Exception: pass

async def api(method, data=None):
    if not TOKEN: raise RuntimeError("BOT_TOKEN is not configured")
    timeout=aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(f"https://api.telegram.org/bot{TOKEN}/{method}",json=data or {}) as response:
            result=await response.json(content_type=None)
    if not result.get("ok"): raise RuntimeError(result.get("description",f"Telegram {method} failed"))
    return result.get("result")

async def bot_star_balance():
    result=await api("getMyStarBalance")
    return int(result.get("amount",0)) if isinstance(result,dict) else int(result or 0)

async def ensure_recipient(user_ref):
    """Resolve a numeric Telegram ID or public @username before taking payment."""
    raw=str(user_ref or "").strip()
    if raw.startswith("@"):
        if not raw[1:] or not raw[1:].replace("_","").isalnum():
            raise ValueError("Укажи корректный публичный @username Telegram.")
        chat_id=raw
    else:
        if not raw.isdigit() or int(raw)<=0:
            raise ValueError("Укажи числовой Telegram ID или публичный @username.")
        chat_id=int(raw)
    try:
        chat=await api("getChat",{"chat_id":chat_id})
    except Exception as exc:
        message=str(exc).lower()
        if "user not found" in message or "chat not found" in message:
            raise ValueError("Telegram не видит этого пользователя. Получатель должен открыть @FenixMediarobot, нажать /start и отправить любое сообщение. Затем повтори заказ, указав его числовой ID.") from exc
        raise
    if not chat or chat.get("type")!="private":
        raise ValueError("Укажи числовой ID личного Telegram-аккаунта, а не группы или канала.")
    return chat

def register(dp, bot, db, owner_ids=()):
    owner_ids=set(owner_ids or ())
    init(db)
    router=Router(name="fenix_telegram_gifts")
    class GiftFlow(StatesGroup):
        recipient=State()
        note=State()
        admin_recipient=State()
        admin_note=State()
        admin_promo=State()

    async def gifts():
        result=await api("getAvailableGifts")
        return [g for g in result.get("gifts",[]) if int(g.get("star_count",0))>0]

    async def create_invoice(buyer, recipient, gift, note):
        base=int(gift["star_count"]); total=base+MARKUP_STARS
        oid=secrets.token_hex(6); payload="fenixgift:"+oid; p=ph(db)
        title=(gift.get("sticker") or {}).get("emoji") or "🎁"
        title=f"{title} Telegram-подарок"
        run(db,f"INSERT INTO tg_store_orders(id,payload,buyer_uid,recipient_uid,kind,item_id,title,stars,status,created,note) VALUES({','.join([p]*11)})",
            (oid,payload,buyer,recipient,"gift",str(gift["id"]),title,total,"invoice",datetime.now(timezone.utc).isoformat(),note))
        await bot.send_invoice(chat_id=buyer,title=title[:32],description=f"Подарок Telegram · {base} ⭐ + 5 ⭐ комиссия. Получатель ID {recipient}.",
            payload=payload,provider_token="",currency="XTR",prices=[LabeledPrice(label=title[:32],amount=total)])

    async def send_catalog(chat_id, owner_id, recipient_id, prefix="tgs:buy:"):
        catalog=await gifts()
        if not catalog:
            return await bot.send_message(chat_id,"Telegram сейчас не вернул доступных подарков.")
        rows=[]
        for gift in catalog[:50]:
            emoji=(gift.get("sticker") or {}).get("emoji") or "🎁"
            base=int(gift["star_count"])
            token=secrets.token_urlsafe(7).replace("-","").replace("_","")[:10]
            run(db,f"INSERT INTO tg_store_items(token,owner_uid,recipient_uid,gift_id,title,stars,created) VALUES({','.join([ph(db)]*7)})",
                (token,owner_id,recipient_id,str(gift["id"]),emoji,base,datetime.now(timezone.utc).isoformat()))
            rows.append([InlineKeyboardButton(text=f"{emoji} {base+MARKUP_STARS} ⭐ · {(base+MARKUP_STARS)*1.35:.2f} ₽",callback_data=f"{prefix}{token}")])
        rows.append([InlineKeyboardButton(text="🧾 Мои заказы",callback_data="tgs:history")])
        await bot.send_message(chat_id,"<b>🎁 ПОДАРКИ TELEGRAM · FENIX</b>\nЦена: стоимость подарка + 5 ⭐ комиссия. Курс: 1 ⭐ = 1,35 ₽. Выбери подарок:",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    @router.message(Command("gifts"))
    async def gifts_command(m):
        await m.answer("🎁 Открой магазин подарков через кнопку меню.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 Открыть подарки",callback_data="tgs:catalog")]]))

    @router.callback_query(F.data=="tgs:promos")
    async def promo_admin(c,state: FSMContext):
        if c.from_user.id not in owner_ids and not db.is_admin(c.from_user.id):
            return await c.answer("Нет доступа.",show_alert=True)
        await state.set_state(GiftFlow.admin_promo)
        await c.message.answer("🎟 СОЗДАНИЕ ПРОМОКОДА\nОтправь: КОД СКИДКА_В_STARS КОЛИЧЕСТВО_АКТИВАЦИЙ\nПример: FENIX5 5 100\nСкидка уменьшает комиссию, максимум 5 ⭐.")
        await c.answer()

    @router.message(GiftFlow.admin_promo)
    async def promo_create(m,state: FSMContext):
        if m.from_user.id not in owner_ids and not db.is_admin(m.from_user.id):
            await state.clear(); return
        parts=(m.text or "").strip().split()
        if len(parts)!=3 or not parts[1].isdigit() or not parts[2].isdigit() or not parts[0].isalnum():
            return await m.answer("Формат: FENIX5 5 100")
        code=parts[0].upper(); discount=max(1,min(MARKUP_STARS,int(parts[1]))); uses=max(1,min(100000,int(parts[2])))
        with db.con() as conn:
            if db.use_postgres:
                conn.execute("INSERT INTO tg_store_promos(code,discount,uses_left,active,created) VALUES(%s,%s,%s,1,%s) ON CONFLICT(code) DO UPDATE SET discount=EXCLUDED.discount,uses_left=EXCLUDED.uses_left,active=1",(code,discount,uses,datetime.now(timezone.utc).isoformat()))
            else:
                conn.execute("INSERT OR REPLACE INTO tg_store_promos(code,discount,uses_left,active,created) VALUES(?,?,?,1,?)",(code,discount,uses,datetime.now(timezone.utc).isoformat()))
        await state.clear()
        await m.answer(f"Промокод {code} создан. Скидка {discount} ⭐. Активаций: {uses}.")
    @router.callback_query(F.data=="tgs:history")
    async def order_history(c):
        stats=one(db,f"SELECT COUNT(*) AS total, SUM(CASE WHEN status IN ('delivering','delivered','delivery_failed') THEN 1 ELSE 0 END) AS paid, SUM(CASE WHEN status='delivered' THEN 1 ELSE 0 END) AS delivered, SUM(CASE WHEN status='delivery_failed' THEN 1 ELSE 0 END) AS failed, SUM(CASE WHEN status='invoice' THEN 1 ELSE 0 END) AS unpaid, COALESCE(SUM(CASE WHEN status IN ('delivering','delivered','delivery_failed') THEN stars ELSE 0 END),0) AS spent FROM tg_store_orders WHERE buyer_uid={ph(db)}",(c.from_user.id,)) or {}
        with db.con() as conn:
            items=conn.execute(f"SELECT id,title,recipient_uid,stars,status,created,error FROM tg_store_orders WHERE buyer_uid={ph(db)} ORDER BY created DESC LIMIT 10",(c.from_user.id,)).fetchall()
        labels={"invoice":"Ожидает оплаты","delivering":"Оплата получена · отправляется","delivered":"Подарок доставлен","delivery_failed":"Оплачено · нужна проверка"}
        lines=["🧾 <b>МОИ ЗАКАЗЫ</b>",f"Всего заказов: <b>{stats.get('total',0) or 0}</b>",f"Оплачено: <b>{stats.get('paid',0) or 0}</b> · доставлено: <b>{stats.get('delivered',0) or 0}</b>",f"Ошибки доставки: <b>{stats.get('failed',0) or 0}</b> · ожидают оплаты: <b>{stats.get('unpaid',0) or 0}</b>",f"Потрачено: <b>{stats.get('spent',0) or 0} ⭐</b>",""]
        for item in items:
            item=dict(item)
            lines.append(f"• {item['title']} — <b>{item['stars']} ⭐</b>\nПолучатель: <code>{item['recipient_uid']}</code>\nСтатус: {labels.get(item['status'],item['status'])}\nЗаказ: <code>{item['id']}</code>")
            if item.get("error") and item["status"]=="delivery_failed": lines.append("Ошибка: "+str(item["error"])[:160])
        await c.message.answer("\n\n".join(lines),parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 В магазин",callback_data="tgs:catalog")]]))
        await c.answer()

    @router.callback_query(F.data=="tgs:adminstats")
    async def admin_stats(c):
        if c.from_user.id not in owner_ids and not db.is_admin(c.from_user.id):
            return await c.answer("Нет доступа.",show_alert=True)
        with db.con() as conn:
            totals=dict(conn.execute(f"SELECT COUNT(*) AS orders, SUM(CASE WHEN status IN ('delivering','delivered','delivery_failed') THEN 1 ELSE 0 END) AS paid, SUM(CASE WHEN status='invoice' THEN 1 ELSE 0 END) AS unpaid, SUM(CASE WHEN status='delivered' THEN 1 ELSE 0 END) AS delivered, SUM(CASE WHEN status='delivering' THEN 1 ELSE 0 END) AS delivering, SUM(CASE WHEN status='delivery_failed' THEN 1 ELSE 0 END) AS failed, COALESCE(SUM(CASE WHEN status IN ('delivering','delivered','delivery_failed') THEN stars ELSE 0 END),0) AS revenue, COALESCE(SUM(CASE WHEN status IN ('delivering','delivered','delivery_failed') THEN {MARKUP_STARS} ELSE 0 END),0) AS commission_paid, COALESCE(SUM(CASE WHEN status='delivered' THEN {MARKUP_STARS} ELSE 0 END),0) AS commission_delivered, COALESCE(SUM(CASE WHEN status IN ('delivering','delivery_failed') THEN {MARKUP_STARS} ELSE 0 END),0) AS commission_held FROM tg_store_orders").fetchone())
        for key in ("paid","unpaid","delivered","delivering","failed","orders"):
            totals[key]=int(totals.get(key) or 0)
        balance=await bot_star_balance()
        rub=lambda stars: f"{stars*1.35:.2f}"
        await c.message.answer(f"💰 <b>ФИНАНСЫ FENIX STARS</b>\n━━━━━━━━━━━━━━━━━━\n🧾 Всего заказов: <b>{totals['orders']}</b>\n💳 Оплачено: <b>{totals['paid']}</b>\n🎁 Доставлено: <b>{totals['delivered']}</b>\n⏳ В процессе отправки: <b>{totals['delivering']}</b>\n⚠️ Ошибки доставки: <b>{totals['failed']}</b>\n🕒 Ожидают оплаты: <b>{totals['unpaid']}</b>\n━━━━━━━━━━━━━━━━━━\n💰 Получено оплат: <b>{totals['revenue']} ⭐</b> · <b>{rub(totals['revenue'])} ₽</b>\n📈 Комиссия получена: <b>{totals['commission_paid']} ⭐</b> · <b>{rub(totals['commission_paid'])} ₽</b>\n✅ Комиссия по доставленным: <b>{totals['commission_delivered']} ⭐</b>\n🔒 Комиссия в заказах с проблемой/доставкой: <b>{totals['commission_held']} ⭐</b>\n━━━━━━━━━━━━━━━━━━\n⭐ Баланс бота сейчас: <b>{balance} ⭐</b> · <b>{rub(balance)} ₽</b>\n🧾 Комиссия за заказ: <b>{MARKUP_STARS} ⭐</b> · <b>{rub(MARKUP_STARS)} ₽</b>\n💱 Курс: <b>1 ⭐ = 1,35 ₽</b>",parse_mode="HTML")
        await c.answer()

    @router.callback_query(F.data=="tgs:catalog")
    async def catalog_callback(c, state: FSMContext):
        await state.clear()
        await state.set_state(GiftFlow.recipient)
        await c.message.answer("Кому отправить подарок? Отправь числовой Telegram ID получателя. Чтобы подарить себе — нажми кнопку.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 Себе",callback_data="tgs:self")]]))
        await c.answer()

    @router.callback_query(F.data=="tgs:self")
    async def self_recipient(c,state: FSMContext):
        await state.update_data(recipient=c.from_user.id)
        await state.clear()
        try: await send_catalog(c.from_user.id,c.from_user.id,c.from_user.id)
        except Exception:
            log.exception("Gift catalog failed"); await c.answer("Не удалось загрузить каталог.",show_alert=True); return
        await c.answer()

    @router.message(GiftFlow.recipient)
    async def recipient_input(m,state: FSMContext):
        raw=(m.text or "").strip()
        if not (raw.isdigit() and int(raw)>0) and not (raw.startswith("@") and len(raw)>2):
            return await m.answer("Введи числовой Telegram ID или @username. Для подарка себе нажми кнопку «Себе».")
        try:
            recipient_chat=await ensure_recipient(raw)
            recipient_id=int(recipient_chat["id"])
        except ValueError as exc:
            return await m.answer(str(exc))
        except Exception:
            log.exception("Recipient validation failed")
            return await m.answer("Не удалось проверить получателя в Telegram. Попробуй позже.")
        await state.clear()
        try: await send_catalog(m.chat.id,m.from_user.id,recipient_id)
        except Exception:
            log.exception("Gift catalog failed"); await m.answer("Не удалось загрузить каталог Telegram.")

    @router.callback_query(F.data.startswith("tgs:buy:"))
    async def select_gift(c,state: FSMContext):
        token=c.data.split(":")[-1]
        item=one(db,f"SELECT * FROM tg_store_items WHERE token={ph(db)}",(token,))
        if not item or int(item["owner_uid"])!=c.from_user.id:
            return await c.answer("Каталог устарел. Открой заново.",show_alert=True)
        await state.update_data(token=token)
        await state.set_state(GiftFlow.note)
        await c.message.answer("Добавить надпись к подарку? Отправь текст (до 128 символов) или нажми «Без надписи».",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Без надписи",callback_data="tgs:nonote")]]))
        await c.answer()

    async def issue_invoice(c, state, note):
        data=await state.get_data(); item=one(db,f"SELECT * FROM tg_store_items WHERE token={ph(db)}",(data.get("token",""),))
        if not item or int(item["owner_uid"])!=c.from_user.id:
            await state.clear(); return await c.answer("Позиция устарела.",show_alert=True)
        gift={"id":item["gift_id"],"star_count":item["stars"],"sticker":{"emoji":item["title"]}}
        try:
            await create_invoice(c.from_user.id,int(item["recipient_uid"]),gift,note)
            await state.clear(); await c.answer("Счёт создан")
        except Exception:
            log.exception("Gift invoice create failed"); await c.answer("Не удалось создать счёт.",show_alert=True)

    @router.callback_query(F.data=="tgs:nonote")
    async def no_note(c,state: FSMContext):
        await issue_invoice(c,state,"")

    @router.message(GiftFlow.note)
    async def note_input(m,state: FSMContext):
        note=(m.text or "").strip()
        if len(note)>128: return await m.answer("Максимум 128 символов. Сократи надпись.")
        data=await state.get_data(); item=one(db,f"SELECT * FROM tg_store_items WHERE token={ph(db)}",(data.get("token",""),))
        if not item or int(item["owner_uid"])!=m.from_user.id:
            await state.clear(); return await m.answer("Каталог устарел. Открой магазин заново.")
        gift={"id":item["gift_id"],"star_count":item["stars"],"sticker":{"emoji":item["title"]}}
        try:
            await create_invoice(m.from_user.id,int(item["recipient_uid"]),gift,note)
            await state.clear()
        except Exception:
            log.exception("Gift invoice failed"); await m.answer("Не удалось создать счёт.")

    @router.callback_query(F.data=="tgs:admin")
    async def admin_gifts(c,state: FSMContext):
        if c.from_user.id not in owner_ids and not db.is_admin(c.from_user.id):
            return await c.answer("Нет доступа.",show_alert=True)
        await state.clear()
        await state.set_state(GiftFlow.admin_recipient)
        await c.message.answer("🎁 <b>АДМИН · ПОДАРИТЬ ПОДАРОК</b>\nОтправь числовой Telegram ID или @username.",parse_mode="HTML")
        await c.answer()

    @router.message(GiftFlow.admin_recipient)
    async def admin_recipient(m,state: FSMContext):
        if m.from_user.id not in owner_ids and not db.is_admin(m.from_user.id):
            await state.clear(); return
        raw=(m.text or "").strip()
        if not (raw.isdigit() and int(raw)>0) and not (raw.startswith("@") and len(raw)>2):
            return await m.answer("Введи числовой Telegram ID или @username.")
        try:
            recipient_chat=await ensure_recipient(raw)
            recipient_id=int(recipient_chat["id"])
        except ValueError as exc:
            return await m.answer(str(exc))
        except Exception:
            log.exception("Admin recipient validation failed")
            return await m.answer("Не удалось проверить получателя в Telegram. Попробуй позже.")
        await state.update_data(admin_recipient=recipient_id)
        await state.set_state(GiftFlow.admin_note)
        await m.answer("Надпись к подарку? Отправь текст или напиши «-» без надписи.")

    @router.message(GiftFlow.admin_note)
    async def admin_note(m,state: FSMContext):
        if m.from_user.id not in owner_ids and not db.is_admin(m.from_user.id):
            await state.clear(); return
        note=(m.text or "").strip()
        if note=="-": note=""
        if len(note)>128: return await m.answer("Максимум 128 символов.")
        data=await state.get_data()
        try:
            catalog=await gifts()
            if not catalog: return await m.answer("Нет доступных подарков.")
            await state.update_data(admin_note=note)
            rows=[]
            for gift in catalog[:50]:
                emoji=(gift.get("sticker") or {}).get("emoji") or "🎁"
                rows.append([InlineKeyboardButton(text=f"{emoji} · {gift['star_count']} ⭐",callback_data=f"tgs:adminpick:{gift['id']}")])
            await m.answer("Выбери подарок. Он будет оплачен с баланса Stars бота.",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        except Exception:
            log.exception("Admin gift catalog error"); await m.answer("Не удалось загрузить каталог.")
        await state.update_data(admin_recipient=data["admin_recipient"])
        await state.set_state(GiftFlow.admin_note)

    @router.callback_query(F.data.startswith("tgs:adminpick:"))
    async def admin_pick(c,state: FSMContext):
        if c.from_user.id not in owner_ids and not db.is_admin(c.from_user.id):
            return await c.answer("Нет доступа.",show_alert=True)
        gift_id=c.data.split(":",2)[2]
        data=await state.get_data()
        if not data.get("admin_recipient"): return await c.answer("Сессия истекла.",show_alert=True)
        try:
            catalog=await gifts(); gift=next((g for g in catalog if str(g["id"])==gift_id),None)
            if not gift: return await c.answer("Подарок больше недоступен.",show_alert=True)
            cost=int(gift["star_count"]); balance=await bot_star_balance()
            if balance<cost: return await c.answer(f"На балансе {balance} ⭐, нужно {cost} ⭐.",show_alert=True)
            payload={"user_id":int(data["admin_recipient"]),"gift_id":gift_id}
            if data.get("admin_note"): payload["text"]=data["admin_note"]
            await api("sendGift",payload)
            await state.clear()
            await c.message.answer(f"✅ Подарок отправлен пользователю <code>{data['admin_recipient']}</code>.\nСписано: {cost} ⭐. Остаток до операции: {balance} ⭐.",parse_mode="HTML")
            await c.answer("Отправлено")
        except Exception as e:
            log.exception("Admin gift send failed")
            message=str(e)
            if "user not found" in message.lower() or "chat not found" in message.lower():
                message="Telegram не нашёл получателя. Он должен открыть @FenixMediarobot, нажать /start и отправить любое сообщение. После этого повтори отправку."
            await c.answer(f"Ошибка отправки: {message[:150]}",show_alert=True)

    @router.pre_checkout_query()
    async def pre_checkout(q):
        order=one(db,f"SELECT * FROM tg_store_orders WHERE payload={ph(db)}",(q.invoice_payload,))
        ok=bool(order and order["status"]=="invoice" and int(order["buyer_uid"])==q.from_user.id and int(order["stars"])==int(q.total_amount) and q.currency=="XTR")
        error="Счёт недействителен. Открой магазин заново."
        # Не проверяем баланс до оплаты: Stars по счёту должны поступить боту.
        # После успешной оплаты проверяем, что номинала хватает на sendGift.
        await q.answer(ok=ok,error_message=None if ok else error)

    @router.message(F.successful_payment)
    async def payment_success(m):
        pay=m.successful_payment; p=ph(db)
        order=one(db,f"SELECT * FROM tg_store_orders WHERE payload={p}",(pay.invoice_payload,))
        if not order or int(order["buyer_uid"])!=m.from_user.id:
            log.error("Unmatched gift payment %s",pay.invoice_payload)
            return await m.answer("Платёж получен, но заказ не найден. Обратись в поддержку.")
        if pay.currency!="XTR" or int(pay.total_amount)!=int(order["stars"]):
            return await m.answer("Платёж получен, но сумма не совпала. Заказ передан на проверку.")
        charge=pay.telegram_payment_charge_id
        claimed=run(db,f"UPDATE tg_store_orders SET status='delivering',charge_id={p} WHERE id={p} AND status='invoice'",(charge,order["id"]))
        if claimed!=1: return await m.answer("Этот платёж уже обрабатывается.")
        try:
            balance=await bot_star_balance()
            gift_cost=int(order["stars"])-MARKUP_STARS
            if balance<gift_cost: raise RuntimeError(f"Недостаточно Stars на балансе бота: {balance}, нужно {gift_cost}")
            payload={"user_id":int(order["recipient_uid"]),"gift_id":str(order["item_id"])}
            if order.get("note"): payload["text"]=order["note"]
            await api("sendGift",payload)
            run(db,f"UPDATE tg_store_orders SET status='delivered',delivered={p},error=NULL WHERE id={p}",(datetime.now(timezone.utc).isoformat(),order["id"]))
            await m.answer(f"✅ Подарок отправлен пользователю <code>{order['recipient_uid']}</code>. Оплата: {order['stars']} ⭐ (включая комиссию {MARKUP_STARS} ⭐).",parse_mode="HTML")
        except Exception as e:
            log.exception("Paid gift delivery failed")
            run(db,f"UPDATE tg_store_orders SET status='delivery_failed',error={p} WHERE id={p}",(str(e)[:1000],order["id"]))
            for admin_id in owner_ids:
                try: await bot.send_message(admin_id,f"⚠️ Заказ #{order['id']} оплачен, но подарок не отправлен. Получатель {order['recipient_uid']}. Ошибка: {str(e)[:500]}")
                except Exception: pass
            await m.answer("Оплата принята, но Telegram не выполнил отправку. Заказ сохранён для проверки; повторно платить не нужно.")

    dp.include_router(router)
    log.info("FENIX Telegram gifts store router registered")