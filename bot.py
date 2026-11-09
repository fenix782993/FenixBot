import asyncio, logging, os, re, secrets, hashlib, html, json, random
import store as shop
from datetime import datetime, timezone, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, MessageEntity, WebAppInfo, LabeledPrice
from pathlib import Path
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from aiohttp import web
from db import DB

load_dotenv()
TOKEN=os.getenv("BOT_TOKEN","")
CHANNEL=os.getenv("CHANNEL_ID","")
CHANNEL_URL=os.getenv("CHANNEL_URL","")
ADMINS={int(x) for x in os.getenv("ADMIN_IDS","").replace(" ","").split(",") if x}
if not TOKEN: raise RuntimeError("BOT_TOKEN не задан")
logging.basicConfig(level=logging.INFO)
bot=Bot(TOKEN); dp=Dispatcher(storage=MemoryStorage()); db=DB(os.getenv("DATABASE_PATH","fenix.sqlite3"))
OWNER_IDS={int(x) for x in os.getenv('OWNER_IDS', os.getenv('ADMIN_IDS','')).replace(' ','').split(',') if x}
REQUIRED_CHANNEL_URL = CHANNEL_URL or "https://t.me/+1usTps-EXmxjNWRl"
def is_admin(uid): return db.is_admin(uid)

def payout_status_label(status):
    return {"pending":"🕒 На проверке","paid":"✅ Выплачено","rejected":"❌ Отклонено"}.get(str(status), str(status))

def neat_value(value, fallback="Не указано"):
    value=str(value or "").strip()
    return value if value else fallback
def is_owner(uid): return uid in OWNER_IDS
def _json_setting(key, default):
    try:
        value = json.loads(db.setting(key, json.dumps(default, ensure_ascii=False)) or "{}")
        return value if isinstance(value, type(default)) else default
    except Exception:
        return default

def _emoji_for_button_label(label, pack_ids=None):
    """Choose a stable custom emoji for any button label."""
    text = str(label or "").lower()
    groups = [
        (("покуп", "магаз", "донат", "товар", "оплат", "баланс", "stars", "пополн"), "5280818098960611598"),
        (("колес", "форту", "приз", "выигрыш", "удач"), "5395597754166682968"),
        (("профил", "кабинет", "аккаунт", "игрок", "войти"), "5382224089295365367"),
        (("реферал", "ссыл", "приглас"), "5458394638505223612"),
        (("статист", "выруч", "финанс", "продаж", "сумм"), "5449875850046481967"),
        (("рейтинг", "топ", "достижен"), "5395597754166682968"),
        (("медиа", "видео", "публикац", "канал"), "5210905596273905344"),
        (("владел", "админ", "настрой", "управлен", "состав"), "5382224089295365367"),
        (("заяв", "обращен", "тикет", "поддерж"), "5456149049214249060"),
        (("уведом", "сообщ", "ответ"), "5458421812763307254"),
        (("отклон", "удал", "закры", "отмена", "снять"), "5447621198374511640"),
        (("назад", "главн", "вернут", "спис"), "5456174445355875099"),
        (("подпис", "провер", "подтверд", "одобр", "принят", "готов"), "5382224089295365367"),
    ]
    for words, emoji_id in groups:
        if any(word in text for word in words):
            return str(emoji_id)
    if pack_ids:
        return str(pack_ids[0])
    return "5280818098960611598"


def premium_button_icons():
    """Return a complete icon map for every known and dynamically named button."""
    defaults = {
        "🛍 Донат и товары":"5280818098960611598",
        "🎡 Колесо фортуны · 50 ₽":"5395597754166682968",
        "👤 Личный кабинет":"5382224089295365367",
        "🔗 Моя реферальная ссылка":"5458394638505223612",
        "📊 Статистика":"5449875850046481967",
        "🏆 Рейтинг":"5395597754166682968",
        "🤝 Стать медиапартнёром":"5210905596273905344",
        "🎬 Кабинет медиапартнёра":"5210905596273905344",
        "⚙️ Панель владельца":"5382224089295365367",
        "💳 Пополнить баланс":"5280818098960611598",
        "🚘 Магазин":"5458696196749008675",
        "🎫 Мои заявки":"5456149049214249060",
        "🔔 Уведомления":"5458421812763307254",
        "💬 Поддержка":"5456304325166900944",
        "⬅️ Главное меню":"5456174445355875099",
        "✅ Подтвердить":"5382224089295365367",
        "❌ Отклонить":"5447621198374511640",
    }
    saved = _json_setting("button_custom_emoji_map", {})
    saved = saved if isinstance(saved, dict) else {}
    pack = _load_emoji_pack()
    pack_ids = [str(item.get("id")) for item in pack if isinstance(item, dict) and str(item.get("id", "")).isdigit()]
    result = {}
    labels = list(dict.fromkeys(list(defaults) + list(PREMIUM_BUTTON_CATALOG)))
    for index, label in enumerate(labels):
        # Every button receives an ID from the imported OutlineEmoji pack.
        result[label] = pack_ids[index % len(pack_ids)] if pack_ids else _emoji_for_button_label(label)
    # Keep explicit assignments only when they point into the currently imported pack.
    for label, emoji_id in saved.items():
        if str(emoji_id).isdigit() and (not pack_ids or str(emoji_id) in pack_ids):
            result[label] = str(emoji_id)
    return result
def premium_button_styles():
    value = _json_setting("button_style_map", {})
    return value if isinstance(value, dict) else {}

def _strip_leading_button_emoji(value):
    """Remove old Unicode emoji so Telegram shows only the OutlineEmoji icon."""
    text = str(value or "").lstrip()
    while text:
        ch = text[0]
        code = ord(ch)
        is_symbol = (
            0x1F000 <= code <= 0x1FAFF
            or 0x2600 <= code <= 0x27FF
            or 0x2300 <= code <= 0x23FF
            or code in (0xFE0E, 0xFE0F, 0x200D, 0x20E3)
            or 0x1F3FB <= code <= 0x1F3FF
        )
        if is_symbol or ch.isspace():
            text = text[1:]
        else:
            break
    return text.lstrip()


def markup(rows):
    """Apply OutlineEmoji custom icons and button styles to every inline button."""
    icons, styles = premium_button_icons(), premium_button_styles()
    pack = _load_emoji_pack()
    pack_ids = [
        str(item.get("id")) for item in pack
        if isinstance(item, dict) and str(item.get("id", "")).isdigit()
    ]
    styled_rows = []
    for row in rows:
        styled_row = []
        for button in row:
            try:
                if isinstance(button, InlineKeyboardButton):
                    callback = getattr(button, "callback_data", None) or ""
                    original_text = button.text or ""
                    aliases = {
                        "cab": "👤 Личный кабинет",
                        "ref": "🔗 Моя реферальная ссылка",
                        "stats": "📊 Статистика",
                        "top": "🏆 Рейтинг",
                        "media": "🤝 Стать медиапартнёром",
                        "owner": "⚙️ Панель владельца",
                    }
                    keys = [original_text, callback, aliases.get(callback, "")]
                    custom_id = next((icons.get(key) for key in keys if icons.get(key)), None)
                    if not custom_id and pack_ids:
                        seed = callback or original_text
                        custom_id = pack_ids[sum(ord(ch) for ch in seed) % len(pack_ids)]

                    style = next((styles.get(key) for key in keys if styles.get(key)), None)
                    default_styles = {
                        "cab": "primary", "ref": "success", "stats": "primary",
                        "top": "success", "media": "success", "media_cabinet": "success",
                        "owner": "danger", "check_subscription": "success",
                        "support": "danger", "back_home": "primary",
                        "my_tickets": "primary", "notifications": "primary",
                        "achievements": "success", "user_settings": "primary",
                        "ticket_close": "danger", "payout_reject": "danger",
                        "payout_approve": "success", "ticket_queue": "primary",
                        "ticket_reply": "primary", "media_payout": "success",
                    }
                    if not style:
                        style = default_styles.get(callback) or default_styles.get(callback.split(":", 1)[0])
                    if not style:
                        key_text = (callback + " " + original_text).lower()
                        if any(word in key_text for word in ("reject", "remove", "delete", "close", "cancel", "отклон", "удал", "закры")):
                            style = "danger"
                        elif any(word in key_text for word in ("approve", "paid", "check", "confirm", "yes", "accept", "одобр", "подтверд", "провер")):
                            style = "success"
                        else:
                            style = "primary"

                    updates = {}
                    if custom_id and str(custom_id).isdigit():
                        updates["icon_custom_emoji_id"] = str(custom_id)
                        # Keep the normal emoji in the label as a visible fallback.
                        # Telegram renders icon_custom_emoji_id only when the bot owner
                        # has Premium (or the bot has eligible Fragment usernames).
                    if style in {"primary", "success", "danger"}:
                        updates["style"] = style
                    if updates:
                        data = button.model_dump(exclude_none=True)
                        data.update(updates)
                        button = InlineKeyboardButton.model_validate(data)
            except Exception:
                logging.exception("Не удалось применить OutlineEmoji к кнопке %r", getattr(button, "text", None))
            styled_row.append(button)
        styled_rows.append(styled_row)
    return InlineKeyboardMarkup(inline_keyboard=styled_rows)


async def subscribed(uid: int) -> bool:
    # Для приватного канала CHANNEL_ID должен быть задан числовым ID в окружении.
    if not CHANNEL:
        logging.error("CHANNEL_ID не задан: обязательную подписку проверить невозможно")
        return False
    try:
        member = await bot.get_chat_member(CHANNEL, uid)
        return member.status in {"member", "administrator", "creator"}
    except Exception:
        logging.exception("Не удалось проверить подписку пользователя %s", uid)
        return False

def staff_chat_kind(chat_id):
    if str(chat_id) == str(db.setting("admin_chat_id", "")): return "admin"
    if str(chat_id) == str(db.setting("leader_chat_id", "")): return "leader"
    return None

def can_manage_chat(message, kind):
    # Bot administrators can manage both linked staff chats.
    if is_admin(message.from_user.id): return True
    # A leader may manage the leader roster only if explicitly granted that role.
    return kind == "leader" and bool(db.staff_role(message.from_user.id, "leader"))

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
ASSET_CACHE = {}
ASSET_FILES = {
    "welcome": "welcome.jpg",
    "profile": "profile.jpg",
    "referral": "referral.jpg",
    "rating": "rating.jpg",
    "media": "media_partners.jpg",
    "news": "news.jpg",
    "rewards": "rewards.jpg",
    "black": "black_server.jpg",
    "admin_recruitment": "admin_recruitment.jpg",
    "leader_recruitment": "leader_recruitment.jpg",
    "helper_recruitment": "helper_recruitment.jpg",
    "footer": "footer.png",
    "logo": "logo.png",
}

async def answer_visual(message, asset_key, caption, reply_markup=None):
    """Отправляет локальный баннер из assets; если файла нет — пишет текст."""
    filename = ASSET_FILES.get(asset_key)
    image_path = ASSETS_DIR / filename if filename else None
    if image_path and image_path.is_file():
        try:
            if len(caption or "") <= 1024:
                result=await message.answer_photo(
                    ASSET_CACHE.get(str(image_path)) or FSInputFile(str(image_path)),
                    caption=caption or None,
                    reply_markup=reply_markup
                )
                if result.photo: ASSET_CACHE[str(image_path)]=result.photo[-1].file_id
                return result
            await message.answer_photo(ASSET_CACHE.get(str(image_path)) or FSInputFile(str(image_path)))
            return await message.answer(caption, reply_markup=reply_markup)
        except Exception:
            logging.exception("Не удалось отправить баннер %s", image_path)
    else:
        logging.warning("Баннер не найден: %s", image_path)
    return await message.answer(caption, reply_markup=reply_markup)



def branded_panel(text):
    """Give every interactive bot screen one consistent FENIX header."""
    value = str(text or "")
    # Finance is already a compact owner-only report; do not prepend a second banner.
    if value.lstrip().startswith(("💰 <b>ФИНАНСЫ", "💰 ФИНАНСЫ")):
        return value
    if not value.startswith("🔥 FENIX ONLINE"):
        value = "🔥 FENIX ONLINE  •  BLACK\n━━━━━━━━━━━━━━━━━━\n" + value
    return value


def welcome_caption():
    custom = str(db.setting("welcome_text", "") or "").strip()
    if not custom or custom == "🔥 FENIX ONLINE\nТвой личный кабинет.":
        custom = "Твой игровой кабинет, покупки и статистика — в одном месте."
    return (
        "🔥 FENIX ONLINE\n"
        "━━━━━━━━━━━━━━━━━━\n"
        + custom
        + "\n\nВыбери нужный раздел в меню ниже."
    )


async def edit_panel(message, text, reply_markup=None, parse_mode="HTML"):
    """Prefer editing the existing message and keep every screen consistently branded."""
    text = branded_panel(text)
    try:
        return await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        try:
            return await message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            return await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)

@dp.callback_query(F.data == "fenixid:show")
async def fenix_id_open(c):
    try:
        from fenix_id import render as render_fenix_id
        text = render_fenix_id(db, c.from_user)
        await edit_panel(c.message, text, parse_mode="HTML", reply_markup=markup([
            [InlineKeyboardButton(text="🔄 Обновить профиль", callback_data="fenixid:show")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="back_home")]
        ]))
        await c.answer()
    except Exception:
        logging.exception("FENIX ID open failed")
        await c.answer("Не удалось открыть FENIX ID. Ошибка записана.", show_alert=True)

@dp.message(Command("fenixid"))
@dp.message(Command("idcard"))
async def fenix_id_command(m):
    try:
        from fenix_id import render as render_fenix_id
        await m.answer(render_fenix_id(db, m.from_user), parse_mode="HTML",
            reply_markup=markup([[InlineKeyboardButton(text="🪪 Открыть FENIX ID", callback_data="fenixid:show")]]))
    except Exception:
        logging.exception("FENIX ID command failed")
        await m.answer("Не удалось открыть FENIX ID. Попробуй ещё раз позже.")

