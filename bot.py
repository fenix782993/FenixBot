import asyncio, logging, os, re, secrets, hashlib
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from db import DB

load_dotenv()
TOKEN=os.getenv("BOT_TOKEN","")
CHANNEL=os.getenv("CHANNEL_ID","")
CHANNEL_URL=os.getenv("CHANNEL_URL","")
ADMINS={int(x) for x in os.getenv("ADMIN_IDS","").replace(" ","").split(",") if x}
if not TOKEN: raise RuntimeError("BOT_TOKEN не задан")
logging.basicConfig(level=logging.INFO)
bot=Bot(TOKEN); dp=Dispatcher(storage=MemoryStorage()); db=DB(os.getenv("DATABASE_PATH","data.sqlite3"))
OWNER_IDS=ADMINS.copy()
def is_admin(uid): return db.is_admin(uid)
def is_owner(uid): return uid in OWNER_IDS
def markup(rows): return InlineKeyboardMarkup(inline_keyboard=rows)
def menu(uid):
    label=db.setting("home_label","📢 Новости FENIX ONLINE")
    url=db.setting("home_url",CHANNEL_URL)
    rows=[[InlineKeyboardButton(text="👤 Личный кабинет",callback_data="cab"),
           InlineKeyboardButton(text="🔗 Моя реферальная ссылка",callback_data="ref")],
          [InlineKeyboardButton(text="📊 Статистика",callback_data="stats"),
           InlineKeyboardButton(text="🏆 Рейтинг",callback_data="top")],
          [InlineKeyboardButton(text="🤝 Стать медиапартнёром",callback_data="media")]]
    if url: rows.append([InlineKeyboardButton(text=label,url=url)])
    if is_admin(uid): rows.append([InlineKeyboardButton(text="⚙️ Панель владельца",callback_data="owner")])
    return markup(rows)
class S(StatesGroup):
    nick=State(); password=State(); media_channel=State(); media_stats=State(); media_contact=State()
    post_text=State(); post_photo=State(); post_button=State(); post_url=State()
    button_label=State(); button_url=State(); broadcast=State(); admin_add=State(); admin_remove=State()
def hashpw(p):
    salt=secrets.token_hex(16)
    return salt+"$"+hashlib.pbkdf2_hmac("sha256",p.encode(),salt.encode(),200000).hex()
@dp.message(Command("id"))
async def cmd_id(m): await m.answer(f"Твой Telegram ID: {m.from_user.id}")
@dp.message(CommandStart())
async def start(m:Message,state:FSMContext):
    u=db.user(m.from_user.id)
    if u: return await m.answer("🔥 <b>FENIX ONLINE</b>\nТвой личный кабинет.",parse_mode="HTML",reply_markup=menu(m.from_user.id))
    p=(m.text or "").split(maxsplit=1); ref=None
    if len(p)>1 and p[1].startswith("r"):
        try: ref=int(p[1][1:])
        except: pass
    if ref==m.from_user.id: ref=None
    await state.update_data(ref=ref); await state.set_state(S.nick)
    await m.answer("🔥 <b>FENIX ONLINE — регистрация</b>\n\nВведи игровой никнейм (3–24 символа, латиница, цифры и _).",parse_mode="HTML")
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
    await m.answer("✅ <b>Регистрация завершена!</b>",parse_mode="HTML",reply_markup=menu(m.from_user.id))
    if d.get("ref"):
        try: await bot.send_message(d["ref"],f"🎉 По твоей ссылке зарегистрировался игрок <b>{d['nick']}</b>.",parse_mode="HTML")
        except: pass
@dp.callback_query(F.data=="cab")
async def cab(c):
    u=db.user(c.from_user.id)
    if not u: return await c.answer("Сначала /start",show_alert=True)
    await c.message.answer(f"👤 <b>ЛИЧНЫЙ КАБИНЕТ</b>\nНик: <b>{u['nick']}</b>\nПриглашено: <b>{db.ref_count(c.from_user.id)}</b>",parse_mode="HTML"); await c.answer()
@dp.callback_query(F.data=="ref")
async def ref(c):
    if not db.user(c.from_user.id): return await c.answer("Сначала /start",show_alert=True)
    me=await bot.get_me(); link=f"https://t.me/{me.username}?start=r{c.from_user.id}"
    await c.message.answer(f"🔗 <b>ТВОЯ РЕФЕРАЛЬНАЯ ССЫЛКА</b>\n<code>{link}</code>\nЗарегистрировано по ссылке: <b>{db.ref_count(c.from_user.id)}</b>\n\nДля приглашений именно в канал используй /invite.",parse_mode="HTML"); await c.answer()
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
    await c.message.answer(f"📊 Твои регистрации по реферальной ссылке: <b>{db.ref_count(c.from_user.id)}</b>\nВступления в канал по персональной ссылке: <b>{db.channel_count(c.from_user.id)}</b>",parse_mode="HTML"); await c.answer()
