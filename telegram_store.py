"""FENIX Telegram Stars store: real Telegram gifts and Premium subscriptions."""
import logging
import os
import secrets
from datetime import datetime, timezone
import aiohttp
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton

log = logging.getLogger("fenix.telegram_store")
TOKEN = os.getenv("BOT_TOKEN", "").strip()
PREMIUM_PRICES = {3: 1000, 6: 1500, 12: 2500}

def ph(db): return "%s" if db.use_postgres else "?"
def run(db, sql, args=()):
    with db.con() as c: return c.execute(sql, args)
def one(db, sql, args=()):
    with db.con() as c:
        row=c.execute(sql,args).fetchone()
        return dict(row) if row else None

def init(db):
    with db.con() as c:
        if db.use_postgres:
            c.execute("""CREATE TABLE IF NOT EXISTS tg_store_items(token TEXT PRIMARY KEY,owner_uid BIGINT NOT NULL,recipient_uid BIGINT NOT NULL,gift_id TEXT NOT NULL,title TEXT,stars INTEGER NOT NULL,created TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS tg_store_orders(id TEXT PRIMARY KEY,payload TEXT UNIQUE NOT NULL,buyer_uid BIGINT NOT NULL,recipient_uid BIGINT NOT NULL,kind TEXT NOT NULL,item_id TEXT NOT NULL,title TEXT NOT NULL,stars INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'invoice',charge_id TEXT UNIQUE,error TEXT,created TEXT NOT NULL,delivered TEXT)""")
        else:
            c.executescript("""CREATE TABLE IF NOT EXISTS tg_store_items(token TEXT PRIMARY KEY,owner_uid INTEGER NOT NULL,recipient_uid INTEGER NOT NULL,gift_id TEXT NOT NULL,title TEXT,stars INTEGER NOT NULL,created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tg_store_orders(id TEXT PRIMARY KEY,payload TEXT UNIQUE NOT NULL,buyer_uid INTEGER NOT NULL,recipient_uid INTEGER NOT NULL,kind TEXT NOT NULL,item_id TEXT NOT NULL,title TEXT NOT NULL,stars INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'invoice',charge_id TEXT UNIQUE,error TEXT,created TEXT NOT NULL,delivered TEXT);""")

async def api(method, data=None):
    if not TOKEN: raise RuntimeError("BOT_TOKEN is not configured")
    timeout=aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(f"https://api.telegram.org/bot{TOKEN}/{method}",json=data or {}) as response:
            result=await response.json(content_type=None)
    if not result.get("ok"): raise RuntimeError(result.get("description",f"Telegram {method} failed"))
    return result.get("result")