def menu(uid):
    media_status=(db.media_current(uid) or {}).get("status")
    label=db.setting("home_label","📢 Новости FENIX ONLINE")
    url=db.setting("home_url",CHANNEL_URL)
    wheel_url=os.getenv("WEBAPP_URL","https://fenixbot-vyqo.onrender.com").rstrip("/")+"/wheel"
    rows=[[InlineKeyboardButton(text="🎁 Telegram-подарки",callback_data="tgs:catalog")],
          [InlineKeyboardButton(text="🎡 Колесо фортуны · 50 ₽",url=wheel_url)],
          [InlineKeyboardButton(text="⭐ Пополнить Stars",callback_data="donate_stars"),
           InlineKeyboardButton(text="💳 Ручное пополнение",callback_data="manual_donation")],
          [InlineKeyboardButton(text="🪪 FENIX ID",callback_data="fenixid:show")],
          [InlineKeyboardButton(text=db.setting("cab_label","👤 Личный кабинет"),callback_data="cab"),
           InlineKeyboardButton(text=db.setting("ref_label","🔗 Моя реферальная ссылка"),callback_data="ref")],
          [InlineKeyboardButton(text=db.setting("stats_label","📊 Статистика"),callback_data="stats"),
           InlineKeyboardButton(text=db.setting("top_label","🏆 Рейтинг"),callback_data="top")],
          [InlineKeyboardButton(text=("🎬 Кабинет медиапартнёра" if (media_status=="approved") else db.setting("media_label","🤝 Стать медиапартнёром")),callback_data=("media_cabinet" if (media_status=="approved") else "media"))]]
    if url: rows.append([InlineKeyboardButton(text=label,url=url)])
    if is_admin(uid): rows.append([InlineKeyboardButton(text=db.setting("owner_label","⚙️ Панель владельца"),callback_data="owner")])
    return markup(rows)
class S(StatesGroup):
    manual_rub=State(); manual_proof=State(); stars_custom=State()
    nick=State(); password=State(); media_channel=State(); media_stats=State(); media_contact=State()
    payout_channel=State(); payout_video=State(); media_payout_requisites=State(); payout_views=State(); payout_amount=State(); payout_note=State(); customize_label=State()
    post_text=State(); post_photo_choice=State(); post_photo=State()
    post_button_choice=State(); post_button=State(); post_url=State()
    button_label=State(); button_url=State(); broadcast=State(); admin_add=State(); admin_remove=State()
    button_emoji=State(); button_emoji_sequence=State()
    support_subject=State(); support_body=State()
def hashpw(p):
    salt=secrets.token_hex(16)
    return salt+"$"+hashlib.pbkdf2_hmac("sha256",p.encode(),salt.encode(),200000).hex()
@dp.message(Command("id"))
async def cmd_id(m): await m.answer(f"Твой Telegram ID: {m.from_user.id}")

PREMIUM_BUTTON_CATALOG = [
    # Главное меню — ключевые кнопки, показанные в Telegram-примере
    '🎡 Колесо фортуны · 50 ₽', '👤 Личный кабинет', '🔗 Моя реферальная ссылка', '📊 Статистика', '🏆 Рейтинг',
    '🤝 Стать медиапартнёром', '🎬 Кабинет медиапартнёра',
    '⚙️ Панель владельца', '📢 Новости FENIX ONLINE',
    # Остальные разделы и действия бота
    '📢 Подписаться', '✅ Проверить подписку', '🎫 Мои заявки', '🔔 Уведомления', '🏆 Достижения', '📊 Статистика', '⚙️ Настройки', '💬 Поддержка', '⬅️ Главное меню', '🎬 Кабинет медиапартнёра', '📊 Статистика видео', '🔗 Канал и примеры', '📅 Календарь активности', '💳 История выплат', '🎥 Отправить видеоотчёт', '💰 Запросить выплату', '⬅️ В кабинет', '🏠 Главное меню', '➕ Создать обращение', 'Открыть обращение', '✉️ Ответить', '🔒 Закрыть обращение', '⬅️ К моим заявкам', '🎫 К обращениям', '⬅️ В кабинет медиапартнёра', '⬅️ Назад', '📋 Заявки на выплаты', '⬅️ В панель владельца', '✅ Одобрить / рассчитать', '❌ Отклонить', '📋 К списку', '💸 Отметить отправку денег', '📣 Опубликовать пост', '📨 Рассылка', '💸 Заявки на выплаты', '🎫 Обращения игроков', '🎨 Кастомизация бота', '👥 Составы и чаты', '📈 Общая статистика', '👮 Управление администраторами', '💎 Premium Emoji для всех кнопок', '➕ Добавить администратора', '➖ Снять администратора', '🔄 Обновить статус чатов', '↩️ В панель владельца', '✅ Да', '❌ Нет'
]

def _load_emoji_pack():
    try:
        return json.loads(db.setting("premium_emoji_pack", "[]") or "[]")
    except Exception:
        return []

def _save_button_emoji_map(mapping):
    db.set_setting("button_custom_emoji_map", json.dumps(mapping, ensure_ascii=False))

@dp.message(Command("emojipack"))
async def import_emoji_pack(m: Message):
    if not is_owner(m.from_user.id):
        return await m.answer("⛔ Импортировать наборы эмодзи может только владелец.")
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer(
            "💎 <b>ИМПОРТ PREMIUM-ПАКА</b>\n\n"
            "Отправь ссылку на набор:\n"
            "<code>/emojipack https://t.me/addemoji/НАЗВАНИЕ_ПАКА</code>\n\n"
            "Также поддерживается ссылка <code>t.me/addstickers/...</code>.",
            parse_mode="HTML"
        )
    link = parts[1].strip()
    match = re.search(r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:addemoji|addstickers)/([A-Za-z0-9_]+)", link, re.IGNORECASE)
    if not match:
        return await m.answer("❌ Не распознал ссылку. Нужна ссылка вида https://t.me/addemoji/название_пака")
    pack_name = match.group(1)
    try:
        sticker_set = await bot.get_sticker_set(pack_name)
    except Exception as e:
        logging.exception("Не удалось получить Telegram sticker set %s", pack_name)
        return await m.answer(
            "❌ Не удалось загрузить набор через Telegram Bot API. "
            "Проверь ссылку и доступность набора для бота."
        )
    items = []
    for sticker in sticker_set.stickers:
        custom_id = getattr(sticker, "custom_emoji_id", None)
        if custom_id:
            items.append({"id": str(custom_id), "emoji": getattr(sticker, "emoji", None) or "💎"})
    if not items:
        return await m.answer(
            "⚠️ Набор получен, но Telegram не вернул для его элементов custom_emoji_id. "
            "Убедись, что это именно набор Custom Emoji, а не обычных стикеров."
        )
    db.set_setting("premium_emoji_pack", json.dumps(items, ensure_ascii=False))
    preview = "\n".join(f"{i}. {html.escape(x['emoji'])} — <code>{x['id']}</code>" for i,x in enumerate(items[:30],1))
    if len(items) > 30:
        preview += f"\n… и ещё {len(items)-30}"
    await m.answer(
        f"✅ <b>НАБОР СОХРАНЁН</b>\n"
        f"📦 {html.escape(pack_name)}\n"
        f"💎 Эмодзи загружено: <b>{len(items)}</b>\n\n"
        f"{preview}\n\n"
        "Назначить значок кнопке:\n<code>/setbtnemoji НОМЕР_КНОПКИ НОМЕР_ЭМОДЗИ</code>\n"
        "Список кнопок: <code>/btnlist</code>\n"
        "Список эмодзи: <code>/emojilist</code>",
        parse_mode="HTML"
    )

@dp.message(Command("emojilist"))
async def list_pack_emojis(m: Message):
    if not is_owner(m.from_user.id):
        return await m.answer("⛔ Нет доступа.")
    items = _load_emoji_pack()
    if not items:
        return await m.answer("Пак ещё не загружен. Используй /emojipack ссылка")

    # Telegram renders a real custom emoji only when the message carries
    # a custom_emoji MessageEntity with the corresponding custom_emoji_id.
    lines = ["💎 PREMIUM CUSTOM EMOJI ИЗ ПАКА", "━━━━━━━━━━━━━━━━━━"]
    entities = []
    utf16_offset = 0
    for i, item in enumerate(items, 1):
        custom_id = str(item.get("id") or "")
        marker = "X"
        line = f"{i}. {marker}  ID: {custom_id}"
        marker_offset = utf16_offset + len(f"{i}. ")
        if custom_id:
            entities.append(MessageEntity(
                type="custom_emoji",
                offset=marker_offset,
                length=1,
                custom_emoji_id=custom_id
            ))
        lines.append(line)
        # Telegram entity offsets are measured in UTF-16 code units.
        utf16_offset += len(line.encode("utf-16-le")) // 2 + 1

    text = "\n".join(lines)
    await m.answer(text, entities=entities)

@dp.message(Command("btnlist"))
async def list_premium_buttons(m: Message):
    if not is_owner(m.from_user.id):
        return await m.answer("⛔ Нет доступа.")
    mapping = premium_button_icons()
    lines = []
    for i,label in enumerate(PREMIUM_BUTTON_CATALOG,1):
        status = "💎 назначен" if mapping.get(label) else "— не назначен"
        lines.append(f"{i}. {html.escape(label)} — {status}")
    await m.answer("🎛 <b>КНОПКИ БОТА</b>\n\n" + "\n".join(lines), parse_mode="HTML")

@dp.message(Command("setbtnemoji"))
async def set_button_custom_emoji(m: Message):
    if not is_owner(m.from_user.id):
        return await m.answer("⛔ Нет доступа.")
    parts = (m.text or "").split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        return await m.answer("Формат: <code>/setbtnemoji НОМЕР_КНОПКИ НОМЕР_ЭМОДЗИ</code>\nНапример: <code>/setbtnemoji 1 4</code>", parse_mode="HTML")
    button_index, emoji_index = int(parts[1]), int(parts[2])
    if not 1 <= button_index <= len(PREMIUM_BUTTON_CATALOG):
        return await m.answer(f"Номер кнопки должен быть от 1 до {len(PREMIUM_BUTTON_CATALOG)}.")
    pack = _load_emoji_pack()
    if not 1 <= emoji_index <= len(pack):
        return await m.answer(f"В сохранённом паке нет эмодзи №{emoji_index}. Смотри /emojilist.")
    label = PREMIUM_BUTTON_CATALOG[button_index-1]
    mapping = premium_button_icons()
    mapping[label] = str(pack[emoji_index-1]["id"])
    _save_button_emoji_map(mapping)
    await m.answer(
        f"✅ <b>ЗНАЧОК НАЗНАЧЕН</b>\n\n"
        f"Кнопка №{button_index}: <b>{html.escape(label)}</b>\n"
        f"Эмодзи №{emoji_index}: {html.escape(pack[emoji_index-1].get('emoji','💎'))}\n\n"
        "Открой соответствующее меню заново, чтобы увидеть изменение.",
        parse_mode="HTML"
    )

