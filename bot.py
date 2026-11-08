import asyncio, logging, os, re, secrets, hashlib, html
from datetime import datetime, timezone, timedelta
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
REQUIRED_CHANNEL_URL = CHANNEL_URL or "https://t.me/+1usTps-EXmxjNWRl"
def is_admin(uid): return db.is_admin(uid)
def is_owner(uid): return uid in OWNER_IDS
def markup(rows): return InlineKeyboardMarkup(inline_keyboard=rows)

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
    if is_owner(message.from_user.id): return True
    if kind == "admin": return is_admin(message.from_user.id)
    return bool(db.staff_role(message.from_user.id, "leader"))

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

def menu(uid):
    media_status=(db.media_current(uid) or {}).get("status")
    label=db.setting("home_label","📢 Новости FENIX ONLINE")
    url=db.setting("home_url",CHANNEL_URL)
    rows=[[InlineKeyboardButton(text=db.setting("cab_label","👤 Личный кабинет"),callback_data="cab"),
           InlineKeyboardButton(text=db.setting("ref_label","🔗 Моя реферальная ссылка"),callback_data="ref")],
          [InlineKeyboardButton(text=db.setting("stats_label","📊 Статистика"),callback_data="stats"),
           InlineKeyboardButton(text=db.setting("top_label","🏆 Рейтинг"),callback_data="top")],
          [InlineKeyboardButton(text=("🎬 Кабинет медиапартнёра" if (media_status=="approved") else db.setting("media_label","🤝 Стать медиапартнёром")),callback_data=("media_cabinet" if (media_status=="approved") else "media"))]]
    if url: rows.append([InlineKeyboardButton(text=label,url=url)])
    if is_admin(uid): rows.append([InlineKeyboardButton(text=db.setting("owner_label","⚙️ Панель владельца"),callback_data="owner")])
    return markup(rows)
class S(StatesGroup):
    nick=State(); password=State(); media_channel=State(); media_stats=State(); media_contact=State()
    payout_channel=State(); payout_video=State(); media_payout_requisites=State(); payout_views=State(); payout_amount=State(); payout_note=State(); customize_label=State()
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
        if not await subscribed(m.from_user.id):
            await m.answer(
                "🔒 Для использования FENIX ONLINE необходимо подписаться на канал проекта.",
                reply_markup=markup([[InlineKeyboardButton(text="📢 Подписаться", url=REQUIRED_CHANNEL_URL)],
                                     [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]])
            )
            return
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
    current=db.media_current(c.from_user.id)
    if current and current.get("status")=="pending":
        return await c.answer("Твоя заявка уже находится на рассмотрении.",show_alert=True)
    if current and current.get("status")=="approved":
        return await c.message.answer("🎉 Ты уже медиапартнёр. Открой свой кабинет.",reply_markup=markup([[InlineKeyboardButton(text="🎬 Кабинет медиапартнёра",callback_data="media_cabinet")]]))
    await state.set_state(S.media_channel)
    await answer_visual(c.message, "media", "🤝 ЗАЯВКА В МЕДИАПАРТНЁРЫ\nПришли ссылку на свой канал или площадку.")
    await c.answer()

