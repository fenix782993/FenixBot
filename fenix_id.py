"""FENIX ID: persistent cross-service identity foundation for the FENIX ecosystem."""
import logging
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

log = logging.getLogger("fenix.id")


def _base36(value):
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    value = int(value)
    out = ""
    while value:
        value, rem = divmod(value, 36)
        out = alphabet[rem] + out
    return out or "0"


def init(db):
    with db.con() as c:
        if db.use_postgres:
            c.execute("""CREATE TABLE IF NOT EXISTS fenix_profiles(
                uid BIGINT PRIMARY KEY, public_id TEXT UNIQUE NOT NULL,
                game_nick TEXT, game_status TEXT NOT NULL DEFAULT 'not_linked',
                forum_name TEXT, forum_status TEXT NOT NULL DEFAULT 'not_linked',
                created TEXT NOT NULL, updated TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS fenix_link_requests(
                id BIGSERIAL PRIMARY KEY, uid BIGINT NOT NULL, service TEXT NOT NULL,
                value TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                created TEXT NOT NULL, reviewed_by BIGINT, review_note TEXT)""")
        else:
            c.executescript("""CREATE TABLE IF NOT EXISTS fenix_profiles(
                uid INTEGER PRIMARY KEY, public_id TEXT UNIQUE NOT NULL,
                game_nick TEXT, game_status TEXT NOT NULL DEFAULT 'not_linked',
                forum_name TEXT, forum_status TEXT NOT NULL DEFAULT 'not_linked',
                created TEXT NOT NULL, updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS fenix_link_requests(
                id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL, service TEXT NOT NULL,
                value TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                created TEXT NOT NULL, reviewed_by INTEGER, review_note TEXT);""")


def profile(db, uid):
    row = db._one(f"SELECT * FROM fenix_profiles WHERE uid={db._ph()}", (int(uid),))
    if row:
        return row
    now = datetime.now(timezone.utc).isoformat()
    public_id = "FX-" + _base36(uid).rjust(7, "0")
    with db.con() as c:
        if db.use_postgres:
            c.execute("""INSERT INTO fenix_profiles(uid,public_id,created,updated)
                VALUES(%s,%s,%s,%s) ON CONFLICT(uid) DO NOTHING""",
                (int(uid), public_id, now, now))
        else:
            c.execute("""INSERT OR IGNORE INTO fenix_profiles(uid,public_id,created,updated)
                VALUES(?,?,?,?)""", (int(uid), public_id, now, now))
    return db._one(f"SELECT * FROM fenix_profiles WHERE uid={db._ph()}", (int(uid),))


def render(db, user):
    p = profile(db, user.id)
    account = db.user(user.id) or {}
    game = p.get("game_nick") if p.get("game_status") == "verified" else "Не привязан"
    forum = p.get("forum_name") if p.get("forum_status") == "verified" else "Не привязан"
    username = ("@" + user.username) if user.username else "Не указан"
    return (
        "🪪 <b>FENIX ID</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Уникальный номер: <code>{p['public_id']}</code>\n"
        f"Telegram: {username}\n"
        f"Игровой профиль: <b>{game}</b>\n"
        f"Форум: <b>{forum}</b>\n"
        f"Игровой ник в боте: <b>{account.get('nick') or 'Не указан'}</b>\n\n"
        "Это единый идентификатор профиля FENIX. Привязки игровых и форумных аккаунтов "
        "показываются подтверждёнными только после проверки."
    )


def register(dp, db):
    init(db)
    router = Router(name="fenix_id")

    @router.message(Command("fenixid"))
    @router.message(Command("idcard"))
    async def show_id(message):
        await message.answer(render(db, message.from_user),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обновить профиль", callback_data="fenixid:show")],
                [InlineKeyboardButton(text="🎁 Магазин подарков", callback_data="tgs:catalog")],
            ]))

    @router.callback_query(F.data == "fenixid:show")
    async def show_id_callback(callback):
        await callback.message.edit_text(render(db, callback.from_user),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎁 Магазин подарков", callback_data="tgs:catalog")]
            ]))
        await callback.answer()

    dp.include_router(router)
    log.info("FENIX ID core registered")


__all__ = ["register", "init", "profile", "render"]