@dp.message(Command("resetbtnemoji"))
async def reset_button_custom_emoji(m: Message):
    if not is_owner(m.from_user.id):
        return await m.answer("⛔ Нет доступа.")
    parts = (m.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await m.answer("Формат: <code>/resetbtnemoji НОМЕР_КНОПКИ</code>", parse_mode="HTML")
    index = int(parts[1])
    if not 1 <= index <= len(PREMIUM_BUTTON_CATALOG):
        return await m.answer("Неверный номер кнопки.")
    label = PREMIUM_BUTTON_CATALOG[index-1]
    mapping = premium_button_icons()
    mapping.pop(label, None)
    _save_button_emoji_map(mapping)
    await m.answer(f"✅ Premium Emoji снят с кнопки: <b>{html.escape(label)}</b>", parse_mode="HTML")

@dp.message(Command("premiumall"))
async def premium_all_start(m: Message, state: FSMContext):
    if not is_owner(m.from_user.id):
        return await m.answer("⛔ Настраивать Premium Emoji может только владелец бота.")
    await state.set_state(S.button_emoji_sequence)
    await state.update_data(premium_button_index=0, premium_button_map={})
    lines = ["💎 <b>НАСТРОЙКА PREMIUM EMOJI ДЛЯ КАЖДОЙ КНОПКИ</b>", "━━━━━━━━━━━━━━━━━━"]
    for i, label in enumerate(PREMIUM_BUTTON_CATALOG, 1):
        lines.append(f"{i}. {html.escape(label)}")
    lines += ["━━━━━━━━━━━━━━━━━━", "Отправляй Premium Emoji по одному, строго по порядку: сначала №1, затем №2, №3 и так далее.", "После каждого эмодзи бот подтвердит номер. Команда /premiumstop отменит настройку."]
    await m.answer("\n".join(lines), parse_mode="HTML")

@dp.message(S.button_emoji_sequence)
async def premium_all_receive(m: Message, state: FSMContext):
    if not is_owner(m.from_user.id):
        await state.clear()
        return await m.answer("⛔ Нет доступа.")
    data = await state.get_data()
    index = int(data.get("premium_button_index", 0))
    if index >= len(PREMIUM_BUTTON_CATALOG):
        await state.clear()
        return await m.answer("✅ Все кнопки уже настроены. Используй /premiumall, чтобы начать заново.")
    entities = list(m.entities or []) + list(m.caption_entities or [])
    custom = next((e for e in entities if e.type == "custom_emoji" and e.custom_emoji_id), None)
    if not custom:
        return await m.answer(f"💎 Пришли именно Premium Emoji для кнопки №{index+1}: <b>{html.escape(PREMIUM_BUTTON_CATALOG[index])}</b>", parse_mode="HTML")
    mapping = data.get("premium_button_map", {})
    mapping[PREMIUM_BUTTON_CATALOG[index]] = str(custom.custom_emoji_id)
    index += 1
    await state.update_data(premium_button_index=index, premium_button_map=mapping)
    if index >= len(PREMIUM_BUTTON_CATALOG):
        db.set_setting("button_custom_emoji_map", json.dumps(mapping, ensure_ascii=False))
        await state.clear()
        return await m.answer(f"🎉 <b>ГОТОВО!</b> Настроены Premium Emoji для всех {len(mapping)} кнопок. Открой меню заново, чтобы увидеть значки.", parse_mode="HTML")
    await m.answer(
        f"✅ Эмодзи №{index} сохранён.\n"
        f"💎 Теперь отправь №{index+1} для кнопки:\n<b>{html.escape(PREMIUM_BUTTON_CATALOG[index])}</b>\n"
        f"Осталось: {len(PREMIUM_BUTTON_CATALOG)-index}",
        parse_mode="HTML"
    )

@dp.message(Command("premiumstop"))
async def premium_all_stop(m: Message, state: FSMContext):
    if not is_owner(m.from_user.id):
        return await m.answer("⛔ Нет доступа.")
    await state.clear()
    await m.answer("Настройка Premium Emoji остановлена. Уже сохранённые настройки не изменены.")

@dp.message(Command("clearbuttonemoji"))
async def clear_button_emoji(m: Message):
    if not is_owner(m.from_user.id):
        return await m.answer("⛔ Нет доступа.")
    db.set_setting("button_custom_emoji_map", "{}")
    db.set_setting("button_custom_emoji_id", "")
    await m.answer("✅ Все Premium Emoji для кнопок удалены.")

@dp.message(Command("setbtnstyle"))
async def set_button_style(m: Message):
    if not is_owner(m.from_user.id):
        return await m.answer("⛔ Нет доступа.")
    parts = (m.text or "").split()
    if len(parts) != 3 or not parts[1].isdigit() or parts[2].lower() not in {"primary", "success", "danger", "default"}:
        return await m.answer("Формат: <code>/setbtnstyle НОМЕР primary|success|danger|default</code>", parse_mode="HTML")
    index = int(parts[1])
    if not 1 <= index <= len(PREMIUM_BUTTON_CATALOG):
        return await m.answer(f"Номер кнопки должен быть от 1 до {len(PREMIUM_BUTTON_CATALOG)}.")
    label = PREMIUM_BUTTON_CATALOG[index - 1]
    styles = premium_button_styles()
    if parts[2].lower() == "default":
        styles.pop(label, None)
    else:
        styles[label] = parts[2].lower()
    db.set_setting("button_style_map", json.dumps(styles, ensure_ascii=False))
    await m.answer(f"✅ Стиль кнопки <b>{html.escape(label)}</b> обновлён: <code>{parts[2].lower()}</code>", parse_mode="HTML")

@dp.message(CommandStart())
async def start(m:Message,state:FSMContext):
    try:
        await state.clear()  # /start always resets any unfinished wizard
        if not await subscribed(m.from_user.id):
            await m.answer(
                "🔒 Для использования FENIX ONLINE необходимо подписаться на канал проекта.",
                reply_markup=markup([[InlineKeyboardButton(text="📢 Подписаться", url=REQUIRED_CHANNEL_URL)],
                                     [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]])
            )
            return
        u=db.user(m.from_user.id)
        args=(m.text or '').split(maxsplit=1)
        payload=args[1] if len(args)>1 else ''
        if u and payload == "fenix_gifts":
            return await m.answer(
                "🎁 <b>FENIX · МАГАЗИН TELEGRAM</b>\nВыбери, что хочешь купить:",
                parse_mode="HTML",
                reply_markup=markup([
                    [InlineKeyboardButton(text="🎁 Купить Telegram-подарок", callback_data="tgs:catalog")],
                    [InlineKeyboardButton(text="⭐ Купить Telegram Premium", callback_data="tgs:premium_catalog")],
                    [InlineKeyboardButton(text="🆔 Мой Telegram ID", callback_data="tgs:showid")]
                ])
            )
        if u and payload in ("stars", "donate_stars"):
            rows=[[InlineKeyboardButton(text=f"{rub} ₽ · {int(rub*1.05)} ⭐",callback_data=f"stars_rub:{rub}")]
                  for rub in STARS_RUB_PRESETS]
            rows.append([InlineKeyboardButton(text="✏️ Ввести свою сумму",callback_data="stars_custom")])
            rows.append([InlineKeyboardButton(text="⬅️ Главное меню",callback_data="back_home")])
            return await m.answer("⭐ <b>Пополнение Telegram Stars</b>\nМинимум 100 ₽ · 1 ₽ = 2 FNZ.\nВыбери сумму — Telegram откроет защищённый счёт на оплату.",parse_mode="HTML",reply_markup=markup(rows))
        if u and payload.startswith('buy_'):
            code=payload[4:]
            item=next((dict(x) for x in shop.PRODUCTS if x['code']==code),None)
            try: overrides=json.loads(db.setting('store_prices','{}') or '{}')
            except Exception: overrides={}
            if item and code in overrides:
                try: item['price']=max(1,int(overrides[code]))
                except Exception: pass
            if not item or item.get('price') is None:
                return await m.answer('Этот товар пока недоступен для покупки.')
            kb=markup([[InlineKeyboardButton(text='✅ Подтвердить покупку',callback_data='buy_confirm:'+code)],
                       [InlineKeyboardButton(text='❌ Отмена',callback_data='buy_cancel')]])
            return await m.answer('🛒 Подтверждение покупки\n\nТовар: '+item['name']+'\nЦена: '+str(item['price'])+' FNZ\nИгровой ник: '+u['nick']+'\n\nПодтверди списание с баланса.',reply_markup=kb)
        if u:
            return await answer_visual(
                m, "welcome", welcome_caption(),
                reply_markup=menu(m.from_user.id)
            )
        p=(m.text or "").split(maxsplit=1); ref=None
        if len(p)>1 and p[1].startswith("r"):
            try: ref=int(p[1][1:])
            except: pass
        if ref==m.from_user.id: ref=None
        await state.update_data(ref=ref)
        await state.set_state(S.nick)
        await answer_visual(
            m, "welcome",
            db.setting("registration_text", "🔥 FENIX ONLINE — регистрация\n\nВведи игровой никнейм (3–24 символа, латиница, цифры и _).")
        )
    except Exception:
        logging.exception("Ошибка /start")
        await m.answer("Не удалось открыть бота. Попробуй ещё раз позже.")

# Telegram Stars top-up. 100 RUB is priced at 105 Stars; FNZ are credited
# only after Telegram confirms successful_payment (not on pre-checkout).
STARS_RUB_PRESETS = (100, 300, 500, 1000, 2500, 5000)


@dp.callback_query(F.data.startswith('buy_confirm:'))
async def buy_confirm(c):
    user=db.user(c.from_user.id)
    if not user: return await c.answer('Сначала зарегистрируйся через /start.',show_alert=True)
    code=c.data.split(':',1)[1]
    item=next((dict(x) for x in shop.PRODUCTS if x['code']==code),None)
    try: overrides=json.loads(db.setting('store_prices','{}') or '{}')
    except Exception: overrides={}
    if item and code in overrides:
        try: item['price']=max(1,int(overrides[code]))
        except Exception: pass
    if not item or item.get('price') is None: return await c.answer('Товар недоступен.',show_alert=True)
    price=int(item['price'])
    if shop.balance(db,c.from_user.id)<price: return await c.answer('Недостаточно FNZ. Пополни баланс.',show_alert=True)
    oid=shop.create_order(db,c.from_user.id,user['nick'],code,item['name'],price,'')
    if not oid: return await c.answer('Не удалось оформить заказ.',show_alert=True)
    msg='Покупка #'+str(oid)+' завершена: '+item['name']+' · '+str(price)+' FNZ. Товар добавлен в инвентарь. Запроси выдачу в игре.'
    db.add_notification(c.from_user.id,'Покупка завершена',msg)
    await c.message.edit_text('✅ '+msg,reply_markup=markup([[InlineKeyboardButton(text='📦 Мои заказы',callback_data='shop_orders')]]))
    await c.answer('Заказ оформлен')

@dp.callback_query(F.data=='back_home')
async def back_home(c):
    await answer_visual(c.message, "welcome", welcome_caption(), reply_markup=menu(c.from_user.id))
    await c.answer()
@dp.callback_query(F.data=='buy_cancel')
async def buy_cancel(c):
    await c.message.edit_text('Покупка отменена.')
    await c.answer()

@dp.callback_query(F.data=='shop_orders')
async def shop_orders(c):
    rows=shop.list_orders(db,uid=c.from_user.id,limit=20)
    labels={'purchased':'В инвентаре · запроси выдачу в игре','pending_delivery':'Ожидает выдачи','processing':'В обработке','delivered':'Выдан'}
    body='📦 МОИ ЗАКАЗЫ\n\n' if rows else 'У тебя пока нет заказов.'
    body += '\n'.join('#'+str(x['id'])+' · '+x['product_name']+' · '+str(x['price_fnz'])+' FNZ · '+labels.get(x['status'],x['status']) for x in rows)
    await c.message.answer(body,reply_markup=markup([[InlineKeyboardButton(text='⬅️ Главное меню',callback_data='back_home')]]))
    await c.answer()
@dp.callback_query(F.data == "manual_donation")
async def manual_donation_start(c,state:FSMContext):
    if not db.user(c.from_user.id):
        return await c.answer("Сначала зарегистрируйся через /start.",show_alert=True)
    await state.set_state(S.manual_rub)
    await c.message.answer("Введи сумму перевода в рублях. Минимум 100 ₽.")
    await c.answer()

@dp.message(S.manual_rub)
async def manual_donation_rub(m,state:FSMContext):
    raw=(m.text or "").strip().replace(" ","")
    if not raw.isdigit() or not 100<=int(raw)<=100000:
        return await m.answer("Укажи целую сумму от 100 до 100 000 ₽.")
    await state.update_data(manual_rub=int(raw))
    await state.set_state(S.manual_proof)
    await m.answer(os.getenv("MANUAL_PAYMENT_DETAILS") or db.setting("manual_payment_details", "Реквизиты для ручного пополнения пока не настроены. Обратись в поддержку."))

@dp.message(S.manual_proof)
async def manual_donation_proof(m,state:FSMContext):
    proof=(m.text or "").strip()[:500]
    if len(proof)<3:return await m.answer("Добавь комментарий или последние 4 цифры перевода.")
    data=await state.get_data(); rub=int(data["manual_rub"]); uid=m.from_user.id
    nmz=rub*2
    did=shop.new_donation(db,uid,rub,nmz,"manual",proof)
    user=db.user(uid) or {}
    text_admin=(f"💳 <b>Новая заявка на ручное пополнение #{did}</b>\n"
      f"Игрок: {html.escape(user.get('nick','—'))}\nTelegram ID: <code>{uid}</code>\n"
      f"Сумма: <b>{rub} ₽</b>\nК начислению: <b>{nmz} FNZ</b>\nПодтверждение: {html.escape(proof)}\n\n"
      "Сверь поступление в банке. Только после проверки нажимай «Одобрить».")
    kb=markup([[InlineKeyboardButton(text="✅ Одобрить",callback_data=f"donation_paid:{did}"),
               InlineKeyboardButton(text="❌ Отклонить",callback_data=f"donation_rejected:{did}")]])
    sent=0
    for aid in OWNER_IDS:
        try: await bot.send_message(aid,text_admin,parse_mode="HTML",reply_markup=kb); sent+=1
        except Exception: logging.exception("manual donation owner notification failed")
    await state.clear()
    if sent:
        await m.answer(f"Заявка #{did} отправлена владельцу. {nmz} FNZ будут начислены только после его личного одобрения.")
    else:
        shop.reject_donation(db,did,uid,"Не удалось уведомить владельца")
        await m.answer("Не удалось отправить заявку владельцу. Попробуй позже или напиши в поддержку.")

@dp.callback_query(F.data == "donate_stars")
async def donate_stars_menu(c):
    if not db.user(c.from_user.id):
        return await c.answer("Сначала зарегистрируйся через /start.", show_alert=True)
    rows=[[InlineKeyboardButton(text=f"{rub} ₽ · {int(rub*1.05)} ⭐", callback_data=f"stars_rub:{rub}")]
          for rub in STARS_RUB_PRESETS]
    rows.append([InlineKeyboardButton(text="✏️ Ввести свою сумму", callback_data="stars_custom")])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back_home")])
    await c.message.answer("⭐ <b>Пополнение Telegram Stars</b>\nМинимум 100 ₽. Курс начисления: 1 ₽ = 2 FNZ.\nОплата проходит через Telegram.",parse_mode="HTML",reply_markup=markup(rows))
    await c.answer()

@dp.callback_query(F.data=="stars_custom")
async def stars_custom_start(c,state:FSMContext):
    if not db.user(c.from_user.id):
        return await c.answer("Сначала зарегистрируйся через /start.",show_alert=True)
    await state.set_state(S.stars_custom)
    await c.message.answer("Введи сумму пополнения в рублях (от 100 до 100 000). Я выставлю счёт Telegram Stars.")
    await c.answer()

@dp.message(S.stars_custom)
async def stars_custom_amount(m,state:FSMContext):
    raw=(m.text or "").strip().replace(" ","").replace(",",".")
    try: rub=float(raw)
    except Exception: return await m.answer("Введи сумму числом, минимум 100 ₽.")
    if rub<100 or rub>100000 or round(rub,2)!=rub:
        return await m.answer("Допустимая сумма: от 100 до 100 000 ₽, можно с копейками.")
    rub_int=int(round(rub))
    if abs(rub-rub_int)>0.001:
        return await m.answer("Для оплаты Stars введи целое число рублей.")
    stars=int(rub_int*1.05); nmz=rub_int*2
    await bot.send_invoice(chat_id=m.from_user.id,title=f"FENIX ONLINE — {nmz} FNZ",
        description=f"Пополнение игрового баланса на {nmz} FNZ. Оплата {rub_int} RUB в Telegram Stars.",
        payload=f"fenix_nmz:{m.from_user.id}:{rub_int}:{stars}",provider_token="",currency="XTR",
        prices=[LabeledPrice(label=f"{nmz} FNZ",amount=stars)])
    await state.clear()

@dp.callback_query(F.data.startswith("stars_rub:"))
async def stars_invoice(c):
    if not db.user(c.from_user.id):
        return await c.answer("Сначала зарегистрируйся через /start.", show_alert=True)
    try: rub=int(c.data.split(":",1)[1])
    except Exception: return await c.answer("Некорректная сумма.",show_alert=True)
    if rub<100 or rub>100000: return await c.answer("Сумма должна быть от 100 ₽.",show_alert=True)
    stars=int(rub*1.05)
    nmz=rub*2
    await bot.send_invoice(
        chat_id=c.from_user.id,
        title=f"FENIX ONLINE — {nmz} FNZ",
        description=f"Пополнение игрового баланса на {nmz} FNZ. Оплата {rub} RUB в Telegram Stars.",
        payload=f"fenix_nmz:{c.from_user.id}:{rub}:{stars}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"{nmz} FNZ", amount=stars)],
    )
    await c.answer("Счёт Telegram Stars отправлен.")

@dp.pre_checkout_query(F.invoice_payload.startswith("fenix_nmz:"))
async def stars_pre_checkout(q):
    try:
        parts=q.invoice_payload.split(":")
        valid=(len(parts)==4 and parts[0]=="fenix_nmz" and int(parts[1])==q.from_user.id
               and int(parts[2])>=100 and int(parts[3])==q.total_amount and q.currency=="XTR")
    except Exception: valid=False
    await q.answer(ok=bool(valid), error_message=None if valid else "Счёт недействителен. Открой пополнение заново.")

@dp.message(F.successful_payment.invoice_payload.startswith("fenix_nmz:"))
async def stars_success(m):
    payment=m.successful_payment
    try:
        parts=payment.invoice_payload.split(":")
        if len(parts)!=4 or parts[0]!="fenix_nmz" or int(parts[1])!=m.from_user.id:
            raise ValueError("invalid invoice payload")
        rub,stars=int(parts[2]),int(parts[3])
        if payment.currency!="XTR" or payment.total_amount!=stars or rub<100:
            raise ValueError("payment amount mismatch")
        nmz=rub*2
        charge_key=f"telegram_payment_charge_id:{payment.telegram_payment_charge_id}"
        existing=db._one(f"SELECT id,status FROM donations WHERE method={db._ph()} AND proof={db._ph()}",("telegram_stars",charge_key))
        if existing:
            await m.answer("Этот платёж уже обработан. Повторного начисления не будет.")
            return
        did=shop.new_donation(db,m.from_user.id,rub,nmz,"telegram_stars",charge_key)
        if not shop.mark_paid(db,did,m.from_user.id,"Telegram Stars successful_payment"):
            raise RuntimeError("could not credit confirmed Stars payment")
        db.add_notification(m.from_user.id,"Пополнение Stars",f"Оплата {stars} Stars подтверждена. Начислено {nmz} FNZ.")
        await m.answer(f"✅ Оплата подтверждена Telegram. На баланс начислено <b>{nmz} FNZ</b>.",parse_mode="HTML")
    except Exception:
        logging.exception("Telegram Stars payment processing failed")
        await m.answer("Платёж получен, но автоматическое зачисление не завершилось. Обратись к владельцу с чеком Telegram.")

@dp.callback_query(F.data.startswith("donation_paid:"))
async def donation_paid(c):
    if not is_owner(c.from_user.id): return await c.answer("Только владелец.",show_alert=True)
    did=int(c.data.split(":",1)[1])
    item=db._one(f"SELECT * FROM donations WHERE id={db._ph()}",(did,))
    if not item or item["status"]!="pending": return await c.answer("Заявка уже обработана.",show_alert=True)
    if not shop.mark_paid(db,did,c.from_user.id,"Одобрено владельцем"): return await c.answer("Не удалось одобрить.",show_alert=True)
    msg="Пополнение #"+str(did)+" одобрено. Начислено "+str(int(item["fnz_amount"]))+" FNZ."
    db.add_notification(int(item["uid"]),"Статус пополнения",msg)
    try: await bot.send_message(int(item["uid"]),msg)
    except Exception: logging.exception("notify player failed")
    await c.message.edit_reply_markup(reply_markup=None)
    await c.answer("Зачисление подтверждено")
@dp.callback_query(F.data.startswith("donation_rejected:"))
async def donation_rejected(c):
    if not is_owner(c.from_user.id): return await c.answer("Только владелец.",show_alert=True)
    did=int(c.data.split(":",1)[1])
    item=db._one(f"SELECT * FROM donations WHERE id={db._ph()}",(did,))
    if not item or item["status"]!="pending": return await c.answer("Заявка уже обработана.",show_alert=True)
    if not shop.reject_donation(db,did,c.from_user.id,"Отклонено владельцем"): return await c.answer("Не удалось отклонить.",show_alert=True)
    msg="Пополнение #"+str(did)+" отклонено владельцем."
    db.add_notification(int(item["uid"]),"Статус пополнения",msg)
    try: await bot.send_message(int(item["uid"]),msg)
    except Exception: logging.exception("notify player failed")
    await c.message.edit_reply_markup(reply_markup=None)
    await c.answer("Заявка отклонена")
@dp.callback_query(F.data == "check_subscription")
async def check_subscription(c):
    if not await subscribed(c.from_user.id):
        return await c.answer("Подписка не найдена. Подпишись и нажми ещё раз.", show_alert=True)
    await c.message.answer("✅ Подписка подтверждена. Нажми /start для продолжения.")
    await c.answer("Подписка подтверждена")

@dp.message(S.nick)
async def nick(m:Message,state:FSMContext):
    n=(m.text or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{3,24}",n): return await m.answer("Неверный формат. Пример: Fenix_Rudcov")
    if db.nick_exists(n): return await m.answer("Такой ник уже занят. Введи другой.")
    await state.update_data(nick=n); await state.set_state(S.password)
    await m.answer("Придумай пароль кабинета (минимум 8 символов). Не используй пароль от других сервисов.")
@dp.message(S.password)
async def password(m:Message,state:FSMContext):
    p=m.text or ""
    if len(p)<8: return await m.answer("Пароль должен быть не короче 8 символов.")
    d=await state.get_data(); db.add_user(m.from_user.id,m.from_user.username or "",d["nick"],hashpw(p),d.get("ref"))
    db.achievement_award(m.from_user.id,"first_login","Первый вход в FENIX ONLINE")
    if d.get("ref") and db.user(d["ref"]):
        db.add_ref(d["ref"],m.from_user.id)
        if db.ref_count(d["ref"]) >= 1:
            db.achievement_award(d["ref"],"first_referral","Первый приглашённый игрок")
            db.add_notification(d["ref"],"Новый реферал",f"По твоей ссылке зарегистрировался игрок {d['nick']}.")
    await state.clear()
    await answer_visual(m, "welcome", "✅ Регистрация завершена!", reply_markup=menu(m.from_user.id))
    if d.get("ref"):
        try: await bot.send_message(d["ref"],f"🎉 По твоей ссылке зарегистрировался игрок {d['nick']}.")
        except: pass
@dp.callback_query(F.data=="cab")
async def cab(c):
    try:
        u=db.user(c.from_user.id)
        if not u:
            return await c.answer("Сначала зарегистрируйся через /start", show_alert=True)
        invited=db.ref_count(c.from_user.id)
        unread=db.unread_notifications(c.from_user.id)
        tickets=db.tickets_for_user(c.from_user.id,100)
        active=sum(1 for t in tickets if t.get("status")=="open")
        awards=db.achievements_for_user(c.from_user.id)
        text=(f"👤 <b>ЛИЧНЫЙ КАБИНЕТ</b>\n━━━━━━━━━━━━━━━━━━\n"
              f"🎮 <b>Игровой ник:</b> {html.escape(u['nick'])}\n"
              f"🟢 <b>Статус:</b> Активен\n"
              f"👥 <b>Приглашено:</b> {invited}\n"
              f"🎫 <b>Активные заявки:</b> {active}\n"
              f"🔔 <b>Новые уведомления:</b> {unread}\n"
              f"🏆 <b>Достижения:</b> {len(awards)}")
        await edit_panel(c.message,text,reply_markup=markup([
            [InlineKeyboardButton(text="🎫 Мои заявки",callback_data="my_tickets"),
             InlineKeyboardButton(text="🔔 Уведомления",callback_data="notifications")],
            [InlineKeyboardButton(text="🏆 Достижения",callback_data="achievements"),
             InlineKeyboardButton(text="📊 Статистика",callback_data="stats")],
            [InlineKeyboardButton(text="⚙️ Настройки",callback_data="user_settings"),
             InlineKeyboardButton(text="💬 Поддержка",callback_data="support")],
            [InlineKeyboardButton(text="⬅️ Главное меню",callback_data="back_home")]
        ]))
        await c.answer()
    except Exception:
        logging.exception("Ошибка открытия личного кабинета")
        await c.answer("Не удалось загрузить кабинет. Попробуй позже.", show_alert=True)

@dp.callback_query(F.data=="ref")
async def ref(c):
    try:
        if not db.user(c.from_user.id):
            return await c.answer("Сначала зарегистрируйся через /start", show_alert=True)
        me=await bot.get_me()
        link=f"https://t.me/{me.username}?start=r{c.from_user.id}"
        count=db.ref_count(c.from_user.id)
        await answer_visual(c.message, "referral",
            f"🔗 ТВОЯ РЕФЕРАЛЬНАЯ ССЫЛКА\n{link}\nЗарегистрировано по ссылке: {count}\n\nДля приглашений именно в канал используй /invite.")
        await c.answer()
    except Exception:
        logging.exception("Ошибка открытия реферальной ссылки")
        await c.answer("Не удалось загрузить ссылку. Попробуй позже.", show_alert=True)

@dp.message(Command("invite"))
async def invite(m):
    if not CHANNEL: return await m.answer("Канал не настроен.")
    if not db.user(m.from_user.id): return await m.answer("Сначала зарегистрируйся через /start")
    try:
        x=await bot.create_chat_invite_link(CHANNEL,name=f"ref-{m.from_user.id}")
        db.save_invite(x.invite_link,m.from_user.id)
        await m.answer("Твоя персональная ссылка на вступление в канал:\n"+x.invite_link)
    except Exception as e: await m.answer("Не удалось создать ссылку. Добавь бота администратором канала с правом приглашать пользователей и управлять ссылками.\n"+str(e))
@dp.chat_member()
async def member(ev:ChatMemberUpdated):
    if str(ev.chat.id)!=str(CHANNEL): return
    if ev.new_chat_member.status in ("member","administrator","creator") and ev.old_chat_member.status in ("left","kicked"):
        link=ev.invite_link.invite_link if ev.invite_link else None
        owner=db.invite_owner(link) if link else None
        if owner and owner!=ev.new_chat_member.user.id and db.add_channel_join(owner,ev.new_chat_member.user.id):
            try: await bot.send_message(owner,"🎉 По твоей ссылке новый подписчик вступил в канал!")
            except: pass
@dp.callback_query(F.data=="stats")
async def stats(c):
    try:
        registered=db.ref_count(c.from_user.id)
        joined=db.channel_count(c.from_user.id)
        await edit_panel(c.message,
            f"📊 ТВОЯ СТАТИСТИКА\n\nРегистрации по реферальной ссылке: {registered}\nВступления в канал по персональной ссылке: {joined}")
        await c.answer()
    except Exception:
        logging.exception("Ошибка загрузки статистики")
        await c.answer("Не удалось загрузить статистику. Проверь подключение базы.", show_alert=True)

@dp.callback_query(F.data=="top")
async def top(c):
    try:
        rows=db.top()
        txt="🏆 ТОП РЕФЕРАЛОВ\n\n"+("\n".join(f"{i}. {x['nick']} — {x['n']}" for i,x in enumerate(rows,1)) if rows else "Пока пусто.")
        await edit_panel(c.message, txt)
        await c.answer()
    except Exception:
        logging.exception("Ошибка рейтинга")
        await c.answer("Не удалось загрузить рейтинг.", show_alert=True)

@dp.callback_query(F.data=="media")
async def media(c,state:FSMContext):
    current=db.media_current(c.from_user.id)
    if current and current.get("status")=="pending":
        return await c.answer("Твоя заявка уже находится на рассмотрении.",show_alert=True)
    if current and current.get("status")=="approved":
        return await edit_panel(c.message,"🎉 Ты уже медиапартнёр. Открой свой кабинет.",reply_markup=markup([[InlineKeyboardButton(text="🎬 Кабинет медиапартнёра",callback_data="media_cabinet")]]))
    await state.set_state(S.media_channel)
    await edit_panel(c.message, "🤝 ЗАЯВКА В МЕДИАПАРТНЁРЫ\nПришли ссылку на свой канал или площадку.")
    await c.answer()

@dp.callback_query(F.data=="media_cabinet")
async def media_cabinet(c):
    current=db.media_current(c.from_user.id)
    if not current or current.get("status")!="approved":
        return await c.answer("Кабинет доступен только одобренным медиапартнёрам.",show_alert=True)
    days=min(db.media_active_days(c.from_user.id),7)
    views=db.media_video_views_total(c.from_user.id)
    payouts=db.media_payouts_for_user(c.from_user.id,5)
    pending=sum(1 for x in payouts if x.get("status")=="pending")
    text=( "🎬 <b>КАБИНЕТ МЕДИАПАРТНЁРА</b>\n━━━━━━━━━━━━━━━━━━\n"
           "🟢 <b>Статус:</b> Одобрен\n"
           f"📅 <b>Активные дни:</b> {days}/7\n"
           f"👁 <b>Подтверждённые просмотры:</b> {views:,}\n"
           f"💳 <b>Заявки на выплату:</b> {len(payouts)}\n"
           f"🕒 <b>На рассмотрении:</b> {pending}\n"
           "━━━━━━━━━━━━━━━━━━\nВыбери нужный раздел:")
    await edit_panel(c.message,text,reply_markup=markup([
        [InlineKeyboardButton(text="📊 Статистика видео",callback_data="media_stats")],
        [InlineKeyboardButton(text="🔗 Канал и примеры",callback_data="media_channel_info")],
        [InlineKeyboardButton(text="📅 Календарь активности",callback_data="media_calendar")],
        [InlineKeyboardButton(text="💳 История выплат",callback_data="media_history")],
        [InlineKeyboardButton(text="🎥 Отправить видеоотчёт",callback_data="media_video_report")],
        [InlineKeyboardButton(text="💰 Запросить выплату",callback_data="media_payout")],
        [InlineKeyboardButton(text="⬅️ Главное меню",callback_data="back_home")]
    ]))
    await c.answer()

@dp.callback_query(F.data=="back_home")
async def back_home(c):
    await c.answer()
    await edit_panel(c.message,"🔥 <b>FENIX ONLINE</b>\n<i>Твой проект. Твои возможности.</i>\n\nВыбери нужный раздел:",reply_markup=menu(c.from_user.id))

@dp.callback_query(F.data=="notifications")
async def user_notifications(c):
    await c.answer()
    rows=db.notifications_for_user(c.from_user.id,10)
    if not rows:
        txt="🔔 <b>УВЕДОМЛЕНИЯ</b>\n\nПока новых уведомлений нет."
    else:
        txt="🔔 <b>УВЕДОМЛЕНИЯ</b>\n━━━━━━━━━━━━━━━━━━\n"
        for n in rows:
            mark="🆕" if not n.get("is_read") else "▫️"
            txt += f"\n{mark} <b>{html.escape(n['title'])}</b>\n{html.escape(n['body'])}\n"
        db.mark_notifications_read(c.from_user.id)
    kb=markup([[InlineKeyboardButton(text="⬅️ В кабинет",callback_data="cab")],
               [InlineKeyboardButton(text="🏠 Главное меню",callback_data="back_home")]])
    try: await c.message.edit_text(txt,parse_mode="HTML",reply_markup=kb)
    except Exception: await c.message.answer(txt,parse_mode="HTML",reply_markup=kb)

@dp.callback_query(F.data=="my_tickets")
async def my_tickets(c):
    await c.answer()
    rows=db.tickets_for_user(c.from_user.id,10)
    status={"open":"🟡 Открыта","closed":"⚫ Закрыта","answered":"🟢 Есть ответ"}
    txt="🎫 <b>МОИ ЗАЯВКИ</b>\n━━━━━━━━━━━━━━━━━━\n"
    if not rows: txt+="У тебя пока нет обращений."
    else:
        for t in rows:
            txt+=f"\n<b>#{t['id']} · {html.escape(t['subject'])}</b>\n{status.get(t['status'],t['status'])}\n"
    kb=[[InlineKeyboardButton(text=f"Открыть #{t['id']}",callback_data=f"ticket_view:{t['id']}")] for t in rows[:8]]
    kb += [[InlineKeyboardButton(text="➕ Создать обращение",callback_data="support")],
           [InlineKeyboardButton(text="⬅️ В кабинет",callback_data="cab")]]
    try: await c.message.edit_text(txt,parse_mode="HTML",reply_markup=markup(kb))
    except Exception: await c.message.answer(txt,parse_mode="HTML",reply_markup=markup(kb))

@dp.callback_query(F.data=="support")
async def support_start(c,state:FSMContext):
    await c.answer()
    await state.clear()
    await state.set_state(S.support_subject)
    try: await c.message.edit_text("💬 <b>ЦЕНТР ПОДДЕРЖКИ</b>\n\nНапиши краткую тему обращения.",parse_mode="HTML")
    except Exception: await c.message.answer("💬 <b>ЦЕНТР ПОДДЕРЖКИ</b>\n\nНапиши краткую тему обращения.",parse_mode="HTML")

@dp.message(S.support_subject)
async def support_subject(m,state:FSMContext):
    subject=(m.text or "").strip()
    if len(subject)<3 or len(subject)>100:
        return await m.answer("Тема должна содержать от 3 до 100 символов.")
    await state.update_data(ticket_subject=subject)
    await state.set_state(S.support_body)
    await m.answer("Опиши проблему подробнее (до 3000 символов).")

@dp.message(S.support_body)
async def support_body(m,state:FSMContext):
    body=(m.text or "").strip()
    if len(body)<5 or len(body)>3000:
        return await m.answer("Сообщение должно содержать от 5 до 3000 символов.")
    data=await state.get_data()
    if data.get("ticket_reply_id"):
        tid=int(data["ticket_reply_id"]); ticket=db.ticket_get(tid)
        if not ticket:
            await state.clear(); return await m.answer("Обращение не найдено.")
        db.ticket_reply(tid,m.from_user.id,body)
        recipient=ticket["uid"] if m.from_user.id!=ticket["uid"] else None
        db.ticket_set_status(tid,"answered" if recipient else "open")
        if recipient:
            db.add_notification(recipient,f"Ответ по обращению #{tid}",body[:500])
            try:
                await bot.send_message(recipient,f"💬 <b>Новый ответ по обращению #{tid}</b>\n{html.escape(body[:2500])}",parse_mode="HTML",
                    reply_markup=markup([[InlineKeyboardButton(text="Открыть обращение",callback_data=f"ticket_view:{tid}")]]))
            except Exception: logging.exception("Не удалось отправить ответ пользователю")
        await state.clear()
        return await m.answer(f"✅ Ответ по обращению #{tid} отправлен.")
    tid=db.create_ticket(m.from_user.id,data["ticket_subject"],body)
    await state.clear()
    await m.answer(f"✅ <b>Обращение #{tid} создано.</b>\nПоддержка ответит здесь, в боте.",parse_mode="HTML",
                   reply_markup=markup([[InlineKeyboardButton(text="🎫 Мои заявки",callback_data="my_tickets")]]))
    for aid in db.admin_ids():
        try:
            await bot.send_message(aid,f"🎫 <b>Новое обращение #{tid}</b>\nОт: <code>{m.from_user.id}</code>\nТема: {html.escape(data['ticket_subject'])}\n{html.escape(body[:1200])}",
                parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text=f"Открыть #{tid}",callback_data=f"ticket_view:{tid}")]]))
        except Exception: logging.exception("Не удалось уведомить администратора о тикете")


