import asyncio, logging, os, re, secrets, hashlib
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, ChatPermissions
from pathlib import Path
from datetime import datetime, timedelta, timezone
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
OWNER_IDS=ADMINS.copy()
def is_admin(uid): return db.is_admin(uid)
def is_owner(uid): return uid in OWNER_IDS
def markup(rows): return InlineKeyboardMarkup(inline_keyboard=rows)

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
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
                return await message.answer_photo(
                    FSInputFile(str(image_path)),
                    caption=caption or None,
                    reply_markup=reply_markup
                )
            await message.answer_photo(FSInputFile(str(image_path)))
            return await message.answer(caption, reply_markup=reply_markup)
        except Exception:
            logging.exception("Не удалось отправить баннер %s", image_path)
    else:
        logging.warning("Баннер не найден: %s", image_path)
    return await message.answer(caption, reply_markup=reply_markup)

def menu(uid):
    label=db.setting("home_label","📢 Новости FENIX ONLINE")
    url=db.setting("home_url",CHANNEL_URL)
    rows=[[InlineKeyboardButton(text="👤 Личный кабинет",callback_data="cab"),
           InlineKeyboardButton(text="🔗 Моя реферальная ссылка",callback_data="ref")],
          [InlineKeyboardButton(text="📊 Статистика",callback_data="stats"),
           InlineKeyboardButton(text="🏆 Рейтинг",callback_data="top")],
          [InlineKeyboardButton(text="🤝 Стать медиапартнёром",callback_data="media")]]
    if url: rows.append([InlineKeyboardButton(text=label,url=url)])
    if is_admin(uid):
        rows.append([InlineKeyboardButton(text="⚙️ Панель администратора",callback_data="owner")])
        admin_chat_url=db.setting("admin_chat_url")
        if admin_chat_url: rows.append([InlineKeyboardButton(text="💬 Админ-чат",url=admin_chat_url)])
    return markup(rows)
class S(StatesGroup):
    nick=State(); password=State(); media_channel=State(); media_stats=State(); media_contact=State()
    post_text=State(); post_photo_choice=State(); post_photo=State()
    post_button_choice=State(); post_button=State(); post_url=State()
    button_label=State(); button_url=State(); broadcast=State(); admin_add=State(); admin_remove=State()
def hashpw(p):
    salt=secrets.token_hex(16)
    return salt+"$"+hashlib.pbkdf2_hmac("sha256",p.encode(),salt.encode(),200000).hex()