def register(dp, bot, db):
    init(db)
    router=Router(name="fenix_telegram_stars_store")
    async def invoice(buyer,recipient,kind,item_id,title,stars):
        oid=secrets.token_hex(6); payload="fenix:"+oid; p=ph(db)
        run(db,f"INSERT INTO tg_store_orders(id,payload,buyer_uid,recipient_uid,kind,item_id,title,stars,status,created) VALUES({','.join([p]*10)})",
            (oid,payload,buyer,recipient,kind,str(item_id),title,int(stars),"invoice",datetime.now(timezone.utc).isoformat()))
        await bot.send_invoice(chat_id=buyer,title=title[:32],description=f"Подарок для Telegram ID {recipient}. Оплата Telegram Stars.",
            payload=payload,provider_token="",currency="XTR",prices=[LabeledPrice(label=title[:32],amount=int(stars))])

    @router.message(Command("giftshop"))
    async def giftshop(m):
        args=(m.text or "").split()
        if len(args)<2 or not args[1].isdigit():
            return await m.answer("🎁 <b>Магазин подарков FENIX</b>\nИспользование: <code>/giftshop TELEGRAM_ID</code>",parse_mode="HTML")
        recipient=int(args[1])
        try: gifts=(await api("getAvailableGifts")).get("gifts",[])
        except Exception as e:
            log.exception("Gift catalog error")
            return await m.answer(f"Не удалось получить каталог Telegram: {str(e)[:200]}")
        gifts=[g for g in gifts if int(g.get("star_count",0))>0]
        if not gifts: return await m.answer("Telegram сейчас не вернул доступных подарков.")
        buttons=[]
        for gift in gifts[:40]:
            emoji=(gift.get("sticker") or {}).get("emoji") or "🎁"; stars=int(gift["star_count"])
            label=f"{emoji} Подарок · {stars} ⭐"; token=secrets.token_urlsafe(6).replace("-","").replace("_","")[:8]
            run(db,f"INSERT INTO tg_store_items(token,owner_uid,recipient_uid,gift_id,title,stars,created) VALUES({','.join([ph(db)]*7)})",
                (token,m.from_user.id,recipient,str(gift["id"]),label,stars,datetime.now(timezone.utc).isoformat()))
            buttons.append([InlineKeyboardButton(text=label[:60],callback_data=f"tgs:g:{token}")])
        buttons.append([InlineKeyboardButton(text="⭐ Telegram Premium",callback_data=f"tgs:p:3:{recipient}")])
        await m.answer("<b>FENIX · TELEGRAM GIFTS</b>\nКаталог получен напрямую из Telegram. Выбери подарок — после оплаты бот отправит его получателю.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    @router.message(Command("premiumgift"))
    async def premiumgift(m):
        args=(m.text or "").split()
        if len(args)<2 or not args[1].isdigit():
            return await m.answer("Использование: <code>/premiumgift TELEGRAM_ID</code>",parse_mode="HTML")
        uid=int(args[1])
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="3 месяца · 1000 ⭐",callback_data=f"tgs:p:3:{uid}")],
            [InlineKeyboardButton(text="6 месяцев · 1500 ⭐",callback_data=f"tgs:p:6:{uid}")],
            [InlineKeyboardButton(text="12 месяцев · 2500 ⭐",callback_data=f"tgs:p:12:{uid}")]])
        await m.answer("<b>Подарить Telegram Premium</b>\nВыбери срок подписки:",parse_mode="HTML",reply_markup=kb)

    @router.callback_query(F.data.startswith("tgs:g:"))
    async def choose_gift(c):
        token=c.data.split(":")[-1]; item=one(db,f"SELECT * FROM tg_store_items WHERE token={ph(db)}",(token,))
        if not item or int(item["owner_uid"])!=c.from_user.id: return await c.answer("Позиция устарела. Открой каталог заново.",show_alert=True)
        try:
            await invoice(c.from_user.id,int(item["recipient_uid"]),"gift",item["gift_id"],item["title"],int(item["stars"]))
            await c.answer("Счёт создан")
        except Exception:
            log.exception("Gift invoice error"); await c.answer("Не удалось создать счёт",show_alert=True)

    @router.callback_query(F.data.startswith("tgs:p:"))
    async def choose_premium(c):
        parts=c.data.split(":")
        months,recipient=(int(parts[-2]),int(parts[-1]))
        stars=PREMIUM_PRICES.get(months)
        if not stars or recipient<=0: return await c.answer("Некорректный запрос",show_alert=True)
        try:
            await invoice(c.from_user.id,recipient,"premium",months,f"Telegram Premium · {months} мес.",stars)
            await c.answer("Счёт создан")
        except Exception:
            log.exception("Premium invoice error"); await c.answer("Не удалось создать счёт",show_alert=True)

    @router.pre_checkout_query()
    async def pre_checkout(q):
        order=one(db,f"SELECT * FROM tg_store_orders WHERE payload={ph(db)}",(q.invoice_payload,))
        ok=bool(order and order["status"]=="invoice" and int(order["buyer_uid"])==q.from_user.id and int(order["stars"])==int(q.total_amount) and q.currency=="XTR")
        await q.answer(ok=ok,error_message=None if ok else "Счёт недействителен. Открой магазин заново.")

    @router.message(F.successful_payment)
    async def payment_success(m):
        pay=m.successful_payment; p=ph(db)
        order=one(db,f"SELECT * FROM tg_store_orders WHERE payload={p}",(pay.invoice_payload,))
        if not order or int(order["buyer_uid"])!=m.from_user.id:
            log.error("Unmatched successful Stars payment %s",pay.invoice_payload)
            return await m.answer("Платёж получен, но заказ не найден. Обратись в поддержку и приложи ID платежа.")
        if pay.currency != "XTR" or int(pay.total_amount) != int(order["stars"]):
            log.error("Stars payment mismatch for order %s: currency=%s amount=%s expected=%s", order["id"], pay.currency, pay.total_amount, order["stars"])
            return await m.answer("Платёж получен, но сумма не совпала с заказом. Доставка остановлена, обратись в поддержку и приложи ID платежа.")
        charge=pay.telegram_payment_charge_id
        claimed=run(db,f"UPDATE tg_store_orders SET status='delivering',charge_id={p} WHERE id={p} AND status='invoice'",(charge,order["id"]))
        if getattr(claimed,"rowcount",0)!=1:
            return await m.answer("Этот платёж уже обрабатывается. Повторная выдача не выполняется.")
        try:
            if order["kind"]=="gift":
                await api("sendGift",{"user_id":int(order["recipient_uid"]),"gift_id":str(order["item_id"]),"text":"Подарок от FENIX"})
            else:
                await api("giftPremiumSubscription",{"user_id":int(order["recipient_uid"]),"month_count":int(order["item_id"]),"star_count":int(order["stars"]),"text":"Telegram Premium от FENIX"})
            run(db,f"UPDATE tg_store_orders SET status='delivered',delivered={p},error=NULL WHERE id={p}",(datetime.now(timezone.utc).isoformat(),order["id"]))
            await m.answer(f"✅ {order['title']} отправлен пользователю <code>{order['recipient_uid']}</code>.",parse_mode="HTML")
        except Exception as e:
            log.exception("Paid gift delivery failed")
            run(db,f"UPDATE tg_store_orders SET status='delivery_failed',error={p} WHERE id={p}",(str(e)[:1000],order["id"]))
            await m.answer("Оплата принята, но Telegram не выполнил отправку. Заказ сохранён для ручной проверки; повторно оплачивать не нужно.")

    dp.include_router(router)
    log.info("FENIX Telegram Stars store router registered")