@dp.callback_query(F.data.startswith("ticket_view:"))
async def ticket_view(c):
    await c.answer()
    tid=int(c.data.split(":",1)[1])
    t=db.ticket_get(tid)
    if not t or (t["uid"]!=c.from_user.id and not is_admin(c.from_user.id)):
        return await c.answer("Обращение не найдено или нет доступа.",show_alert=True)
    messages=db.ticket_messages(tid)
    txt=f"🎫 <b>ОБРАЩЕНИЕ #{tid}</b>\n<b>{html.escape(t['subject'])}</b>\nСтатус: {'Открыто' if t['status']=='open' else 'Закрыто'}\n━━━━━━━━━━━━━━━━━━\n"
    for msg in messages[-8:]:
        who="Ты" if msg["sender"]==t["uid"] else "Поддержка"
        txt+=f"\n<b>{who}:</b> {html.escape(msg['body'][:900])}\n"
    kb=[]
    if t["status"]!="closed":
        kb.append([InlineKeyboardButton(text="✉️ Ответить",callback_data=f"ticket_reply:{tid}")])
    if is_admin(c.from_user.id) and t["status"]!="closed":
        kb.append([InlineKeyboardButton(text="🔒 Закрыть обращение",callback_data=f"ticket_close:{tid}")])
    kb.append([InlineKeyboardButton(text="⬅️ К моим заявкам",callback_data="my_tickets")])
    try: await c.message.edit_text(txt,parse_mode="HTML",reply_markup=markup(kb))
    except Exception: await c.message.answer(txt,parse_mode="HTML",reply_markup=markup(kb))

