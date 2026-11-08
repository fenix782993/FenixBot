import asyncio, logging, os, re, secrets, hashlib
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
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
    rows=[[InlineKeyboardButton(text=db.setting("label_cab","👤 Личный кабинет"),callback_data="cab"),
           InlineKeyboardButton(text=db.setting("label_ref","🔗 Моя реферальная ссылка"),callback_data="ref")],
          [InlineKeyboardButton(text=db.setting("label_stats","📊 Статистика"),callback_data="stats"),
           InlineKeyboardButton(text=db.setting("label_top","🏆 Рейтинг"),callback_data="top")],
          [InlineKeyboardButton(text=db.setting("label_media","🤝 Стать медиапартнёром"),callback_data="media")]]
    if url: rows.append([InlineKeyboardButton(text=label,url=url)])
    if is_admin(uid): rows.append([InlineKeyboardButton(text="⚙️ Панель владельца",callback_data="owner")])
    return markup(rows)
class S(StatesGroup):
    nick=State(); password=State(); media_channel=State(); media_stats=State(); media_contact=State()
    post_text=State(); post_photo_choice=State(); post_photo=State()
    post_button_choice=State(); post_button=State(); post_url=State()
    button_label=State(); button_url=State(); broadcast=State(); admin_add=State(); admin_remove=State()
    staff_uid=State(); staff_role=State(); staff_reason=State(); report_body=State(); media_views=State(); media_frequency=State(); media_examples=State(); media_contact=State()
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
                m, "welcome", "🔥 FENIX ONLINE\\nТвой личный кабинет.",
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
            "🔥 FENIX ONLINE — регистрация\\n\\nВведи игровой никнейм (3–24 символа, латиница, цифры и _)."
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
    await state.clear(); await state.set_state(S.media_channel)
    await answer_visual(c.message,"media","🤝 ЗАЯВКА В МЕДИАПАРТНЁРЫ\n\nУкажи ссылку на YouTube или TikTok канал.")
    await c.answer()

@dp.message(S.media_channel)
async def media1(m,state:FSMContext):
    link=(m.text or "").strip()
    if not re.match(r"^https?://\S+",link): return await m.answer("Пришли корректную ссылку на канал, начиная с https://")
    await state.update_data(ch=link); await state.set_state(S.media_stats)
    await m.answer("Укажи количество подписчиков и среднее число просмотров на видео.")
@dp.message(S.media_stats)
async def media2(m,state:FSMContext):
    await state.update_data(st=m.text or ""); await state.set_state(S.media_views)
    await m.answer("Сколько просмотров набрали последние 5 видео? Напиши отдельно по каждому, например: 850, 920, 710, 1100, 780.")
@dp.message(S.media_views)
async def media_views(m,state:FSMContext):
    raw=(m.text or "").strip(); nums=[int(x) for x in re.findall(r"\d+",raw)]
    if len(nums)<5: return await m.answer("Нужно указать просмотры минимум для 5 последних видео.")
    await state.update_data(views=nums[:5]); await state.set_state(S.media_frequency)
    await m.answer("Как часто публикуешь видео? Например: 2–3 раза в неделю.")
@dp.message(S.media_frequency)
async def media_frequency(m,state:FSMContext):
    await state.update_data(freq=m.text or ""); await state.set_state(S.media_examples)
    await m.answer("Пришли ссылки на 2–3 примера своих видео.")
@dp.message(S.media_examples)
async def media_examples(m,state:FSMContext):
    links=(m.text or "").strip()
    if "http" not in links: return await m.answer("Добавь ссылки на опубликованные видео.")
    await state.update_data(examples=links); await state.set_state(S.media_contact)
    await m.answer("Оставь контакт для связи с руководством.")