@dp.callback_query(F.data=="media_cabinet")
async def media_cabinet(c):
    current=db.media_current(c.from_user.id)
    if not current or current.get("status")!="approved":
        return await c.answer("Кабинет доступен только одобренным медиапартнёрам.",show_alert=True)
    payouts=db.media_payouts_for_user(c.from_user.id,5)
    history="\n".join(f"#{x['id']} — {x['amount']} — {x['status']}" for x in payouts) or "Пока запросов выплат нет."
    await c.message.answer("🎬 КАБИНЕТ МЕДИАПАРТНЁРА\n\n🎥 Видеоотчёт: /media_video\n📅 Выплаты после 7 активных дней, раз в 14 дней\n💰 1000 просмотров = 50 ₽\n\nСтатус: ✅ Одобрен\nКанал: "+str(current.get('ch') or '—')+"\nАудитория: "+str(current.get('stats') or '—')+"\n\n💳 ИСТОРИЯ ЗАПРОСОВ ВЫПЛАТ\n"+history,reply_markup=markup([[InlineKeyboardButton(text="💸 Запросить выплату",callback_data="media_payout")]]))
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
    if not is_admin(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    rows=db.media_pending_payouts()
    if not rows: await c.message.answer('📋 Заявок на выплату пока нет.')
    else:
        kb=[[InlineKeyboardButton(text=f'#{r["id"]} · ID {r["uid"]}',callback_data=f'payout_view:{r["id"]}')] for r in rows[:30]]
        await c.message.answer(f'💸 <b>ЗАЯВКИ НА ВЫПЛАТУ</b>\nВ очереди: {len(rows)}\nВыбирай заявку для проверки по одной.',reply_markup=markup(kb),parse_mode='HTML')
    await c.answer()

@dp.callback_query(F.data.startswith('payout_view:'))
async def payout_view(c):
    if not is_admin(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
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
    await c.message.answer(txt,parse_mode='HTML',reply_markup=markup(kb))
    await c.answer()

@dp.callback_query(F.data.startswith('payout_approve:'))
async def payout_approve(c,state:FSMContext):
    if not is_admin(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    pid=int(c.data.split(':')[1]); r=db.media_payout_get(pid)
    if not r or r['status']!='pending': return await c.answer('Заявка уже обработана',show_alert=True)
    await state.update_data(review_pid=pid)
    await state.set_state(S.payout_views)
    await c.message.answer('👁 Введи подтверждённое число просмотров (целое число). Расчёт: 1 000 просмотров = 50 ₽.')
    await c.answer()

@dp.message(S.payout_views)
async def payout_views(m,state:FSMContext):
    if not is_admin(m.from_user.id): return
    raw=(m.text or '').strip().replace(' ','')
    if not raw.isdigit(): return await m.answer('Введи число просмотров.')
    views=int(raw)
    if views>1000000000: return await m.answer('Слишком большое число.')
    amount=views*0.05
    await state.update_data(views=views)
    await state.set_state(S.payout_amount)
    await m.answer(f'📊 Расчёт по тарифу: {amount:.2f} ₽.\nНапиши итоговую сумму выплаты в рублях (администратор может скорректировать её).')

@dp.message(S.payout_amount)
async def payout_amount(m,state:FSMContext):
    if not is_admin(m.from_user.id): return
    try: amount=float((m.text or '').strip().replace(',','.'))
    except ValueError: return await m.answer('Введи сумму числом.')
    if amount<0 or amount>10000000: return await m.answer('Некорректная сумма.')
    await state.update_data(approved_amount=f'{amount:.2f} RUB')
    await state.set_state(S.payout_note)
    await m.answer('✍️ Напиши текст решения для медиапартнёра. После этого заявка будет одобрена. Деньги переводи вручную по реквизитам.')

@dp.message(S.payout_note)
async def payout_note(m,state:FSMContext):
    if not is_admin(m.from_user.id): return
    note=(m.text or '').strip()
    if not note: return await m.answer('Напиши текст решения.')
    data=await state.get_data(); pid=data['review_pid']; r=db.media_payout_get(pid)
    if not r or r['status']!='pending': await state.clear(); return await m.answer('Заявка уже обработана.')
    if data.get('reject'):
        db.media_payout_review(pid,'rejected',m.from_user.id,note[:1500])
        await state.clear()
        await m.answer(f'❌ Заявка #{pid} отклонена.')
        try: await bot.send_message(r['uid'],f'❌ <b>ВЫПЛАТА ОТКЛОНЕНА</b>\n\n📝 {html.escape(note)}',parse_mode='HTML')
        except Exception: logging.exception('Не удалось отправить отказ')
        return
    db.media_payout_set_amount(pid,data['approved_amount'])
    db.media_payout_review(pid,'approved',m.from_user.id,note[:1500])
    await state.clear()
    await m.answer(f'✅ Заявка #{pid} одобрена. Сумма: {data["approved_amount"]}. После фактического перевода отметь выплату.',reply_markup=markup([[InlineKeyboardButton(text='💸 Отметить отправку денег',callback_data=f'mpaid:{pid}')]]))
    try: await bot.send_message(r['uid'],f'🎉 <b>ВЫПЛАТА ОДОБРЕНА!</b>\n\n💰 Сумма: <b>{data["approved_amount"]}</b>\n📝 {html.escape(note)}\n\n⏳ Ожидай фактического перевода.',parse_mode='HTML')
    except Exception: logging.exception('Не удалось уведомить медиапартнёра')

@dp.callback_query(F.data.startswith('payout_reject:'))
async def payout_reject(c,state:FSMContext):
    if not is_admin(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    pid=int(c.data.split(':')[1]); r=db.media_payout_get(pid)
    if not r or r['status']!='pending': return await c.answer('Заявка уже обработана',show_alert=True)
    await state.update_data(review_pid=pid)
    await state.set_state(S.payout_note)
    await state.update_data(reject=True)
    await c.message.answer('❌ Напиши причину отказа для медиапартнёра.')
    await c.answer()

@dp.callback_query(F.data.startswith('mpaid:'))
async def media_payout_paid(c):
    if not is_admin(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    pid=int(c.data.split(':')[1]); r=db.media_payout_get(pid)
    if not r or r['status']!='approved': return await c.answer('Сначала одобри заявку.',show_alert=True)
    db.media_payout_review(pid,'paid',c.from_user.id,r.get('review_note') or '')
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
        try: await bot.send_message(a["uid"],"Заявка в медиапартнёры отклонена.")
        except: pass
    await c.message.edit_reply_markup(reply_markup=None); await c.answer("Отклонено")
@dp.callback_query(F.data=="owner")
async def owner(c):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    await answer_visual(c.message, "news", "⚙️ ПАНЕЛЬ ВЛАДЕЛЬЦА", reply_markup=markup([
        [InlineKeyboardButton(text="📣 Опубликовать пост",callback_data="post")],
        [InlineKeyboardButton(text="📨 Рассылка",callback_data="broadcast")],
        [InlineKeyboardButton(text="💸 Заявки на выплаты",callback_data="payout_queue")],
        [InlineKeyboardButton(text="🎨 Кастомизация бота",callback_data="customize")],
        [InlineKeyboardButton(text="👥 Составы и чаты",callback_data="staff_setup")],
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
    text += "\n".join(
        f"• {db.staff_display(uid)}\n  Должность: {db.staff_role(uid, 'admin') or 'Администратор'}"
        for uid in ids
    ) if ids else "Администраторов пока нет."
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

@dp.message(Command("bind_admin_chat"))
async def bind_admin_chat(m):
    if not is_owner(m.from_user.id) or m.chat.type == "private":
        return await m.answer("Команду может выполнить владелец непосредственно в административном чате.")
    db.set_setting("admin_chat_id", str(m.chat.id))
    await m.answer("✅ Этот чат назначен административным. Здесь доступны команды управления администрацией.")

@dp.message(Command("bind_leader_chat"))
async def bind_leader_chat(m):
    if not is_owner(m.from_user.id) or m.chat.type == "private":
        return await m.answer("Команду может выполнить владелец непосредственно в лидерском чате.")
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
    await m.answer(f"✅ Должность назначена\nИгрок: {db.staff_display(user['uid'])}\nДолжность: {title}")
    try: await bot.send_message(user["uid"], f"🎖 Вам назначена должность: {title}")
    except Exception: pass

@dp.message(Command("stafflist"))
async def staff_list(m):
    kind = staff_chat_kind(m.chat.id)
    if kind is None: return await m.answer("Команда доступна только в привязанных чатах персонала.")
    if not can_manage_chat(m, kind): return await m.answer("⛔ Нет доступа.")
    rows = db.staff_list(kind)
    heading = "👮 СОСТАВ АДМИНИСТРАЦИИ" if kind == "admin" else "👑 СОСТАВ ЛИДЕРОВ"
    body = "\n\n".join(f"{i}. {db.staff_display(x['uid'])}\nДолжность: {x['title']}\nTelegram ID: {x['uid']}" for i,x in enumerate(rows,1))
    await m.answer(heading + "\n\n" + (body or "Состав пока пуст."))

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
    await m.answer(f"✅ Должность снята: {db.staff_display(user['uid'])}")

@dp.callback_query(F.data == "staff_setup")
async def staff_setup(c):
    if not is_owner(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    await c.message.answer("👥 ПРИВЯЗКА ЧАТОВ\nДобавь бота в нужные группы и выполни в них соответствующие команды:\n/bind_admin_chat — административный чат\n/bind_leader_chat — лидерский чат\n\nВ каждом чате: /nnick ник должность, /stafflist — состав, /staffremove ник — снять должность.")
    await c.answer()

CUSTOM_LABELS={"cab":("cab_label","👤 Личный кабинет"),"ref":("ref_label","🔗 Реферальная ссылка"),"stats":("stats_label","📊 Статистика"),"top":("top_label","🏆 Рейтинг"),"media":("media_label","🤝 Стать медиапартнёром"),"owner":("owner_label","⚙️ Панель владельца"),"home":("home_label","📢 Новости FENIX ONLINE")}
@dp.callback_query(F.data == "customize")
async def customize(c):
    if not is_owner(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    rows=[[InlineKeyboardButton(text=label,callback_data=f'custom_pick:{key}')] for key,(_,label) in CUSTOM_LABELS.items()]
    await c.message.answer('🎨 <b>КАСТОМИЗАЦИЯ КНОПОК</b>\n\nВыбери кнопку, название которой хочешь изменить:',parse_mode='HTML',reply_markup=markup(rows))
    await c.answer()

@dp.callback_query(F.data.startswith('custom_pick:'))
async def custom_pick(c,state:FSMContext):
    if not is_owner(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    key=c.data.split(':')[1]
    if key not in CUSTOM_LABELS: return await c.answer('Неизвестная кнопка',show_alert=True)
    setting,default=CUSTOM_LABELS[key]
    await state.update_data(custom_key=key)
    await state.set_state(S.customize_label)
    await c.message.answer(f'✏️ Текущее название: {db.setting(setting,default)}\n\nОтправь новое название (до 64 символов, можно с эмодзи).')
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
    footer=("\n\n━━━━━━━━━━━━━━\n<b>🔥 FENIX ONLINE</b>\n"
            "🛡 <b>VPN:</b> @fenixVPNrobot\n"
            "⭐ <b>Stars:</b> @Fenix_stars_bot\n"
            "💬 <b>Форум:</b> <a href=\"http://forum.wh35740.web1.maze-tech.ru/index.php\">Перейти на форум</a>")
    text=html.escape(data.get("text") or " ")+footer
    photo=data.get("photo")
    if photo and len(text)<=1024:
        await bot.send_photo(chat_id,photo,caption=text,reply_markup=keyboard,parse_mode="HTML")
        return
    if photo:
        await bot.send_photo(chat_id,photo)
    chunks=[html.escape(chunk) for chunk in split_message(data.get("text") or " ")]
    if len(chunks[-1])+len(footer)>4000: chunks.append(footer)
    else: chunks[-1]+=footer
    for i,chunk in enumerate(chunks):
        await bot.send_message(chat_id,chunk,parse_mode="HTML",
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