@dp.callback_query(F.data.startswith("ticket_reply:"))
async def ticket_reply_start(c,state:FSMContext):
    tid=int(c.data.split(":",1)[1]); t=db.ticket_get(tid)
    if not t or (t["uid"]!=c.from_user.id and not is_admin(c.from_user.id)):
        return await c.answer("Нет доступа",show_alert=True)
    await c.answer()
    await state.clear(); await state.update_data(ticket_reply_id=tid); await state.set_state(S.support_body)
    await c.message.answer(f"✉️ Напиши ответ для обращения #{tid}.")

@dp.callback_query(F.data.startswith("ticket_close:"))
async def ticket_close(c):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    tid=int(c.data.split(":",1)[1]); t=db.ticket_get(tid)
    if not t: return await c.answer("Не найдено",show_alert=True)
    db.ticket_set_status(tid,"closed")
    db.add_notification(t["uid"],f"Обращение #{tid} закрыто","Администрация закрыла обращение. Если вопрос остался, создай новое.")
    await c.answer("Обращение закрыто")
    try: await c.message.edit_text(f"🔒 <b>Обращение #{tid} закрыто</b>",parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text="🎫 К обращениям",callback_data="ticket_queue")]]))
    except Exception: pass

@dp.callback_query(F.data=="achievements")
async def achievements(c):
    await c.answer()
    rows=db.achievements_for_user(c.from_user.id)
    txt="🏆 <b>ДОСТИЖЕНИЯ</b>\n━━━━━━━━━━━━━━━━━━\n"
    txt += "\n".join("🏅 "+html.escape(x["title"]) for x in rows) if rows else "Пока нет наград. Они будут появляться за активность в проекте."
    try: await c.message.edit_text(txt,parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text="⬅️ В кабинет",callback_data="cab")]]))
    except Exception: await c.message.answer(txt,parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text="⬅️ В кабинет",callback_data="cab")]]))

@dp.callback_query(F.data=="user_settings")
async def user_settings(c):
    await c.answer()
    txt=("⚙️ <b>НАСТРОЙКИ</b>\n━━━━━━━━━━━━━━━━━━\n"
         "🌐 Язык: Русский\n🎨 Тема: FENIX Dark Blue\n🔔 Уведомления: Включены\n\n"
         "Настройки оформления и уведомлений будут применяться ко всем разделам кабинета.")
    try: await c.message.edit_text(txt,parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text="⬅️ В кабинет",callback_data="cab")]]))
    except Exception: await c.message.answer(txt,parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text="⬅️ В кабинет",callback_data="cab")]]))

@dp.callback_query(F.data=="media_stats")
async def media_stats(c):
    await c.answer()
    rows=db.media_video_stats_for_user(c.from_user.id,10)
    total=db.media_video_views_total(c.from_user.id)
    txt=f"📊 <b>СТАТИСТИКА ВИДЕО</b>\nПодтверждено просмотров: <b>{total:,}</b>\n━━━━━━━━━━━━━━━━━━\n"
    txt += "\n".join(f"👁 {r['views']:,} · {html.escape(r['video_url'][:90])}" for r in rows) if rows else "Проверенных видео пока нет."
    try: await c.message.edit_text(txt,parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text="⬅️ В кабинет медиапартнёра",callback_data="media_cabinet")]]))
    except Exception: await c.message.answer(txt,parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text="⬅️ В кабинет медиапартнёра",callback_data="media_cabinet")]]))

@dp.callback_query(F.data=="media_channel_info")
async def media_channel_info(c):
    await c.answer()
    current=db.media_current(c.from_user.id) or {}
    txt=("🔗 <b>КАНАЛ И ПРИМЕРЫ</b>\n━━━━━━━━━━━━━━━━━━\n"
         f"Канал: {html.escape(neat_value(current.get('ch')))}\n"
         f"Аудитория и средние просмотры: {html.escape(neat_value(current.get('stats')))}\n"
         f"Контакт: {html.escape(neat_value(current.get('contact')))}\n\n"
         "Примеры видео можно добавить через обновление анкеты медиапартнёра.")
    try: await c.message.edit_text(txt,parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text="⬅️ В кабинет медиапартнёра",callback_data="media_cabinet")]]))
    except Exception: await c.message.answer(txt,parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text="⬅️ В кабинет медиапартнёра",callback_data="media_cabinet")]]))

@dp.callback_query(F.data=="media_calendar")
async def media_calendar(c):
    await c.answer()
    days=db.media_active_days(c.from_user.id)
    txt="📅 <b>КАЛЕНДАРЬ АКТИВНОСТИ</b>\n\n"
    txt+=f"Засчитано дней: <b>{min(days,7)}/7</b>\n"
    txt+="\n".join(("🟦" if i<min(days,7) else "⬜️")+f" День {i+1}" for i in range(7))
    try: await c.message.edit_text(txt,parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text="🎥 Отправить видеоотчёт",callback_data="media_video_report")],[InlineKeyboardButton(text="⬅️ Назад",callback_data="media_cabinet")]]))
    except Exception: await c.message.answer(txt,parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text="🎥 Отправить видеоотчёт",callback_data="media_video_report")],[InlineKeyboardButton(text="⬅️ Назад",callback_data="media_cabinet")]]))

@dp.callback_query(F.data=="media_history")
async def media_history(c):
    await c.answer()
    rows=db.media_payouts_for_user(c.from_user.id,15)
    labels={"pending":"🕒 На проверке","approved":"🟦 Одобрено, ожидает перевода","paid":"✅ Выплачено","rejected":"❌ Отклонено"}
    txt="💳 <b>ИСТОРИЯ ВЫПЛАТ</b>\n━━━━━━━━━━━━━━━━━━\n"
    txt+="\n".join(f"#{r['id']} · {labels.get(r['status'],'Обрабатывается')} · {html.escape(str(r['amount'] or 'Сумма не назначена'))}" for r in rows) if rows else "История пока пуста."
    try: await c.message.edit_text(txt,parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text="⬅️ Назад",callback_data="media_cabinet")]]))
    except Exception: await c.message.answer(txt,parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text="⬅️ Назад",callback_data="media_cabinet")]]))


@dp.callback_query(F.data=="media_video_report")
async def media_video_report_button(c,state:FSMContext):
    current=db.media_current(c.from_user.id)
    if not current or current.get("status")!="approved":
        return await c.answer("Доступно только одобренным медиапартнёрам.",show_alert=True)
    await state.clear()
    await state.update_data(video_report=True)
    await state.set_state(S.payout_video)
    await c.message.answer("🎥 <b>ВИДЕООТЧЁТ</b>\n\nОтправь ссылку на опубликованное видео или загрузи видеофайл. Один подтверждённый отчёт в день засчитывается как активный день.",parse_mode="HTML")
    await c.answer()

def payout_eligible(uid):
    current=db.media_current(uid)
    if not current or current.get('status')!='approved': return False, 'Кабинет медиапартнёра ещё не одобрен.'
    if db.media_payout_pending(uid): return False, 'Твоя заявка на выплату уже рассматривается.'
    days=db.media_active_days(uid)
    if days<7: return False, f'Для выплаты нужно 7 активных дней с публикациями видео. Сейчас подтверждено: {days}/7.'
    last=db.media_last_payout_request(uid)
    if last:
        try:
            dt=datetime.fromisoformat(last['created'])
            if datetime.now(timezone.utc)-dt < timedelta(days=14):
                return False, 'Заявку на выплату можно подавать только раз в 14 дней.'
        except (ValueError,TypeError): pass
    return True,''

@dp.callback_query(F.data=="media_payout")
async def media_payout_start(c,state:FSMContext):
    ok,reason=payout_eligible(c.from_user.id)
    if not ok: return await c.answer(reason,show_alert=True)
    await state.set_state(S.payout_channel)
    await c.message.answer('💸 <b>ЗАПРОС ВЫПЛАТЫ</b>\n\nОтправь ссылку на свой канал, где размещены видео.',parse_mode='HTML')
    await c.answer()

@dp.message(S.payout_channel)
async def payout_channel(m,state:FSMContext):
    url=(m.text or '').strip()
    if not url.startswith(('https://','http://')): return await m.answer('Нужна ссылка на канал, начинающаяся с https://')
    await state.update_data(payout_channel=url)
    await state.set_state(S.payout_video)
    await m.answer('🎥 Теперь отправь ссылку на опубликованное видео или само видео файлом. Для каждого нового дня публикаций используй /media_video.')

@dp.message(S.payout_video, F.text | F.video)
async def media_video_activity(m,state:FSMContext):
    data=await state.get_data()
    if not data.get('video_report'): return await payout_video(m,state)
    link=(m.text or '').strip()
    if m.video: link='telegram-file:'+m.video.file_id
    if not link.startswith(('https://','http://','telegram-file:')): return await m.answer('Пришли ссылку на видео или видеофайл.')
    added=db.media_add_day(m.from_user.id,link)
    await state.clear()
    await m.answer(('✅ Видеоотчёт сохранён. ' if added else 'ℹ️ За сегодня отчёт уже есть. ')+f'Активных дней: {db.media_active_days(m.from_user.id)}/7.')

@dp.message(S.payout_video)
async def payout_video(m,state:FSMContext):
    link=(m.text or '').strip()
    if m.video: link='telegram-file:'+m.video.file_id
    if not (link.startswith(('https://','http://','telegram-file:'))): return await m.answer('Отправь ссылку на видео или видео файлом.')
    await state.update_data(payout_video=link)
    await state.set_state(S.media_payout_requisites)
    await m.answer('💳 Отправь реквизиты для выплаты (например, банк и номер телефона). Их увидит только администрация.')

@dp.message(S.media_payout_requisites)
async def media_payout_requisites(m,state:FSMContext):
    requisites=(m.text or '').strip()
    if len(requisites)<5 or len(requisites)>1000: return await m.answer('Проверь реквизиты (5–1000 символов).')
    ok,reason=payout_eligible(m.from_user.id)
    if not ok: await state.clear(); return await m.answer(reason)
    data=await state.get_data()
    pid=db.media_payout(m.from_user.id,'На рассмотрении',requisites)
    db.media_payout_evidence(pid,data['payout_channel'],data['payout_video'])
    await state.clear()
    await m.answer(f'✅ <b>Заявка #{pid} принята!</b>\n\nАдминистратор проверит канал, видео и просмотры, определит сумму и отправит решение.\n\n💰 Тариф: <b>1 000 просмотров = 50 ₽</b>.',parse_mode='HTML')
    for admin_id in db.admin_ids():
        try: await bot.send_message(admin_id,f'💸 Новая заявка на выплату #{pid}. Открой список в панели администратора.',reply_markup=markup([[InlineKeyboardButton(text='📋 Заявки на выплаты',callback_data='payout_queue')]]))
        except Exception: logging.exception('Ошибка уведомления администратора')