@dp.message(S.media_contact)
async def media3(m,state:FSMContext):
    d=await state.get_data(); views=d.get("views",[]); avg=sum(views)//len(views) if views else 0
    details=f"Подписчики/средние просмотры: {d.get('st')}\nПоследние 5 видео: {views}\nСреднее по 5 видео: {avg}\nЧастота: {d.get('freq')}\nПримеры: {d.get('examples')}\nКонтакт: {m.text}"
    aid=db.media(m.from_user.id,d["ch"],details,m.text or "")
    await state.clear(); await m.answer("✅ Заявка отправлена руководству.\nКритерий проекта: от 700 просмотров стабильно; решение принимается после проверки последних публикаций.")
    for a in db.admin_ids():
        try: await bot.send_message(a,f"🤝 МЕДИА-ЗАЯВКА #{aid}\nID: {m.from_user.id}\nКанал: {d['ch']}\n{details}\nАвтоматический ориентир: {'соответствует' if sum(1 for v in views if v>=700)>=4 else 'не соответствует'} (не менее 4 из 5 видео от 700 просмотров).",reply_markup=markup([[InlineKeyboardButton(text="Одобрить",callback_data=f"mok:{aid}"),InlineKeyboardButton(text="Отклонить",callback_data=f"mno:{aid}")]]))
        except Exception: logging.exception("Не удалось отправить медиа-заявку админу %s",a)
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
        [InlineKeyboardButton(text="👮 Управление администраторами",callback_data="admins_manage")],
        [InlineKeyboardButton(text="🧑‍💼 Персонал и должности",callback_data="staff_panel")],
        [InlineKeyboardButton(text="📋 Отчёты сотрудников",callback_data="reports_panel")],
        [InlineKeyboardButton(text="🎨 Конструктор меню",callback_data="menu_customizer")]
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
    if not is_owner(m.from_user.id):
        await state.clear(); return await m.answer("Только владелец может менять оформление.")
    label=(m.text or "").strip()
    if not label or len(label)>64: return await m.answer("Название кнопки должно содержать 1–64 символа.")
    await state.update_data(label=label); await state.set_state(S.button_url); await m.answer("Теперь пришли URL кнопки.")
@dp.message(S.button_url)
async def buttonurl(m,state:FSMContext):
    if not is_owner(m.from_user.id):
        await state.clear(); return
    u=(m.text or "").strip()
    if not u.startswith(("https://","http://")): return await m.answer("Неверный URL.")
    d=await state.get_data(); db.set_setting("home_label",d["label"]); db.set_setting("home_url",u); await state.clear(); await m.answer("✅ Кнопка меню обновлена.")
@dp.message(Command("setlabel"))
async def setlabel(m):
    if not is_owner(m.from_user.id): return await m.answer("Только владелец может менять названия кнопок.")
    parts=(m.text or "").split(maxsplit=2)
    keys={"cab":"личный кабинет","ref":"рефералы","stats":"статистика","top":"рейтинг","media":"медиапартнёры"}
    if len(parts)<3 or parts[1] not in keys:
        return await m.answer("Формат: /setlabel ключ новое название\nКлючи: cab, ref, stats, top, media\nПример: /setlabel media 🎬 Подать заявку в медиа")
    label=parts[2].strip()
    if not label or len(label)>64: return await m.answer("Название должно быть от 1 до 64 символов.")
    db.set_setting("label_"+parts[1],label)
    await m.answer(f"✅ Название кнопки «{keys[parts[1]]}» изменено. Нажми /start, чтобы увидеть обновлённое меню.")

@dp.message(Command("cancel"))
async def cancel(m,state:FSMContext):
    await state.clear(); await m.answer("Отменено.",reply_markup=menu(m.from_user.id))