@dp.message(Command("id"))
async def cmd_id(m): await m.answer(f"Твой Telegram ID: {m.from_user.id}")
@dp.message(CommandStart())
async def start(m:Message,state:FSMContext):
    try:
        u=db.user(m.from_user.id)
        if u:
            return await answer_visual(
                m, "welcome", "🔥 FENIX ONLINE\nТвой личный кабинет.",
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
            "🔥 FENIX ONLINE — регистрация\n\nВведи игровой никнейм (3–24 символа, латиница, цифры и _)."
        )
    except Exception:
        logging.exception("Ошибка /start")
        await m.answer("Не удалось открыть бота. Попробуй ещё раз позже.")
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
    if d.get("ref") and db.user(d["ref"]): db.add_ref(d["ref"],m.from_user.id)
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
        await answer_visual(c.message, "profile",
            f"👤 ЛИЧНЫЙ КАБИНЕТ\nНик: {u['nick']}\nПриглашено: {invited}")
        await c.answer()
    except Exception:
        logging.exception("Ошибка открытия личного кабинета")
        await c.answer("Ошибка базы данных. Попробуй позже.", show_alert=True)

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
        await answer_visual(c.message, "rewards",
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
        await answer_visual(c.message, "rating", txt)
        await c.answer()
    except Exception:
        logging.exception("Ошибка рейтинга")
        await c.answer("Не удалось загрузить рейтинг.", show_alert=True)

@dp.callback_query(F.data=="media")
async def media(c,state:FSMContext):
    await state.set_state(S.media_channel)
    await answer_visual(c.message, "media", "🤝 ЗАЯВКА В МЕДИАПАРТНЁРЫ\nПришли ссылку на свой канал или площадку.")
    await c.answer()

@dp.message(S.media_channel)
async def media1(m,state:FSMContext):
    await state.update_data(ch=m.text or ""); await state.set_state(S.media_stats); await m.answer("Укажи количество подписчиков и средние просмотры.")
@dp.message(S.media_stats)
async def media2(m,state:FSMContext):
    await state.update_data(st=m.text or ""); await state.set_state(S.media_contact); await m.answer("Оставь контакт для связи.")
@dp.message(S.media_contact)
async def media3(m,state:FSMContext):
    d=await state.get_data(); aid=db.media(m.from_user.id,d["ch"],d["st"],m.text or ""); await state.clear()
    await m.answer("✅ Заявка отправлена администрации.")
    for a in db.admin_ids():
        try: await bot.send_message(a,f"🤝 Заявка медиапартнёра #{aid}\nID: {m.from_user.id}\nКанал: {d['ch']}\nАудитория: {d['st']}\nКонтакт: {m.text}",reply_markup=markup([[InlineKeyboardButton(text="Одобрить",callback_data=f"mok:{aid}"),InlineKeyboardButton(text="Отклонить",callback_data=f"mno:{aid}")]]))
        except: pass
@dp.callback_query(F.data.startswith("mok:"))
async def mok(c):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    a=db.media_get(int(c.data.split(":")[1])); db.media_status(int(c.data.split(":")[1]),"approved")
    if a:
        try: await bot.send_message(a["uid"],"🎉 Твоя заявка в медиапартнёры FENIX ONLINE одобрена!")
        except: pass
    await c.message.edit_reply_markup(reply_markup=None); await c.answer("Одобрено")
@dp.callback_query(F.data.startswith("mno:"))
async def mno(c):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    aid=int(c.data.split(":")[1]); a=db.media_get(aid); db.media_status(aid,"rejected")
    if a:
        try: await bot.send_message(a["uid"],"Заявка в медиапартнёры отклонена.")
        except: pass
    await c.message.edit_reply_markup(reply_markup=None); await c.answer("Отклонено")
@dp.callback_query(F.data=="owner")
async def owner(c):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    await answer_visual(c.message, "news", "⚙️ ПАНЕЛЬ ВЛАДЕЛЬЦА", reply_markup=markup([
        [InlineKeyboardButton(text="📣 Опубликовать пост",callback_data="post")],
        [InlineKeyboardButton(text="📨 Рассылка",callback_data="broadcast")],
        [InlineKeyboardButton(text="🎨 Настроить кнопку меню",callback_data="editbutton")],
        [InlineKeyboardButton(text="📈 Общая статистика",callback_data="ostats")],
        [InlineKeyboardButton(text="👮 Управление администраторами",callback_data="admins_manage")]
    ]))
    await c.answer()

@dp.callback_query(F.data=="admins_manage")
async def admins_manage(c):
    if not is_owner(c.from_user.id):
        return await c.answer("Управлять администраторами может только владелец.",show_alert=True)
    ids=db.admin_ids()
    text="👮 УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ\n\n"
    text += "\n".join(f"• {uid}" for uid in ids) if ids else "Администраторов пока нет."
    await c.message.answer(text,reply_markup=markup([
        [InlineKeyboardButton(text="➕ Добавить администратора",callback_data="admin_add")],
        [InlineKeyboardButton(text="➖ Снять администратора",callback_data="admin_remove")]
    ]))
    await c.answer()

@dp.callback_query(F.data=="admin_add")
async def admin_add_start(c,state:FSMContext):
    if not is_owner(c.from_user.id):
        return await c.answer("Только владелец может добавлять администраторов.",show_alert=True)
    await state.set_state(S.admin_add)
    await c.message.answer("Отправь Telegram ID нового администратора. Узнать ID можно командой /id.")
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
    if not is_owner(c.from_user.id):
        return await c.answer("Только владелец может снимать администраторов.",show_alert=True)
    await state.set_state(S.admin_remove)
    await c.message.answer("Отправь Telegram ID администратора, которого нужно снять.")
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

@dp.callback_query(F.data=="ostats")
async def ostats(c):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    await c.message.answer(f"Пользователей: {db.users_total()}\nРеферальных регистраций: {db.refs_total()}\nЗаявок медиа: {db.media_total()}"); await c.answer()
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
    if not is_admin(m.from_user.id): return await m.answer("Нет доступа к публикациям и рассылке.")
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
    if not is_admin(m.from_user.id): return await m.answer("Нет доступа к публикациям и рассылке.")
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
    if not is_admin(m.from_user.id): return await m.answer("Нет доступа к публикациям и рассылке.")
    label=(m.text or "").strip()
    if not label: return await m.answer("Напиши текст кнопки.")
    if len(label)>64: return await m.answer("Текст кнопки должен быть не длиннее 64 символов.")
    await state.update_data(bt=label)
    await state.set_state(S.post_url)
    await m.answer("Теперь отправь URL кнопки, начиная с https://")

@dp.message(S.post_url)
async def posturl(m,state:FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Нет доступа к публикациям и рассылке.")
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

async def send_composed(chat_id,data):
    """Отправляет фото и текст отдельно, если подпись превышает лимит Telegram."""
    keyboard=None
    if data.get("bt") and data.get("bu"):
        keyboard=markup([[InlineKeyboardButton(text=data["bt"],url=data["bu"]) ]])
    text=data.get("text") or " "
    photo=data.get("photo")
    if photo and len(text)<=1024:
        await bot.send_photo(chat_id,photo,caption=text,reply_markup=keyboard)
        return
    if photo:
        await bot.send_photo(chat_id,photo)
    chunks=split_message(text)
    for i,chunk in enumerate(chunks):
        await bot.send_message(chat_id,chunk,
                               reply_markup=keyboard if i==len(chunks)-1 else None)

async def finish_composition(message,state,uid):
    data=await state.get_data()
    mode=data.get("compose_mode","post")
    try:
        if mode=="post":
            await send_composed(CHANNEL,data)
            await message.answer("✅ Публикация отправлена в канал.")
        else:
            sent=0
            for target_id in db.user_ids():
                try:
                    await send_composed(target_id,data)
                    sent+=1
                except Exception:
                    logging.exception("Не удалось отправить рассылку пользователю %s",target_id)
            await message.answer(f"✅ Рассылка завершена. Доставлено: {sent}")
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
    await state.clear(); await m.answer("Отменено.",reply_markup=menu(m.from_user.id))

# -------------------- STAFF / GROUP MODERATION --------------------
def _staff_allowed(uid):
    return is_admin(uid)

def _admin_chat_id():
    value = db.setting("admin_chat_id")
    try: return int(value) if value else None
    except (TypeError, ValueError): return None

async def _group_reply(message, text, **kwargs):
    await message.reply(text, **kwargs)

@dp.message(Command("setadminchat"))
async def set_admin_chat(message: Message):
    if not is_owner(message.from_user.id):
        return await message.reply("Эту настройку может выполнить только владелец проекта.")
    if message.chat.type not in ("group", "supergroup"):
        return await message.reply("Команду нужно выполнить внутри будущего админ-чата.")
    db.set_setting("admin_chat_id", str(message.chat.id))
    try:
        invite = await bot.create_chat_invite_link(message.chat.id, name="FENIX admin chat")
        db.set_setting("admin_chat_url", invite.invite_link)
    except Exception:
        logging.exception("Не удалось создать ссылку админ-чата")
    await message.reply("✅ Этот чат назначен админ-чатом FENIX ONLINE.")

@dp.message(Command("setmodchat"))
async def set_mod_chat(message: Message):
    if not is_owner(message.from_user.id):
        return await message.reply("Эту настройку может выполнить только владелец проекта.")
    if message.chat.type not in ("group", "supergroup"):
        return await message.reply("Команду нужно выполнить в группе, где бот будет модерировать участников.")
    db.set_setting("mod_chat_id", str(message.chat.id))
    await message.reply("✅ Эта группа назначена чатом модерации. Убедись, что бот — администратор с правами блокировки участников.")

@dp.message(Command("staff"))
async def staff_request(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return await message.reply("Команда доступна в назначенном админ-чате.")
    if message.chat.id != _admin_chat_id():
        return await message.reply("Этот чат не назначен админ-чатом FENIX ONLINE.")
    if not is_owner(message.from_user.id):
        return await message.reply("Назначать сотрудников может только владелец.")
    parts=(message.text or "").split(maxsplit=2)
    if len(parts)<3:
        return await message.reply("Формат: /staff игровой_ник должность\nПример: /staff Fenix_Rudcov Старший администратор")
    nick, role=parts[1].strip(), parts[2].strip()
    target=db.user_by_nick(nick)
    if not target:
        return await message.reply("Игрок с таким ником не найден в базе бота. Он должен хотя бы один раз запустить /start.")
    uid=int(target["uid"])
    if is_admin(uid):
        return await message.reply("У этого пользователя уже есть доступ администратора.")
    db.create_staff_request(uid, nick, role, message.from_user.id)
    kb=markup([[InlineKeyboardButton(text="✅ Дать доступ к боту", callback_data=f"staff:grant:{uid}"),
                InlineKeyboardButton(text="❌ Отказать", callback_data=f"staff:deny:{uid}")]])
    await message.reply(f"🛡 Заявка на назначение\nИгровой ник: {nick}\nДолжность: {role}\nTelegram ID: {uid}\n\nВыдать доступ к административной панели?", reply_markup=kb)

@dp.callback_query(F.data.startswith("staff:"))
async def staff_decision(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Решение доступно только владельцу.", show_alert=True)
    _, action, raw_uid=call.data.split(":",2)
    uid=int(raw_uid)
    req=db.staff_request(uid)
    if not req or req["status"] != "pending":
        return await call.answer("Заявка уже обработана или не найдена.", show_alert=True)
    if action=="grant":
        db.add_admin(uid, call.from_user.id)
        db.set_staff_role(uid, req["nick"], req["role"])
        db.update_staff_request(uid,"approved")
        try: await bot.send_message(uid, f"✅ Тебе выдан доступ к панели FENIX ONLINE.\nДолжность: {req['role']}\nОткрой /start.")
        except Exception: logging.exception("Не удалось уведомить нового сотрудника %s", uid)
        result="✅ Доступ выдан. Сотрудник добавлен в администраторы."
    elif action=="deny":
        db.update_staff_request(uid,"denied")
        try: await bot.send_message(uid,"❌ Тебе отказано в доступе к административной панели FENIX ONLINE.")
        except Exception: pass
        result="❌ В доступе отказано. Права не выданы."
    else:
        return await call.answer("Неизвестное действие.", show_alert=True)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.reply(result)
    await call.answer("Готово")

@dp.message(Command("stafflist"))
async def staff_list(message: Message):
    if not is_admin(message.from_user.id): return await message.reply("Нет доступа.")
    rows=db.staff_list()
    body="\n".join(f"• {x['nick']} — {x['role']} (ID {x['uid']})" for x in rows) or "Список пока пуст."
    await message.reply("🛡 СОСТАВ FENIX ONLINE\n"+body)

def _parse_duration(raw):
    m=re.fullmatch(r"(\d+)([mhd])", raw.lower())
    if not m: return None
    n=int(m.group(1)); unit=m.group(2)
    seconds=n*{"m":60,"h":3600,"d":86400}[unit]
    return seconds if 1 <= seconds <= 366*86400 else None

async def _resolve_target(message, token=None):
    if message.reply_to_message and message.reply_to_message.from_user:
        u=message.reply_to_message.from_user
        return u.id, ("@"+u.username if u.username else str(u.id))
    if not token: return None, None
    token=token.strip()
    if token.startswith("@"):
        row=db.user_by_username(token[1:])
        if row: return int(row["uid"]), token
        return None, token
    if token.isdigit(): return int(token), token
    row=db.user_by_nick(token)
    if row: return int(row["uid"]), token
    return None, token

async def _moderation_guard(message):
    if message.chat.type not in ("group","supergroup"):
        await message.reply("Команда работает только в группе."); return False
    try: mod_chat_id=int(db.setting("mod_chat_id") or "0")
    except (TypeError, ValueError): mod_chat_id=0
    if message.chat.id != mod_chat_id:
        await message.reply("Команды модерации доступны только в назначенной группе модерации."); return False
    if not is_admin(message.from_user.id):
        await message.reply("Нет доступа к модерации."); return False
    return True

@dp.message(Command("mute"))
async def cmd_mute(message: Message):
    if not await _moderation_guard(message): return
    args=(message.text or "").split()
    token=args[1] if len(args)>1 and not message.reply_to_message else None
    duration_arg=args[2] if token and len(args)>2 else (args[1] if len(args)>1 and message.reply_to_message else "1h")
    seconds=_parse_duration(duration_arg) if duration_arg else 3600
    if seconds is None: return await message.reply("Формат срока: 10m, 2h или 1d. Максимум 366d.")
    uid,label=await _resolve_target(message,token)
    if not uid: return await message.reply("Не нашёл участника. Ответь на его сообщение или укажи Telegram ID / @username зарегистрированного игрока.")
    if uid==message.from_user.id or uid in OWNER_IDS: return await message.reply("Нельзя применить мут к себе или владельцу.")
    try:
        await bot.restrict_chat_member(message.chat.id, uid, permissions=ChatPermissions(can_send_messages=False), until_date=datetime.now(timezone.utc)+timedelta(seconds=seconds))
        await message.reply(f"🔇 Участник {label} получил мут на {duration_arg}.")
    except Exception as e:
        logging.exception("mute failed")
        await message.reply("Не удалось выдать мут. Проверь, что бот администратор с правом блокировки участников.\n"+str(e)[:400])

@dp.message(Command("unmute"))
async def cmd_unmute(message: Message):
    if not await _moderation_guard(message): return
    args=(message.text or "").split(); token=args[1] if len(args)>1 and not message.reply_to_message else None
    uid,label=await _resolve_target(message,token)
    if not uid: return await message.reply("Ответь на сообщение участника или укажи его Telegram ID / @username.")
    try:
        await bot.restrict_chat_member(message.chat.id,uid,permissions=ChatPermissions(can_send_messages=True,can_send_audios=True,can_send_documents=True,can_send_photos=True,can_send_videos=True,can_send_video_notes=True,can_send_voice_notes=True,can_send_polls=True,can_send_other_messages=True,can_add_web_page_previews=True))
        await message.reply(f"🔊 Ограничения сняты с {label}.")
    except Exception as e:
        logging.exception("unmute failed"); await message.reply("Не удалось снять мут: "+str(e)[:400])

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if not await _moderation_guard(message): return
    args=(message.text or "").split(); token=args[1] if len(args)>1 and not message.reply_to_message else None
    uid,label=await _resolve_target(message,token)
    if not uid: return await message.reply("Ответь на сообщение участника или укажи его Telegram ID / @username.")
    if uid==message.from_user.id or uid in OWNER_IDS: return await message.reply("Нельзя заблокировать себя или владельца.")
    try: await bot.ban_chat_member(message.chat.id,uid); await message.reply(f"⛔ {label} заблокирован в группе.")
    except Exception as e:
        logging.exception("ban failed"); await message.reply("Не удалось заблокировать участника: "+str(e)[:400])

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if not await _moderation_guard(message): return
    args=(message.text or "").split(); token=args[1] if len(args)>1 and not message.reply_to_message else None
    uid,label=await _resolve_target(message,token)
    if not uid: return await message.reply("Укажи Telegram ID участника.")
    try: await bot.unban_chat_member(message.chat.id,uid,only_if_banned=True); await message.reply(f"✅ Блокировка {label} снята.")
    except Exception as e:
        logging.exception("unban failed"); await message.reply("Не удалось снять блокировку: "+str(e)[:400])

@dp.message(Command("kick"))
async def cmd_kick(message: Message):
    if not await _moderation_guard(message): return
    args=(message.text or "").split(); token=args[1] if len(args)>1 and not message.reply_to_message else None
    uid,label=await _resolve_target(message,token)
    if not uid: return await message.reply("Ответь на сообщение участника или укажи его Telegram ID / @username.")
    if uid==message.from_user.id or uid in OWNER_IDS: return await message.reply("Нельзя исключить себя или владельца.")
    try:
        await bot.ban_chat_member(message.chat.id,uid)
        await bot.unban_chat_member(message.chat.id,uid,only_if_banned=True)
        await message.reply(f"👢 {label} исключён из группы. Он сможет вступить снова по ссылке.")
    except Exception as e:
        logging.exception("kick failed"); await message.reply("Не удалось исключить участника: "+str(e)[:400])

@dp.message(Command("warn"))
async def cmd_warn(message: Message):
    if not await _moderation_guard(message): return
    args=(message.text or "").split(maxsplit=2); token=args[1] if len(args)>1 and not message.reply_to_message else None
    uid,label=await _resolve_target(message,token)
    if not uid: return await message.reply("Ответь на сообщение участника или укажи Telegram ID / @username.")
    reason=(args[2] if token and len(args)>2 else (args[1] if len(args)>1 and message.reply_to_message else "Без указания причины"))
    count=db.add_warning(message.chat.id,uid,message.from_user.id,reason)
    try: await bot.send_message(uid,f"⚠️ Предупреждение в чате FENIX ONLINE. Причина: {reason}. Всего предупреждений: {count}")
    except Exception: pass
    await message.reply(f"⚠️ Предупреждение выдано {label}. Всего: {count}.")

@dp.message(Command("warns"))
async def cmd_warns(message: Message):
    if not await _moderation_guard(message): return
    args=(message.text or "").split(); token=args[1] if len(args)>1 and not message.reply_to_message else None
    uid,label=await _resolve_target(message,token)
    if not uid: return await message.reply("Ответь на сообщение участника или укажи Telegram ID / @username.")
    await message.reply(f"⚠️ У {label} предупреждений: {db.warning_count(message.chat.id,uid)}")


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
    asyncio.run(main())