@dp.message(Command('media_video'))
async def media_video_cmd(m,state:FSMContext):
    current=db.media_current(m.from_user.id)
    if not current or current.get('status')!='approved': return await m.answer('Доступно только медиапартнёрам.')
    await state.set_state(S.payout_video)
    await state.update_data(video_report=True)
    await m.answer('🎬 Отправь ссылку на опубликованное сегодня видео или само видео. Один активный день учитывается один раз.')

# separate handler for activity reports, ahead of payout video handler
@dp.callback_query(F.data=='payout_queue')
async def payout_queue(c):
    if not is_owner(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    rows=db.media_pending_payouts()
    if not rows: await edit_panel(c.message,'📋 Заявок на выплату пока нет.',reply_markup=markup([[InlineKeyboardButton(text='⬅️ В панель владельца',callback_data='owner')]]))
    else:
        kb=[[InlineKeyboardButton(text=f'#{r["id"]} · ID {r["uid"]}',callback_data=f'payout_view:{r["id"]}')] for r in rows[:30]]
        await edit_panel(c.message,f'💸 <b>ЗАЯВКИ НА ВЫПЛАТУ</b>\nВ очереди: {len(rows)}\nВыбирай заявку для проверки по одной.',reply_markup=markup(kb),parse_mode='HTML')
    await c.answer()

@dp.callback_query(F.data.startswith('payout_view:'))
async def payout_view(c):
    if not is_owner(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    pid=int(c.data.split(':')[1]); r=db.media_payout_get(pid)
    if not r: return await c.answer('Заявка не найдена',show_alert=True)
    ev=db.media_payout_evidence_get(pid)
    u=db.user(r['uid']); nick=u['nick'] if u else str(r['uid'])
    txt=(f'💸 <b>ЗАЯВКА #{pid}</b>\n👤 {html.escape(nick)} | <code>{r["uid"]}</code>\n'
         f'📺 Канал: {html.escape(ev.get("channel_url", "—"))}\n'
         f'🎥 Видео: {html.escape(ev.get("video_url", "—"))}\n'
         f'💳 Реквизиты: {html.escape(r["requisites"])}\n'
         f'📅 Активных дней: {db.media_active_days(r["uid"])}\n'
         f'📌 Статус: {r["status"]}\n💰 Тариф: 1 000 просмотров = 50 ₽')
    kb=[[InlineKeyboardButton(text='✅ Одобрить / рассчитать',callback_data=f'payout_approve:{pid}')],
        [InlineKeyboardButton(text='❌ Отклонить',callback_data=f'payout_reject:{pid}')],
        [InlineKeyboardButton(text='📋 К списку',callback_data='payout_queue')]] if r['status']=='pending' else [[InlineKeyboardButton(text='📋 К списку',callback_data='payout_queue')]]
    await edit_panel(c.message,txt,parse_mode='HTML',reply_markup=markup(kb))
    await c.answer()

@dp.callback_query(F.data.startswith('payout_approve:'))
async def payout_approve(c,state:FSMContext):
    if not is_owner(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    pid=int(c.data.split(':')[1]); r=db.media_payout_get(pid)
    if not r or r['status']!='pending': return await c.answer('Заявка уже обработана',show_alert=True)
    await state.update_data(review_pid=pid)
    await state.set_state(S.payout_views)
    await c.message.answer('👁 Введи подтверждённое число просмотров (целое число). Расчёт: 1 000 просмотров = 50 ₽.')
    await c.answer()

@dp.message(S.payout_views)
async def payout_views(m,state:FSMContext):
    if not is_owner(m.from_user.id): return
    raw=(m.text or '').strip().replace(' ','')
    if not raw.isdigit(): return await m.answer('Введи число просмотров.')
    views=int(raw)
    if views>1000000000: return await m.answer('Слишком большое число.')
    data=await state.get_data()
    payout=db.media_payout_get(data.get("review_pid"))
    evidence=db.media_payout_evidence_get(data.get("review_pid"))
    if payout and evidence.get("video_url"):
        db.add_media_video_stat(payout["uid"],evidence["video_url"],views,m.from_user.id)
    amount=views*0.05
    await state.update_data(views=views)
    await state.set_state(S.payout_amount)
    await m.answer(f'📊 Расчёт по тарифу: {amount:.2f} ₽.\nНапиши итоговую сумму выплаты в рублях (администратор может скорректировать её).')

@dp.message(S.payout_amount)
async def payout_amount(m,state:FSMContext):
    if not is_owner(m.from_user.id): return
    try: amount=float((m.text or '').strip().replace(',','.'))
    except ValueError: return await m.answer('Введи сумму числом.')
    if amount<0 or amount>10000000: return await m.answer('Некорректная сумма.')
    await state.update_data(approved_amount=f'{amount:.2f} RUB')
    await state.set_state(S.payout_note)
    await m.answer('✍️ Напиши текст решения для медиапартнёра. После этого заявка будет одобрена. Деньги переводи вручную по реквизитам.')

@dp.message(S.payout_note)
async def payout_note(m,state:FSMContext):
    if not is_owner(m.from_user.id): return
    note=(m.text or '').strip()
    if not note: return await m.answer('Напиши текст решения.')
    data=await state.get_data(); pid=data['review_pid']; r=db.media_payout_get(pid)
    if not r or r['status']!='pending': await state.clear(); return await m.answer('Заявка уже обработана.')
    if data.get('reject'):
        db.media_payout_review(pid,'rejected',m.from_user.id,note[:1500])
        db.add_notification(r['uid'],f'Выплата #{pid} отклонена',note[:1000])
        await state.clear()
        await m.answer(f'❌ Заявка #{pid} отклонена.')
        try: await bot.send_message(r['uid'],f'❌ <b>ВЫПЛАТА ОТКЛОНЕНА</b>\n\n📝 {html.escape(note)}',parse_mode='HTML')
        except Exception: logging.exception('Не удалось отправить отказ')
        return
    db.media_payout_set_amount(pid,data['approved_amount'])
    db.media_payout_review(pid,'approved',m.from_user.id,note[:1500])
    db.add_notification(r["uid"], f"Выплата #{pid} одобрена", "Сумма: " + str(data["approved_amount"]) + ". " + note[:700])
    await state.clear()
    await m.answer(f'✅ Заявка #{pid} одобрена. Сумма: {data["approved_amount"]}. После фактического перевода отметь выплату.',reply_markup=markup([[InlineKeyboardButton(text='💸 Отметить отправку денег',callback_data=f'mpaid:{pid}')]]))
    try: await bot.send_message(r['uid'],f'🎉 <b>ВЫПЛАТА ОДОБРЕНА!</b>\n\n💰 Сумма: <b>{data["approved_amount"]}</b>\n📝 {html.escape(note)}\n\n⏳ Ожидай фактического перевода.',parse_mode='HTML')
    except Exception: logging.exception('Не удалось уведомить медиапартнёра')

@dp.callback_query(F.data.startswith('payout_reject:'))
async def payout_reject(c,state:FSMContext):
    if not is_owner(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    pid=int(c.data.split(':')[1]); r=db.media_payout_get(pid)
    if not r or r['status']!='pending': return await c.answer('Заявка уже обработана',show_alert=True)
    await state.update_data(review_pid=pid)
    await state.set_state(S.payout_note)
    await state.update_data(reject=True)
    await c.message.answer('❌ Напиши причину отказа для медиапартнёра.')
    await c.answer()

@dp.callback_query(F.data.startswith('mpaid:'))
async def media_payout_paid(c):
    if not is_owner(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    pid=int(c.data.split(':')[1]); r=db.media_payout_get(pid)
    if not r or r['status']!='approved': return await c.answer('Сначала одобри заявку.',show_alert=True)
    db.media_payout_review(pid,'paid',c.from_user.id,r.get('review_note') or '')
    db.add_notification(r['uid'],f'Выплата #{pid} отправлена',f"Перевод на сумму {r['amount']} отмечен администрацией как выполненный.")
    try: await bot.send_message(r['uid'],f'💸 <b>ВЫПЛАТА ОТПРАВЛЕНА!</b>\n\nАдминистрация отметила перевод по заявке #{pid} на сумму <b>{html.escape(r["amount"])}</b>.',parse_mode='HTML')
    except Exception: logging.exception('Не удалось уведомить о выплате')
    await c.message.edit_reply_markup(reply_markup=None)
    await c.answer('Выплата отмечена')

@dp.callback_query(F.data.startswith("mok:"))
async def mok(c):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    a=db.media_get(int(c.data.split(":")[1]))
    if not a or a.get("status") != "pending": return await c.answer("Заявка уже обработана или не найдена.",show_alert=True)
    db.media_status(int(c.data.split(":")[1]),"approved")
    if a:
        db.add_notification(a["uid"],"Заявка в медиапартнёры одобрена","Тебе открыт доступ к кабинету медиапартнёра.")
        try: await bot.send_message(a["uid"],"🎉 Твоя заявка в медиапартнёры FENIX ONLINE одобрена!")
        except: pass
    await c.message.edit_reply_markup(reply_markup=None); await c.answer("Одобрено")
@dp.callback_query(F.data.startswith("mno:"))
async def mno(c):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    aid=int(c.data.split(":")[1]); a=db.media_get(aid)
    if not a or a.get("status") != "pending": return await c.answer("Заявка уже обработана или не найдена.",show_alert=True)
    db.media_status(aid,"rejected")
    if a:
        db.add_notification(a["uid"],"Заявка в медиапартнёры отклонена","Администрация рассмотрела заявку. При необходимости можно подать её повторно.")
        try: await bot.send_message(a["uid"],"Заявка в медиапартнёры отклонена.")
        except: pass
    await c.message.edit_reply_markup(reply_markup=None); await c.answer("Отклонено")
@dp.callback_query(F.data=="button_emoji_setup")
async def button_emoji_setup(c, state: FSMContext):
    if not is_owner(c.from_user.id):
        return await c.answer("Только владелец может менять Premium Emoji.", show_alert=True)
    await state.set_state(S.button_emoji)
    await edit_panel(
        c.message,
        "💎 <b>PREMIUM EMOJI ДЛЯ ВСЕХ КНОПОК</b>\n\n"
        "Отправь следующим сообщением один Premium Custom Emoji. "
        "Он будет автоматически добавлен ко всем кнопкам бота.\n\n"
        "Отключить: /clearbuttonemoji",
        parse_mode="HTML"
    )
    await c.answer()

@dp.callback_query(F.data=="owner")
async def owner(c):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    await edit_panel(c.message, "⚙️ ПАНЕЛЬ ВЛАДЕЛЬЦА", reply_markup=markup([
        [InlineKeyboardButton(text="📣 Опубликовать пост",callback_data="post")],
        [InlineKeyboardButton(text="📨 Рассылка",callback_data="broadcast")],
        [InlineKeyboardButton(text="💸 Заявки на выплаты",callback_data="payout_queue")],
        [InlineKeyboardButton(text="🎫 Обращения игроков",callback_data="ticket_queue")],
        [InlineKeyboardButton(text="🎨 Кастомизация бота",callback_data="customize")],
        [InlineKeyboardButton(text="👥 Составы и чаты",callback_data="staff_setup")],
        [InlineKeyboardButton(text="📈 Общая статистика",callback_data="ostats")],
        [InlineKeyboardButton(text="💰 Выручка и продажи",callback_data="owner_revenue")],
        [InlineKeyboardButton(text="🎁 Подарить подарок · списать Stars",callback_data="tgs:admin")],
        [InlineKeyboardButton(text="📊 Финансы Fenix Stars",callback_data="tgs:adminstats")],
        [InlineKeyboardButton(text="🎟 Управление промокодами",callback_data="tgs:promos")],
        [InlineKeyboardButton(text="👮 Управление администраторами",callback_data="admins_manage")],
        [InlineKeyboardButton(text="🛡️ Чат-менеджер",callback_data="chat_manager_admin")],
        [InlineKeyboardButton(text="💎 Premium Emoji для всех кнопок",callback_data="button_emoji_setup")]
    ]))
    await c.answer()

@dp.callback_query(F.data=="ticket_queue")
async def ticket_queue(c):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    await c.answer()
    rows=db.open_tickets(30)
    if not rows:
        return await edit_panel(c.message,"🎫 Открытых обращений нет.",reply_markup=markup([[InlineKeyboardButton(text="⬅️ В панель владельца",callback_data="owner")]]))
    kb=[[InlineKeyboardButton(text=f"#{r['id']} · ID {r['uid']} · {str(r['subject'])[:28]}",callback_data=f"ticket_view:{r['id']}")] for r in rows]
    await edit_panel(c.message,"🎫 <b>ОБРАЩЕНИЯ ИГРОКОВ</b>\nВыбери обращение:",parse_mode="HTML",reply_markup=markup(kb))

@dp.callback_query(F.data=="admins_manage")
async def admins_manage(c):
    # Панель владельца доступна is_admin(), поэтому раздел использует ту же проверку.
    if not is_admin(c.from_user.id):
        return await c.answer("Нет доступа к управлению администраторами.",show_alert=True)
    try:
        ids=db.admin_ids()
        text="👮 УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ\n\n"
        text += "\n".join(
            f"• {db.staff_display(uid)}\n  Должность: {db.staff_role(uid, 'admin') or 'Администратор'}"
            for uid in ids
        ) if ids else "Администраторов пока нет."
        await edit_panel(c.message,text,reply_markup=markup([
            [InlineKeyboardButton(text="➕ Добавить администратора",callback_data="admin_add")],
            [InlineKeyboardButton(text="➖ Снять администратора",callback_data="admin_remove")],
            [InlineKeyboardButton(text="⬅️ В панель владельца",callback_data="owner")]
        ]))
        await c.answer()
    except Exception:
        logging.exception("Ошибка открытия управления администраторами")
        await c.answer("Не удалось открыть раздел. Подробности записаны в лог Render.",show_alert=True)

@dp.callback_query(F.data=="admin_add")
async def admin_add_start(c,state:FSMContext):
    if not is_admin(c.from_user.id):
        return await c.answer("Нет доступа.",show_alert=True)
    await state.set_state(S.admin_add)
    await edit_panel(c.message,"Отправь Telegram ID нового администратора. Узнать ID можно командой /id.")
    await c.answer()

@dp.message(S.admin_add)
async def admin_add_finish(m,state:FSMContext):
    if not is_owner(m.from_user.id):
        await state.clear()
        return await m.answer("Нет доступа.")
    raw=(m.text or "").strip()
    if not raw.isdigit():
        return await m.answer("Нужен числовой Telegram ID. Попробуй ещё раз или /cancel.")
    uid=int(raw)
    if uid<=0: return await m.answer("Некорректный ID.")
    if not db.user(uid):
        return await m.answer("Этот человек ещё не зарегистрировался в боте. Пусть сначала нажмёт /start, затем повтори.")
    added=db.add_admin(uid,m.from_user.id)
    await state.clear()
    await m.answer("✅ Администратор добавлен." if added else "Этот пользователь уже администратор.")
    try: await bot.send_message(uid,"👮 Тебе выданы права администратора FENIX ONLINE.")
    except: pass

@dp.callback_query(F.data=="admin_remove")
async def admin_remove_start(c,state:FSMContext):
    if not is_admin(c.from_user.id):
        return await c.answer("Нет доступа.",show_alert=True)
    await state.set_state(S.admin_remove)
    await edit_panel(c.message,"Отправь Telegram ID администратора, которого нужно снять.")
    await c.answer()

@dp.message(S.admin_remove)
async def admin_remove_finish(m,state:FSMContext):
    if not is_owner(m.from_user.id):
        await state.clear()
        return await m.answer("Нет доступа.")
    raw=(m.text or "").strip()
    if not raw.isdigit(): return await m.answer("Нужен числовой Telegram ID. Попробуй ещё раз или /cancel.")
    uid=int(raw)
    if uid in OWNER_IDS:
        await state.clear()
        return await m.answer("Основного владельца нельзя снять через эту панель.")
    removed=db.remove_admin(uid)
    await state.clear()
    await m.answer("✅ Права администратора сняты." if removed else "Такого администратора нет.")
    if removed:
        try: await bot.send_message(uid,"Ваши права администратора FENIX ONLINE были сняты.")
        except: pass

@dp.message(Command("chatid"))
async def show_chat_ids(m):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔ Нет доступа.")
    await m.answer(
        "🔎 <b>ДАННЫЕ ЧАТА</b>\n"
        f"Тип: <code>{html.escape(str(m.chat.type))}</code>\n"
        f"Chat ID: <code>{m.chat.id}</code>\n"
        f"Ваш Telegram ID: <code>{m.from_user.id}</code>\n"
        f"Админ-чат: <code>{html.escape(str(db.setting('admin_chat_id','—')))}</code>\n"
        f"Лидерский чат: <code>{html.escape(str(db.setting('leader_chat_id','—')))}</code>",
        parse_mode="HTML"
    )

@dp.message(Command("bind_admin_chat"))
async def bind_admin_chat(m):
    if not is_admin(m.from_user.id) or m.chat.type == "private":
        return await m.answer("Команду может выполнить администратор бота непосредственно в административном групповом чате.")
    db.set_setting("admin_chat_id", str(m.chat.id))
    await m.answer("✅ Этот чат назначен административным. Здесь доступны команды управления администрацией.")

@dp.message(Command("bind_leader_chat"))
async def bind_leader_chat(m):
    if not is_admin(m.from_user.id) or m.chat.type == "private":
        return await m.answer("Команду может выполнить администратор бота непосредственно в лидерском групповом чате.")
    db.set_setting("leader_chat_id", str(m.chat.id))
    await m.answer("✅ Этот чат назначен лидерским. Здесь доступны команды управления лидерами.")

@dp.message(Command("nnick"))
async def set_staff_title(m):
    kind = staff_chat_kind(m.chat.id)
    if kind not in {"admin", "leader"}:
        return await m.answer("Эта команда работает только в привязанном административном или лидерском чате.")
    if not can_manage_chat(m, kind):
        return await m.answer("⛔ Недостаточно прав для изменения должностей.")
    parts = (m.text or "").split(maxsplit=2)
    if len(parts) < 3:
        return await m.answer("Формат: /nnick Игровой_ник Название должности\nПример: /nnick Fenix_Rudcov Спец. администратор")
    nick, title = parts[1].strip(), parts[2].strip()
    if len(title) > 80:
        return await m.answer("Название должности не должно превышать 80 символов.")
    user = db.user_by_nick(nick)
    if not user:
        return await m.answer("Игрок с таким ником не найден. Он должен сначала запустить бота и зарегистрироваться.")
    db.set_staff_role(user["uid"], kind, title, m.from_user.id)
    if kind == "admin": db.add_admin(user["uid"], m.from_user.id)
    await m.answer(
        "✅ <b>ДОЛЖНОСТЬ НАЗНАЧЕНА</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🎮 Игрок: <b>{html.escape(str(user.get('nick') or 'Без ника'))}</b>\n"
        f"🏅 Должность: <b>{html.escape(str(title))}</b>\n"
        "━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML"
    )
    try: await bot.send_message(user["uid"], f"🎖 Вам назначена должность: {title}")
    except Exception: pass

@dp.message(Command("stafflist"))
async def staff_list(m):
    kind = staff_chat_kind(m.chat.id)
    if kind is None:
        return await m.answer("⛔ Эта команда доступна только в привязанном чате состава.")

    rows = db.staff_list(kind)
    is_admin_roster = kind == "admin"
    heading = "👮‍♂️ СОСТАВ АДМИНИСТРАЦИИ" if is_admin_roster else "👑 СОСТАВ ЛИДЕРОВ"
    divider = "━━━━━━━━━━━━━━━━━━"

    if not rows:
        return await m.answer(
            f"{heading}\n{divider}\n\n"
            "Пока список пуст.\n\n"
            "➕ Добавить игрока:\n"
            "<code>/nnick ИгровойНик Должность</code>",
            parse_mode="HTML"
        )

    lines = []
    for i, row in enumerate(rows, 1):
        user = db.user(row["uid"]) or {}
        nick = html.escape(str(user.get("nick") or "Игровой ник не указан"))
        raw_username = user.get("username")
        username = "@" + html.escape(str(raw_username).lstrip("@")) if raw_username else "Не указан"
        title = html.escape(str(row.get("title") or ("Администратор" if is_admin_roster else "Лидер")))
        uid = html.escape(str(row["uid"]))
        lines.append(
            f"<b>{i}. 🎮 {nick}</b>\n"
            f"   👤 Telegram: {username}\n"
            f"   🏅 Должность: <b>{title}</b>\n"
            f"   🆔 ID: <code>{uid}</code>"
        )

    footer = (
        f"\n{divider}\n"
        f"👥 Всего в составе: <b>{len(rows)}</b>\n\n"
        "🛠 Управление составом:\n"
        "<code>/nnick ИгровойНик Должность</code> — добавить или изменить\n"
        "<code>/staffremove ИгровойНик</code> — снять должность"
    )
    await m.answer(
        f"{heading}\n{divider}\n\n" + "\n\n".join(lines) + footer,
        parse_mode="HTML"
    )


@dp.message(Command("staffhelp"))
async def staff_help(m):
    kind = staff_chat_kind(m.chat.id)
    if kind is None:
        return await m.answer("⛔ Сначала привяжите эту группу командой /bind_admin_chat или /bind_leader_chat.")

    await m.answer(
        "📋 <b>УПРАВЛЕНИЕ СОСТАВОМ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "➕ <b>Добавить игрока / изменить должность</b>\n"
        "<code>/nnick ИгровойНик Должность</code>\n\n"
        "📋 <b>Посмотреть весь состав</b>\n"
        "<code>/stafflist</code>\n\n"
        "➖ <b>Снять игрока с должности</b>\n"
        "<code>/staffremove ИгровойНик</code>\n\n"
        "🆔 <b>Узнать ID группы</b>\n"
        "<code>/chatid</code>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Пример:\n"
        "<code>/nnick Fenix_Rudcov Главный администратор</code>",
        parse_mode="HTML"
    )

@dp.message(Command("staffremove"))
async def staff_remove(m):
    kind = staff_chat_kind(m.chat.id)
    if kind is None or not can_manage_chat(m, kind): return await m.answer("⛔ Нет доступа или чат не привязан.")
    parts=(m.text or "").split(maxsplit=1)
    if len(parts)<2: return await m.answer("Формат: /staffremove Игровой_ник")
    user=db.user_by_nick(parts[1].strip())
    if not user: return await m.answer("Игрок не найден.")
    db.remove_staff_role(user["uid"],kind)
    if kind == "admin" and user["uid"] not in OWNER_IDS: db.remove_admin(user["uid"])
    await m.answer(
        "✅ <b>ДОЛЖНОСТЬ СНЯТА</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🎮 Игрок: <b>{html.escape(str(user.get('nick') or 'Без ника'))}</b>\n"
        "━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "staff_setup")
async def staff_setup(c):
    if not is_owner(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    admin_id=db.setting("admin_chat_id","")
    leader_id=db.setting("leader_chat_id","")
    text=(
        "👥 <b>УПРАВЛЕНИЕ СОСТАВАМИ И ЧАТАМИ</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"🛡 <b>Административный чат:</b> {'✅ Привязан' if admin_id else '⚪ Не привязан'}\n"
        f"<code>{html.escape(str(admin_id) if admin_id else '—')}</code>\n\n"
        f"👑 <b>Лидерский чат:</b> {'✅ Привязан' if leader_id else '⚪ Не привязан'}\n"
        f"<code>{html.escape(str(leader_id) if leader_id else '—')}</code>\n"
        "━━━━━━━━━━━━━━━━━━\n📌 <b>ПОДКЛЮЧЕНИЕ</b>\n"
        "1. Добавь бота в нужную группу.\n"
        "2. В админ-чате выполни /bind_admin_chat.\n"
        "3. В лидерском чате выполни /bind_leader_chat.\n"
        "━━━━━━━━━━━━━━━━━━\n⌨️ <b>КОМАНДЫ СОСТАВА</b>\n"
        "/nnick ИгровойНик Должность — назначить\n/stafflist — список состава\n/staffremove ИгровойНик — снять должность"
    )
    await edit_panel(c.message,text,parse_mode="HTML",reply_markup=markup([
        [InlineKeyboardButton(text="🔄 Обновить статус чатов",callback_data="staff_setup")],
        [InlineKeyboardButton(text="↩️ В панель владельца",callback_data="owner")]
    ]))
    await c.answer()

CUSTOM_LABELS={"cab":("cab_label","👤 Личный кабинет"),"ref":("ref_label","🔗 Реферальная ссылка"),"stats":("stats_label","📊 Статистика"),"top":("top_label","🏆 Рейтинг"),"media":("media_label","🤝 Стать медиапартнёром"),"owner":("owner_label","⚙️ Панель владельца"),"home":("home_label","📢 Новости FENIX ONLINE")}
@dp.callback_query(F.data == "customize")
async def customize(c):
    if not is_owner(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    rows=[[InlineKeyboardButton(text=label,callback_data=f'custom_pick:{key}')] for key,(_,label) in CUSTOM_LABELS.items()]
    await edit_panel(c.message,'🎨 <b>КАСТОМИЗАЦИЯ КНОПОК</b>\n\nВыбери кнопку, название которой хочешь изменить:',parse_mode='HTML',reply_markup=markup(rows))
    await c.answer()

@dp.callback_query(F.data.startswith('custom_pick:'))
async def custom_pick(c,state:FSMContext):
    if not is_owner(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    key=c.data.split(':')[1]
    if key not in CUSTOM_LABELS: return await c.answer('Неизвестная кнопка',show_alert=True)
    setting,default=CUSTOM_LABELS[key]
    await state.update_data(custom_key=key)
    await state.set_state(S.customize_label)
    await edit_panel(c.message,f'✏️ Текущее название: {db.setting(setting,default)}\n\nОтправь новое название (до 64 символов, можно с эмодзи).')
    await c.answer()

@dp.message(S.customize_label)
async def custom_label_save(m,state:FSMContext):
    if not is_owner(m.from_user.id): return
    label=(m.text or '').strip()
    if not label or len(label)>64: return await m.answer('Название должно содержать 1–64 символа.')
    data=await state.get_data(); key=data['custom_key']
    db.set_setting(CUSTOM_LABELS[key][0],label)
    await state.clear()
    await m.answer('✅ Название сохранено. Открой /start, чтобы увидеть обновлённое меню.')

@dp.message(Command("setlabel"))
async def setlabel(m):
    if not is_owner(m.from_user.id): return await m.answer("Только владелец может менять названия кнопок.")
    parts=(m.text or "").split(maxsplit=2)
    if len(parts)<3: return await m.answer("Формат: /setlabel cab 👤 Личный кабинет\nКлючи: cab, ref, stats, top, media")
    keys={"cab":"cab_label","ref":"ref_label","stats":"stats_label","top":"top_label","media":"media_label"}
    key=parts[1].lower()
    if key not in keys: return await m.answer("Неизвестный ключ. Используй: cab, ref, stats, top, media")
    db.set_setting(keys[key],parts[2][:64])
    await m.answer("✅ Название кнопки обновлено.")

@dp.callback_query(F.data=="owner_revenue")
async def owner_revenue(c):
    if not is_owner(c.from_user.id):
        return await c.answer("Только владелец может просматривать финансовую статистику.",show_alert=True)
    ph=db._ph()
    paid=db._one("SELECT COUNT(*) AS n, COALESCE(SUM(rub_amount),0) AS rub, COALESCE(SUM(fnz_amount),0) AS nmz FROM donations WHERE status='paid'") or {}
    pending=db._one("SELECT COUNT(*) AS n, COALESCE(SUM(rub_amount),0) AS rub, COALESCE(SUM(fnz_amount),0) AS nmz FROM donations WHERE status='pending'") or {}
    sales=db._one("SELECT COUNT(*) AS n, COALESCE(SUM(price_fnz),0) AS nmz FROM shop_orders") or {}
    delivered=db._one("SELECT COUNT(*) AS n, COALESCE(SUM(price_fnz),0) AS nmz FROM shop_orders WHERE status='delivered'") or {}
    text=("💰 <b>ФИНАНСЫ</b>\n\n"
          f"Подтверждённые пополнения: <b>{int(paid.get('n') or 0)}</b>\n"
          f"Получено по заявкам: <b>{float(paid.get('rub') or 0):.2f} ₽</b>\n"
          f"Начислено игрокам: <b>{int(paid.get('nmz') or 0)} FNZ</b>\n\n"
          f"Ожидают решения: <b>{int(pending.get('n') or 0)}</b>\n"
          f"Ожидаемая сумма: <b>{float(pending.get('rub') or 0):.2f} ₽</b> / {int(pending.get('nmz') or 0)} FNZ\n\n"
          f"Оплачено заказов магазина: <b>{int(sales.get('n') or 0)}</b> на {int(sales.get('nmz') or 0)} FNZ\n"
          f"Отмечено выданными: <b>{int(delivered.get('n') or 0)}</b> на {int(delivered.get('nmz') or 0)} FNZ")
    await edit_panel(c.message,text,reply_markup=markup([[InlineKeyboardButton(text="⬅️ В панель владельца",callback_data="owner")]]),parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data=="ostats")
async def ostats(c):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    await edit_panel(c.message,f"Пользователей: {db.users_total()}\nРеферальных регистраций: {db.refs_total()}\nЗаявок медиа: {db.media_total()}",reply_markup=markup([[InlineKeyboardButton(text="⬅️ В панель владельца",callback_data="owner")]])); await c.answer()
@dp.callback_query(F.data=="post")
async def post(c,state:FSMContext):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    await state.clear()
    await state.update_data(compose_mode="post")
    await state.set_state(S.post_text)
    await c.message.answer("📣 Пришли обычный текст публикации. HTML-теги не нужны.")
    await c.answer()

@dp.message(S.post_text)
async def posttext(m,state:FSMContext):
    if not is_admin(m.from_user.id): return
    if not (m.text or "").strip():
        return await m.answer("Пришли текстовое сообщение.")
    await state.update_data(text=m.text)
    await state.set_state(S.post_photo_choice)
    await m.answer("🖼 Добавить фотографию?", reply_markup=markup([
        [InlineKeyboardButton(text="✅ Да", callback_data="compose:photo:yes"),
         InlineKeyboardButton(text="❌ Нет", callback_data="compose:photo:no")]
    ]))

@dp.callback_query(F.data.startswith("compose:photo:"))
async def compose_photo_choice(c,state:FSMContext):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    choice=c.data.rsplit(":",1)[1]
    if choice=="yes":
        await state.set_state(S.post_photo)
        await c.message.answer("Отправь фотографию одним сообщением.")
    else:
        await state.update_data(photo=None)
        await state.set_state(S.post_button_choice)
        await c.message.answer("🔘 Добавить URL-кнопку под публикацией?", reply_markup=markup([
            [InlineKeyboardButton(text="✅ Да", callback_data="compose:button:yes"),
             InlineKeyboardButton(text="❌ Нет", callback_data="compose:button:no")]
        ]))
    await c.answer()

@dp.message(S.post_photo)
async def postphoto(m,state:FSMContext):
    if not is_admin(m.from_user.id): return
    if not m.photo:
        return await m.answer("Пожалуйста, отправь именно фотографию.")
    await state.update_data(photo=m.photo[-1].file_id)
    await state.set_state(S.post_button_choice)
    await m.answer("🔘 Добавить URL-кнопку под публикацией?", reply_markup=markup([
        [InlineKeyboardButton(text="✅ Да", callback_data="compose:button:yes"),
         InlineKeyboardButton(text="❌ Нет", callback_data="compose:button:no")]
    ]))

@dp.callback_query(F.data.startswith("compose:button:"))
async def compose_button_choice(c,state:FSMContext):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    choice=c.data.rsplit(":",1)[1]
    if choice=="yes":
        await state.set_state(S.post_button)
        await c.message.answer("Напиши текст кнопки. Например: 🎮 Перейти в игру")
    else:
        await state.update_data(bt=None,bu=None)
        await finish_composition(c.message,state,c.from_user.id)
    await c.answer()

@dp.message(S.post_button)
async def postbutton(m,state:FSMContext):
    if not is_admin(m.from_user.id): return
    label=(m.text or "").strip()
    if not label: return await m.answer("Напиши текст кнопки.")
    if len(label)>64: return await m.answer("Текст кнопки должен быть не длиннее 64 символов.")
    await state.update_data(bt=label)
    await state.set_state(S.post_url)
    await m.answer("Теперь отправь URL кнопки, начиная с https://")

@dp.message(S.post_url)
async def posturl(m,state:FSMContext):
    if not is_admin(m.from_user.id): return
    url=(m.text or "").strip()
    if not re.match(r"^https?://\S+$",url):
        return await m.answer("Неверная ссылка. Отправь полный URL, начиная с https://")
    await state.update_data(bu=url)
    await finish_composition(m,state,m.from_user.id)

def split_message(text,limit=4000):
    text=text or " "
    chunks=[]
    while len(text)>limit:
        cut=text.rfind("\n",0,limit)
        if cut<limit//2: cut=limit
        chunks.append(text[:cut])
        text=text[cut:].lstrip("\n")
    if text: chunks.append(text)
    return chunks

POST_FOOTER_HTML = (
    "━━━━━━━━━━━━━━━━━━\n<b>🔥 FENIX ONLINE</b>\n"
    "<i>Твой проект. Твои возможности.</i>\n\n"
    "🛡 <b>VPN:</b> @fenixVPNrobot\n"
    "⭐ <b>Stars:</b> @Fenix_stars_bot\n"
    '💬 <b>Форум:</b> <a href="http://forum.wh35740.web1.maze-tech.ru/index.php">Открыть форум</a>'
)
POST_SIGNATURE_HTML = f"<blockquote>{POST_FOOTER_HTML}</blockquote>"

def _post_emoji_items():
    return [
        item for item in _load_emoji_pack()
        if isinstance(item, dict) and str(item.get("id", "")).isdigit()
        and str(item.get("emoji", "")).strip()
    ]

def _decorate_post_html(content):
    """Распределяет несколько Custom Emoji по абзацам, не меняя текст публикации."""
    content = str(content or "").strip()
    items = _post_emoji_items()
    if not content or not items:
        return content
    lines = content.split("\n")
    candidates = [i for i, line in enumerate(lines) if line.strip()]
    if not candidates:
        return content
    count = min(len(candidates), random.randint(2, 4))
    chosen = set(random.sample(candidates, count))
    for index in sorted(chosen, reverse=True):
        item = random.choice(items)
        emoji = html.escape(str(item.get("emoji") or "✨"), quote=False)
        emoji_id = html.escape(str(item["id"]), quote=True)
        lines[index] = f'<tg-emoji emoji-id="{emoji_id}">{emoji}</tg-emoji> ' + lines[index]
    return "\n".join(lines)

def _plain_post_fallback(content):
    return re.sub(r'<tg-emoji\s+emoji-id="[^"]+">([^<]+)</tg-emoji>', r'\1', content)

def _build_post_html(raw):
    author = _decorate_post_html(html.escape((raw or "").strip()))
    return (author + "\n\n" if author else "") + POST_SIGNATURE_HTML

async def _send_post_payload(chat_id, photo, text, keyboard=None):
    """Try Premium Custom Emoji first; if Telegram disallows them, publish readable fallback."""
    try:
        if photo and len(text) <= 1024:
            return await bot.send_photo(chat_id, photo, caption=text, reply_markup=keyboard, parse_mode="HTML")
        if photo:
            await bot.send_photo(chat_id, photo)
        return await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=keyboard)
    except Exception:
        if "<tg-emoji " not in text:
            raise
        logging.warning("Telegram не разрешил Custom Emoji в публикации; отправляю обычные emoji")
        fallback = _plain_post_fallback(text)
        if photo and len(fallback) <= 1024:
            return await bot.send_photo(chat_id, photo, caption=fallback, reply_markup=keyboard, parse_mode="HTML")
        if photo:
            await bot.send_photo(chat_id, photo)
        return await bot.send_message(chat_id, fallback, parse_mode="HTML", reply_markup=keyboard)

async def send_composed(chat_id,data):
    """Любая публикация FENIX получает фирменную подпись и аккуратные emoji."""
    keyboard=None
    if data.get("bt") and data.get("bu"):
        keyboard=markup([[InlineKeyboardButton(text=data["bt"],url=data["bu"])]])
    raw=(data.get("text") or "").strip()
    text=_build_post_html(raw)
    photo=data.get("photo")
    if len(text) <= (1024 if photo else 4096):
        await _send_post_payload(chat_id, photo, text, keyboard)
        return
    if photo:
        await bot.send_photo(chat_id, photo)
    chunks=split_message(raw)
    for i,chunk in enumerate(chunks):
        body=_decorate_post_html(html.escape(chunk))
        if i==len(chunks)-1:
            body += "\n\n" + POST_SIGNATURE_HTML
        try:
            await bot.send_message(chat_id, body, parse_mode="HTML",
                reply_markup=keyboard if i==len(chunks)-1 else None)
        except Exception:
            if "<tg-emoji " not in body:
                raise
            await bot.send_message(chat_id, _plain_post_fallback(body), parse_mode="HTML",
                reply_markup=keyboard if i==len(chunks)-1 else None)

@dp.channel_post()
async def auto_style_channel_post(message: Message):
    """Оформляет посты, опубликованные администраторами канала не через бота."""
    if not CHANNEL or str(message.chat.id) != str(CHANNEL):
        return
    current = message.html_text or message.html_caption or message.text or message.caption or ""
    if "FENIX ONLINE" in current and "fenixVPNrobot" in current:
        return
    decorated = _decorate_post_html(current)
    final_text = (decorated + "\n\n" if decorated else "") + POST_SIGNATURE_HTML
    try:
        if message.text is not None:
            await message.edit_text(final_text, parse_mode="HTML")
        else:
            await message.edit_caption(caption=final_text, parse_mode="HTML")
    except Exception as exc:
        if "<tg-emoji " in final_text:
            try:
                fallback = _plain_post_fallback(final_text)
                if message.text is not None:
                    await message.edit_text(fallback, parse_mode="HTML")
                else:
                    await message.edit_caption(caption=fallback, parse_mode="HTML")
                logging.warning("Channel post %s styled with standard emoji fallback", message.message_id)
                return
            except Exception:
                logging.exception("Не удалось применить fallback для channel post %s", message.message_id)
        logging.exception("Не удалось автоматически оформить channel post %s: %s", message.message_id, exc)

async def _broadcast_worker(data, initiator):
    ids=db.user_ids()
    sem=asyncio.Semaphore(8)
    sent=0
    failed=0
    async def deliver(target_id):
        nonlocal sent, failed
        async with sem:
            try:
                await send_composed(target_id,data)
                sent += 1
            except Exception:
                failed += 1
                logging.exception("Ошибка рассылки пользователю %s",target_id)
            await asyncio.sleep(0.04)
    await asyncio.gather(*(deliver(uid) for uid in ids))
    try:
        await bot.send_message(initiator,f"✅ <b>Рассылка завершена</b>\nДоставлено: {sent}\nНе доставлено: {failed}",parse_mode="HTML")
    except Exception: logging.exception("Не удалось отправить итог рассылки")


async def finish_composition(message,state,uid):
    data=await state.get_data()
    mode=data.get("compose_mode","post")
    try:
        if mode=="post":
            await send_composed(CHANNEL,data)
            await message.answer("✅ Публикация отправлена в канал.")
        else:
            asyncio.create_task(_broadcast_worker(data.copy(),uid))
            await message.answer("🚀 Рассылка поставлена в очередь. Бот продолжит обслуживать команды, а результат придёт отдельным сообщением.")
    except Exception as e:
        logging.exception("Ошибка отправки публикации/рассылки")
        await message.answer("❌ Ошибка отправки: "+str(e)[:800])
    await state.clear()

@dp.callback_query(F.data=="broadcast")
async def broadcast(c,state:FSMContext):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    await state.clear()
    await state.update_data(compose_mode="broadcast")
    await state.set_state(S.post_text)
    await c.message.answer("📨 Пришли текст рассылки. Можно добавить фото и URL-кнопку — бот предложит выбор Да/Нет.")
    await c.answer()

@dp.callback_query(F.data=="editbutton")
async def editbutton(c,state:FSMContext):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    await state.set_state(S.button_label); await c.message.answer("Введи новый текст кнопки главного меню."); await c.answer()
@dp.message(S.button_label)
async def buttonlabel(m,state:FSMContext):
    await state.update_data(label=m.text); await state.set_state(S.button_url); await m.answer("Теперь пришли URL кнопки.")
@dp.message(S.button_url)
async def buttonurl(m,state:FSMContext):
    if not is_admin(m.from_user.id): return
    u=(m.text or "").strip()
    if not u.startswith(("https://","http://")): return await m.answer("Неверный URL.")
    d=await state.get_data(); db.set_setting("home_label",d["label"]); db.set_setting("home_url",u); await state.clear(); await m.answer("✅ Кнопка меню обновлена.")
@dp.message(Command("cancel"))
async def cancel(m,state:FSMContext):
    await state.clear(); await m.answer("↩️ Действие отменено. Главное меню:",reply_markup=menu(m.from_user.id))
async def health(request):
    return web.json_response({"status": "ok", "service": "fenix-online-bot"})

async def start_health_server():
    # Render Web Service требует слушающий HTTP-порт.
    port = int(os.getenv("PORT", "10000"))
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logging.info("HTTP health server listening on 0.0.0.0:%s", port)
    return runner

async def main():
    db.init()
    from chat_manager import register_chat_manager
    register_chat_manager(dp, bot, db, OWNER_IDS)
    # Import the owner's OutlineEmoji custom-emoji pack automatically on startup.
    try:
        pack_items = []
        for pack_name in ("OutlineEmoji", "TONEmoji"):
            try:
                sticker_set = await bot.get_sticker_set(pack_name)
                pack_items.extend(
                    {"id": str(sticker.custom_emoji_id), "emoji": getattr(sticker, "emoji", None) or "💎", "pack": pack_name}
                    for sticker in sticker_set.stickers if getattr(sticker, "custom_emoji_id", None)
                )
                logging.info("Loaded %s custom emoji set", pack_name)
            except Exception:
                logging.exception("Could not load custom emoji pack %s", pack_name)
        if pack_items:
            unique = {item["id"]: item for item in pack_items}
            db.set_setting("premium_emoji_pack", json.dumps(list(unique.values()), ensure_ascii=False))
            logging.info("Loaded combined Premium Emoji pool: %s IDs", len(unique))
        else:
            logging.warning("No custom emoji IDs loaded from OutlineEmoji / TONEmoji")
    except Exception:
        logging.exception("Failed to import Premium Emoji packs; bot will continue with standard emoji")
    logging.info("Assets directory: %s | found: %s", ASSETS_DIR, sorted(p.name for p in ASSETS_DIR.glob("*") if p.is_file()))
    runner = await start_health_server()
    try:
        # Long polling Telegram запускается параллельно с HTTP health endpoint.
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types()
        )
    finally:
        await runner.cleanup()
        await bot.session.close()

if __name__ == "__main__":
    # Keep Render's existing "python bot.py" command and run the Mini App
    # HTTP server together with the existing Telegram polling process.
    import sys
    sys.modules.setdefault("bot", sys.modules[__name__])
    from miniapp import main as miniapp_main
    asyncio.run(miniapp_main())