@dp.callback_query(F.data=="staff_panel")
async def staff_panel(c):
    if not is_owner(c.from_user.id): return await c.answer("Только владелец.",show_alert=True)
    rows=db.staff_list(); txt="🧑‍💼 СОСТАВ FENIX ONLINE\n\n"+("\n".join(f"• {x['nick'] or x['uid']} — {x['role']} (ID {x['uid']})" for x in rows) if rows else "Состав пока пуст.")
    active=db.shift_active(); txt+="\n\n🟢 АКТИВНЫЕ СМЕНЫ\n"+("\n".join(f"• {x['nick']} — {x['role']} с {x['started']}" for x in active) if active else "Нет активных смен.")
    await c.message.answer(txt,reply_markup=markup([[InlineKeyboardButton(text="➕ Назначить / изменить должность",callback_data="staff_add")],[InlineKeyboardButton(text="➖ Снять с должности",callback_data="staff_remove")]])); await c.answer()

@dp.callback_query(F.data=="staff_add")
async def staff_add(c,state:FSMContext):
    if not is_owner(c.from_user.id): return await c.answer("Только владелец.",show_alert=True)
    await state.set_state(S.staff_uid); await c.message.answer("Отправь Telegram ID сотрудника."); await c.answer()
@dp.message(S.staff_uid)
async def staff_uid(m,state:FSMContext):
    if not is_owner(m.from_user.id): return await state.clear()
    if not (m.text or "").isdigit(): return await m.answer("Нужен числовой Telegram ID.")
    uid=int(m.text); u=db.user(uid)
    if not u: return await m.answer("Пользователь должен сначала запустить бота через /start.")
    await state.update_data(staff_uid=uid,staff_nick=u['nick']); await state.set_state(S.staff_role)
    await m.answer("Введи должность сотрудника (например: Хелпер, Администратор, Куратор, Заместитель).")
@dp.message(S.staff_role)
async def staff_role(m,state:FSMContext):
    if not is_owner(m.from_user.id): return await state.clear()
    role=(m.text or "").strip()
    if not role or len(role)>64: return await m.answer("Название должности: 1–64 символа.")
    d=await state.get_data(); db.staff_set(d['staff_uid'],d['staff_nick'],role,m.from_user.id); await state.clear()
    await m.answer(f"✅ {d['staff_nick']} назначен: {role}.")
    try: await bot.send_message(d['staff_uid'],f"Вам назначена должность в FENIX ONLINE: {role}.")
    except: pass
@dp.callback_query(F.data=="staff_remove")
async def staff_remove_start(c,state:FSMContext):
    if not is_owner(c.from_user.id): return await c.answer("Только владелец.",show_alert=True)
    await state.set_state(S.staff_reason); await c.message.answer("Отправь ID сотрудника и причину снятия через пробел."); await c.answer()
@dp.message(S.staff_reason)
async def staff_remove_finish(m,state:FSMContext):
    if not is_owner(m.from_user.id): return await state.clear()
    parts=(m.text or "").split(maxsplit=1)
    if not parts or not parts[0].isdigit(): return await m.answer("Формат: TelegramID причина")
    uid=int(parts[0]); reason=parts[1] if len(parts)>1 else "Не указана"
    db.staff_remove(uid,m.from_user.id,reason); await state.clear(); await m.answer("✅ Сотрудник снят с должности, действие записано в историю.")
    try: await bot.send_message(uid,"Ваша должность в FENIX ONLINE снята.")
    except: pass

@dp.message(Command("shift"))
async def shift(m):
    if not db.staff_get(m.from_user.id): return await m.answer("Команда доступна только сотрудникам.")
    active=db.shift_open(m.from_user.id)
    if active: await m.answer("🟢 Рабочая смена начата. Для завершения используй /shiftend.")
    else: await m.answer("У тебя уже есть активная смена. Заверши её командой /shiftend.")
@dp.message(Command("shiftend"))
async def shiftend(m):
    if db.shift_close(m.from_user.id): await m.answer("🔴 Смена завершена и записана.")
    else: await m.answer("У тебя нет активной смены.")