@dp.callback_query(F.data=="top")
async def top(c):
    rows=db.top(); txt="🏆 <b>ТОП РЕФЕРАЛОВ</b>\n\n"+("\n".join(f"{i}. {x['nick']} — {x['n']}" for i,x in enumerate(rows,1)) if rows else "Пока пусто.")
    await c.message.answer(txt,parse_mode="HTML"); await c.answer()
@dp.callback_query(F.data=="media")
async def media(c,state:FSMContext):
    await state.set_state(S.media_channel); await c.message.answer("🤝 <b>Заявка в медиапартнёры</b>\nПришли ссылку на свой канал/площадку.",parse_mode="HTML"); await c.answer()
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
        try: await bot.send_message(a,f"🤝 <b>Заявка медиапартнёра #{aid}</b>\nID: <code>{m.from_user.id}</code>\nКанал: {d['ch']}\nАудитория: {d['st']}\nКонтакт: {m.text}",parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text="Одобрить",callback_data=f"mok:{aid}"),InlineKeyboardButton(text="Отклонить",callback_data=f"mno:{aid}")]]))
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
    await c.message.answer("⚙️ <b>ПАНЕЛЬ ВЛАДЕЛЬЦА</b>",parse_mode="HTML",reply_markup=markup([
    [InlineKeyboardButton(text="📣 Опубликовать пост",callback_data="post")],
    [InlineKeyboardButton(text="📨 Рассылка",callback_data="broadcast")],
    [InlineKeyboardButton(text="🎨 Настроить кнопку меню",callback_data="editbutton")],
    [InlineKeyboardButton(text="📈 Общая статистика",callback_data="ostats")],
    [InlineKeyboardButton(text="👮 Управление администраторами",callback_data="admins_manage")]])); await c.answer()
@dp.callback_query(F.data=="admins_manage")
async def admins_manage(c):
    if not is_owner(c.from_user.id):
        return await c.answer("Управлять администраторами может только владелец.",show_alert=True)
    ids=db.admin_ids()
    text="👮 <b>УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ</b>\\n\\n"
    text += "\\n".join(f"• <code>{uid}</code>" for uid in ids) if ids else "Администраторов пока нет."
    await c.message.answer(text,parse_mode="HTML",reply_markup=markup([
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
    await state.set_state(S.post_text); await c.message.answer("Пришли текст поста (HTML-разметка: <b>, <i>, <u>)."); await c.answer()
@dp.message(S.post_text)
async def posttext(m,state:FSMContext):
    if not is_admin(m.from_user.id): return
    await state.update_data(text=m.text or ""); await state.set_state(S.post_photo); await m.answer("Пришли фото или отправь - без фото.")
@dp.message(S.post_photo)
async def postphoto(m,state:FSMContext):
    if not is_admin(m.from_user.id): return
    ph=m.photo[-1].file_id if m.photo else None
    if not ph and (m.text or "").strip()!="-": return await m.answer("Нужна фотография или символ -.")
    await state.update_data(photo=ph); await state.set_state(S.post_button); await m.answer("Текст кнопки или - без кнопки.")
@dp.message(S.post_button)
async def postbutton(m,state:FSMContext):
    if not is_admin(m.from_user.id): return
    t=(m.text or "").strip(); await state.update_data(bt=None if t=="-" else t)
    if t=="-": return await publish(m,state)
    await state.set_state(S.post_url); await m.answer("Пришли URL кнопки, начиная с https://")
@dp.message(S.post_url)
async def posturl(m,state:FSMContext):
    if not is_admin(m.from_user.id): return
    u=(m.text or "").strip()
    if not u.startswith(("https://","http://")): return await m.answer("Неверная ссылка.")
    await state.update_data(bu=u); await publish(m,state)
async def publish(m,state):
    d=await state.get_data(); rows=[[InlineKeyboardButton(text=d["bt"],url=d["bu"])]] if d.get("bt") else None
    try:
        if d.get("photo"): await bot.send_photo(CHANNEL,d["photo"],caption=d["text"],parse_mode="HTML",reply_markup=markup(rows) if rows else None)
        else: await bot.send_message(CHANNEL,d["text"],parse_mode="HTML",reply_markup=markup(rows) if rows else None)
        await m.answer("✅ Пост опубликован в канале.")
    except Exception as e: await m.answer("Ошибка публикации: "+str(e))
    await state.clear()
@dp.callback_query(F.data=="broadcast")
async def broadcast(c,state:FSMContext):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    await state.set_state(S.broadcast); await c.message.answer("Пришли текст рассылки пользователям бота."); await c.answer()
@dp.message(S.broadcast)
async def broadcast_send(m,state:FSMContext):
    if not is_admin(m.from_user.id): return
    sent=0
    for uid in db.user_ids():
        try: await bot.send_message(uid,m.text or "",parse_mode="HTML"); sent+=1
        except: pass
    await state.clear(); await m.answer(f"Рассылка завершена. Доставлено: {sent}")
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
async def main():
    db.init(); await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
if __name__=="__main__": asyncio.run(main())