@dp.message(Command("reprimand"))
async def reprimand(m):
    if not is_owner(m.from_user.id): return await m.answer("Только владелец может выдавать выговоры.")
    parts=(m.text or "").split(maxsplit=2)
    if len(parts)<3 or not parts[1].isdigit(): return await m.answer("Формат: /reprimand TelegramID причина")
    db.staff_action(int(parts[1]),m.from_user.id,"выговор",parts[2]); await m.answer("✅ Выговор внесён в историю сотрудника.")
@dp.message(Command("staffhistory"))
async def staffhistory(m):
    if not is_owner(m.from_user.id): return await m.answer("Нет доступа.")
    parts=(m.text or "").split(maxsplit=1)
    if len(parts)<2 or not parts[1].isdigit(): return await m.answer("Формат: /staffhistory TelegramID")
    rows=db.staff_history(int(parts[1])); await m.answer("📚 ИСТОРИЯ СОТРУДНИКА\n\n"+("\n".join(f"{x['created']} — {x['action']}: {x['reason'] or '—'}" for x in rows) if rows else "Записей нет."))

@dp.message(Command("report"))
async def report_start(m,state:FSMContext):
    if not db.staff_get(m.from_user.id): return await m.answer("Отчёты доступны только сотрудникам.")
    await state.set_state(S.report_body); await m.answer("Отправь текст отчёта. Можно приложить доказательства отдельным сообщением после отправки текста.")
@dp.message(S.report_body)
async def report_submit(m,state:FSMContext):
    if not db.staff_get(m.from_user.id): await state.clear(); return
    body=(m.text or "").strip()
    if len(body)<10: return await m.answer("Отчёт слишком короткий. Добавь подробности.")
    rid=db.report_add(m.from_user.id,"weekly",body); await state.clear(); await m.answer(f"✅ Отчёт #{rid} отправлен руководству.")
    for a in db.admin_ids():
        try: await bot.send_message(a,f"📋 ОТЧЁТ #{rid}\nСотрудник: {m.from_user.full_name} (ID {m.from_user.id})\n\n{body}",reply_markup=markup([[InlineKeyboardButton(text="✅ Принять",callback_data=f"rptok:{rid}"),InlineKeyboardButton(text="❌ Отклонить",callback_data=f"rptno:{rid}")]]))
        except: pass
@dp.callback_query(F.data.startswith("rptok:") | F.data.startswith("rptno:"))
async def report_decision(c):
    if not is_owner(c.from_user.id): return await c.answer("Только владелец.",show_alert=True)
    action,rid=c.data.split(":"); row=db.report_get(int(rid))
    if not row or row['status']!="pending": return await c.answer("Отчёт уже обработан.",show_alert=True)
    status="accepted" if action=="rptok" else "rejected"; db.report_review(int(rid),c.from_user.id,status)
    try: await bot.send_message(row['uid'],"✅ Отчёт принят." if status=="accepted" else "❌ Отчёт отклонён. Свяжись с руководством для уточнения.")
    except: pass
    await c.message.edit_reply_markup(reply_markup=None); await c.answer("Решение сохранено.")
@dp.callback_query(F.data=="reports_panel")
async def reports_panel(c):
    if not is_owner(c.from_user.id): return await c.answer("Только владелец.",show_alert=True)
    rows=db.reports_pending(); txt="📋 ОЖИДАЮТ ПРОВЕРКИ\n\n"+("\n".join(f"#{x['id']} — ID {x['uid']} — {x['created']}" for x in rows) if rows else "Нет ожидающих отчётов.")
    await c.message.answer(txt); await c.answer()

@dp.callback_query(F.data=="menu_customizer")
async def menu_customizer(c,state:FSMContext):
    if not is_owner(c.from_user.id): return await c.answer("Только владелец.",show_alert=True)
    await state.set_state(S.button_label); await c.message.answer("Отправь новую подпись кнопки новостей. Можно добавить обычный Unicode-эмодзи, например 📰 FENIX NEWS. Максимум 64 символа."); await c.answer()

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
    db.ensure_management()
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
