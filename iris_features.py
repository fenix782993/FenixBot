"""Additional Iris-inspired social modules for FENIX Chat Manager."""
import asyncio
import logging
import random
import re
import secrets
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

log=logging.getLogger("fenix.iris_features")

def ph(db): return "%s" if db.use_postgres else "?"
def run(db,sql,args=()):
    with db.con() as c: return c.execute(sql,args)
def one(db,sql,args=()):
    with db.con() as c:
        x=c.execute(sql,args).fetchone()
        return dict(x) if x else None
def rows(db,sql,args=()):
    with db.con() as c: return [dict(x) for x in c.execute(sql,args).fetchall()]

def init(db):
    with db.con() as c:
        if db.use_postgres:
            c.execute("CREATE TABLE IF NOT EXISTS iris_rep(chat_id BIGINT,uid BIGINT,score INTEGER DEFAULT 0,PRIMARY KEY(chat_id,uid))")
            c.execute("CREATE TABLE IF NOT EXISTS iris_notes(id BIGSERIAL PRIMARY KEY,chat_id BIGINT,uid BIGINT,note TEXT,created TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS iris_bookmarks(id BIGSERIAL PRIMARY KEY,chat_id BIGINT,uid BIGINT,message_id BIGINT,text TEXT,created TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS iris_clans(id BIGSERIAL PRIMARY KEY,chat_id BIGINT,name TEXT,owner BIGINT,created TEXT,UNIQUE(chat_id,name))")
            c.execute("CREATE TABLE IF NOT EXISTS iris_clan_members(chat_id BIGINT,clan_id BIGINT,uid BIGINT,joined TEXT,PRIMARY KEY(chat_id,uid))")
            c.execute("CREATE TABLE IF NOT EXISTS iris_pairs(chat_id BIGINT,a BIGINT,b BIGINT,status TEXT,created TEXT,PRIMARY KEY(chat_id,a,b))")
            c.execute("CREATE TABLE IF NOT EXISTS iris_giveaways(id TEXT PRIMARY KEY,chat_id BIGINT,owner BIGINT,prize TEXT,ends TEXT,status TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS iris_giveaway_users(gid TEXT,uid BIGINT,PRIMARY KEY(gid,uid))")
        else:
            c.executescript("""CREATE TABLE IF NOT EXISTS iris_rep(chat_id INTEGER,uid INTEGER,score INTEGER DEFAULT 0,PRIMARY KEY(chat_id,uid));
            CREATE TABLE IF NOT EXISTS iris_notes(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,uid INTEGER,note TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS iris_bookmarks(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,uid INTEGER,message_id INTEGER,text TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS iris_clans(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,name TEXT,owner INTEGER,created TEXT,UNIQUE(chat_id,name));
            CREATE TABLE IF NOT EXISTS iris_clan_members(chat_id INTEGER,clan_id INTEGER,uid INTEGER,joined TEXT,PRIMARY KEY(chat_id,uid));
            CREATE TABLE IF NOT EXISTS iris_pairs(chat_id INTEGER,a INTEGER,b INTEGER,status TEXT,created TEXT,PRIMARY KEY(chat_id,a,b));
            CREATE TABLE IF NOT EXISTS iris_giveaways(id TEXT PRIMARY KEY,chat_id INTEGER,owner INTEGER,prize TEXT,ends TEXT,status TEXT);
            CREATE TABLE IF NOT EXISTS iris_giveaway_users(gid TEXT,uid INTEGER,PRIMARY KEY(gid,uid));""")

def register(dp,bot,db):
    init(db); router=Router(name="fenix_iris_social_modules")
    def stamp(): return datetime.now(timezone.utc).isoformat()
    async def target(m,args):
        if m.reply_to_message and m.reply_to_message.from_user: return m.reply_to_message.from_user.id
        if args and args[0].isdigit(): return int(args[0])
        return None
    @router.message(Command("iris"))
    async def iris_menu(m):
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛡 Модерация",callback_data="iris:moderation"),InlineKeyboardButton(text="⚙️ Настройки",callback_data="iris:settings")],
            [InlineKeyboardButton(text="👤 Профиль и репутация",callback_data="iris:profile"),InlineKeyboardButton(text="🎲 Развлечения",callback_data="iris:games")],
            [InlineKeyboardButton(text="📝 Заметки и закладки",callback_data="iris:notes"),InlineKeyboardButton(text="🏆 Кланы и розыгрыши",callback_data="iris:community")],
            [InlineKeyboardButton(text="📚 Все команды",callback_data="iris:help")]])
        await m.answer("<b>FENIX · CHAT MANAGER</b>\nВыбери раздел управления беседой:",parse_mode="HTML",reply_markup=kb)
    @router.callback_query(F.data.startswith("iris:"))
    async def iris_menu_cb(c):
        section=c.data.split(":",1)[1]
        if section=="back":
            kb=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛡 Модерация",callback_data="iris:moderation"),InlineKeyboardButton(text="⚙️ Настройки",callback_data="iris:settings")],
                [InlineKeyboardButton(text="👤 Профиль и репутация",callback_data="iris:profile"),InlineKeyboardButton(text="🎲 Развлечения",callback_data="iris:games")],
                [InlineKeyboardButton(text="📝 Заметки и закладки",callback_data="iris:notes"),InlineKeyboardButton(text="🏆 Кланы и розыгрыши",callback_data="iris:community")],
                [InlineKeyboardButton(text="📚 Все команды",callback_data="iris:help")]])
            await c.message.edit_text("<b>FENIX · CHAT MANAGER</b>\nВыбери раздел управления беседой:",parse_mode="HTML",reply_markup=kb)
            await c.answer()
            return
        texts={
        "moderation":"МОДЕРАЦИЯ\n!mute 15m причина — ограничить участника на срок; цель укажи ответом или ID.\n!unmute — снять ограничение.\n!warn причина — выдать предупреждение.\n!unwarn — снять последнее активное предупреждение.\n!warnhistory / !getwarn — история предупреждений.\n!warnlist — сводка активных предупреждений.\n!kick — исключить без постоянного бана.\n!ban 7 причина — заблокировать на 7 дней; без срока — бессрочно.\n!unban ID — снять бан.\n!report текст — создать обращение руководству.\n!filteradd / !filterdel — добавить или удалить фразу фильтра.",
        "settings":"НАСТРОЙКИ БЕСЕДЫ\n!settings — показать текущие параметры.\n!welcome текст — задать приветствие новых участников.\n!setrules текст — установить текст правил; !rules — показать их.\n!setsettings mute on|off — режим ограничений.\n!setsettings invite on|off — режим приглашений.\n!silence — переключить флаг тишины.\n!pin — закрепить сообщение, на которое ответил.\n!unpin — снять закрепление.",
        "profile":"ПРОФИЛЬ И РЕПУТАЦИЯ\n!profile [ID] — ник, репутация и активные предупреждения.\n!stats [ID] — статистика FENIX Manager и должность.\n!rep — повысить репутацию другого участника на 1 (ответом или ID; раз в сутки).\n!топреп — топ-10 по репутации.\n!getnick — посмотреть игровой ник; !setnick ID ник — сохранить; !removenick — удалить.",
        "games":"РАЗВЛЕЧЕНИЯ\n!dice — бросить кубик Telegram.\n!coin — орёл или решка.\n!try — RP-попытка.\n!kiss — поцеловать участника (ответом или ID).\n!obnyat — обнять участника (ответом или ID).\n!duel — вызвать участника на дуэль в кости (ответом или ID).",
        "notes":"ЗАМЕТКИ, ЗАКЛАДКИ И ТАЙМЕРЫ\n!note add текст — сохранить заметку; ответ на участника прикрепляет её к нему.\n!note list — показать заметки; !note del ID — удалить заметку.\n!notes — показать твои заметки.\n!bookmark — сохранить сообщение (ответом); !bookmarks — список; !unbookmark ID — удалить.\n!timer 10m текст — создать напоминание (10 секунд–30 дней); !timers — список; !timerdel ID — отменить.",
        "community":"СООБЩЕСТВО\n!clan create название — создать клан; !clan join название — вступить; !clan leave — выйти; !clan info — сводка крупнейшего клана.\n!circle create/join/leave/info/list — управление кругами беседы.\n!giveaway 1h приз — создать розыгрыш; участники нажимают кнопку.\n!gstop ID — отменить розыгрыш.",
        "help":"СПРАВОЧНИК\n!help — полный список команд и объяснения.\n/iris — открыть это меню.\nМодерация: !mute, !warn, !ban, !kick, !report.\nПрофиль: !profile, !stats, !rep, !топреп.\nРазвлечения: !dice, !coin, !try, !kiss, !obnyat, !duel.\nЗаметки: !note, !notes, !bookmark, !bookmarks.\nСообщество: !clan, !circle, !giveaway."}
        await c.message.edit_text("<b>"+texts.get(section,texts["help"])+"</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="← В меню",callback_data="iris:back")]]))
        await c.answer()
    @router.callback_query(F.data=="iris:back")
    async def iris_back(c):
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📚 Все команды",callback_data="iris:help")],[InlineKeyboardButton(text="🎲 Развлечения",callback_data="iris:games"),InlineKeyboardButton(text="👤 Профиль",callback_data="iris:profile")]])
        await c.message.edit_text("<b>FENIX · CHAT MANAGER</b>\nВыбери раздел:",parse_mode="HTML",reply_markup=kb); await c.answer()
    @router.callback_query(F.data.startswith("irg:join:"))
    async def giveaway_join(c):
        gid=c.data.split(":")[-1]; g=one(db,f"SELECT * FROM iris_giveaways WHERE id={ph(db)}",(gid,))
        if not g or g["status"]!="active": return await c.answer("Розыгрыш завершён.",show_alert=True)
        p=ph(db)
        if db.use_postgres: run(db,f"INSERT INTO iris_giveaway_users(gid,uid) VALUES({p},{p}) ON CONFLICT DO NOTHING",(gid,c.from_user.id))
        else: run(db,f"INSERT OR IGNORE INTO iris_giveaway_users(gid,uid) VALUES({p},{p})",(gid,c.from_user.id))
        await c.answer("Ты участвуешь!")
    feature_commands="dice|кубик|coin|монетка|profile|профиль|rep|реп|note|заметка|notes|заметки|bookmark|закладка|bookmarks|закладки|clan|клан|circle|круг|marry|брак|divorce|развод|timer|таймер|giveaway|розыгрыш|gstop|access|доступ|triggeradd|triggerdel|triggers|триггеры|antispam|антиспам"
    feature_pattern=re.compile(r"(?i)^(?:[!./](?:"+feature_commands+r")(?=$|[^a-zA-Z0-9_])|ирис(?:ка)?[ ]+(?:"+feature_commands+r")(?=$|[^a-zA-Z0-9_]))")
    @router.message(F.text.regexp(feature_pattern))
    async def features(m):
        if m.chat.type=="private": return
        raw=(m.text or "").strip()
        command_text=raw.split(maxsplit=1)[1] if raw.lower().startswith(("ирис ","ириска ")) else raw[1:]
        parts=command_text.split(maxsplit=1); cmd=parts[0].lower(); arg=parts[1] if len(parts)>1 else ""; args=arg.split(); uid=m.from_user.id; chat=m.chat.id; p=ph(db)
        if cmd in ("access","доступ"):
            if not db.is_admin(uid): return await m.answer("⛔ Только администратор FENIX.")
            if len(args)<2: return await m.answer("Формат: !access команда 0|20|40|60|80|off")
            name,value=args[0].lower().lstrip("!./"),args[1].lower()
            try: level=0 if value=="off" else int(value)
            except ValueError: return await m.answer("Уровень: 0, 20, 40, 60, 80 или off.")
            if level not in (0,20,40,60,80): return await m.answer("Недопустимый уровень.")
            enabled=0 if value=="off" else 1
            run(db,f"INSERT INTO cm_access(chat_id,command,min_level,enabled,updated) VALUES({p},{p},{p},{p},{p}) ON CONFLICT(chat_id,command) DO UPDATE SET min_level=excluded.min_level,enabled=excluded.enabled,updated=excluded.updated",(chat,name,level,enabled,stamp()))
            return await m.answer("Настройка доступа сохранена.")
        if cmd in ("triggeradd","triggerdel","triggers","триггеры"):
            if not db.is_admin(uid): return await m.answer("⛔ Только администратор FENIX.")
            if cmd=="triggeradd":
                if "=>" not in arg: return await m.answer("Формат: !triggeradd фраза => ответ")
                phrase,response=[x.strip() for x in arg.split("=>",1)]
                if not phrase or not response: return await m.answer("Нужны фраза и ответ.")
                run(db,f"INSERT INTO cm_triggers(chat_id,phrase,response,created_by,created) VALUES({p},{p},{p},{p},{p},{p})",(chat,phrase,response,uid,stamp()))
                return await m.answer("Автоответ добавлен.")
            if cmd=="triggerdel":
                run(db,f"DELETE FROM cm_triggers WHERE chat_id={p} AND lower(phrase)=lower({p})",(chat,arg.strip()))
                return await m.answer("Автоответ удалён, если существовал.")
            items=rows(db,f"SELECT id,phrase,response FROM cm_triggers WHERE chat_id={p} ORDER BY id DESC LIMIT 20",(chat,))
            return await m.answer("<b>АВТООТВЕТЫ</b>\n"+("\n".join(f"#{x['id']} · {x['phrase']} → {x['response']}}" for x in items) or "Список пуст."),parse_mode="HTML")
        if cmd in ("antispam","антиспам"):
            if not db.is_admin(uid): return await m.answer("⛔ Только администратор FENIX.")
            key=f"cm_antispam:{chat}"; state=str(db.setting(key,"off") or "off").lower()
            value=args[0].lower() if args else "status"
            if value in ("on","вкл"): state="on"; db.set_setting(key,state)
            elif value in ("off","выкл"): state="off"; db.set_setting(key,state)
            elif value!="status": return await m.answer("Формат: !antispam on|off|status")
            return await m.answer("Антиспам "+("включён." if state=="on" else "выключен."))
        if cmd in ("circle","круг"):
            sub=args[0].lower() if args else "list"; name=" ".join(args[1:]).strip()
            if sub=="create" and name:
                try: run(db,f"INSERT INTO iris_clans(chat_id,name,owner,created) VALUES({p},{p},{p},{p})",(chat,"Круг: "+name[:35],uid,stamp()))
                except Exception: return await m.answer("Круг с таким названием уже есть.")
                clan=one(db,f"SELECT id FROM iris_clans WHERE chat_id={p} AND name={p}",(chat,"Круг: "+name[:35]))
                run(db,f"INSERT INTO iris_clan_members(chat_id,clan_id,uid,joined) VALUES({p},{p},{p},{p})",(chat,clan["id"],uid,stamp()))
                return await m.answer(f"Круг «{name[:35]}» создан.")
            if sub in ("join","leave") and name:
                clan=one(db,f"SELECT id FROM iris_clans WHERE chat_id={p} AND name={p}",(chat,"Круг: "+name[:35]))
                if not clan: return await m.answer("Круг не найден.")
                if sub=="join":
                    run(db,f"INSERT INTO iris_clan_members(chat_id,clan_id,uid,joined) VALUES({p},{p},{p},{p}) ON CONFLICT(chat_id,uid) DO UPDATE SET clan_id=excluded.clan_id,joined=excluded.joined",(chat,clan["id"],uid,stamp()))
                else: run(db,f"DELETE FROM iris_clan_members WHERE chat_id={p} AND uid={p} AND clan_id={p}",(chat,uid,clan["id"]))
                return await m.answer("Готово.")
            items=rows(db,f"SELECT name FROM iris_clans WHERE chat_id={p} AND name LIKE 'Круг:%' ORDER BY name",(chat,))
            return await m.answer("<b>КРУГИ</b>\n"+("\n".join("• "+x["name"][6:] for x in items) or "Кругов пока нет. !circle create название"),parse_mode="HTML")
        if cmd in ("coin","монетка"):
            return await m.answer("🪙 "+random.choice(["Орёл","Решка"]))
        if cmd in ("profile","профиль"):
            who=await target(m,args) or uid
            rep=one(db,f"SELECT score FROM iris_rep WHERE chat_id={p} AND uid={p}",(chat,who))
            nick=one(db,f"SELECT nick FROM cm_nicks WHERE chat_id={p} AND uid={p}",(chat,who))
            warns=one(db,f"SELECT COUNT(*) AS n FROM cm_warns WHERE chat_id={p} AND uid={p} AND active=1",(chat,who))
            return await m.answer(f"<b>ПРОФИЛЬ УЧАСТНИКА</b>\nID: <code>{who}</code>\nНик: {(nick or {}).get('nick') or 'не задан'}\nРепутация: {(rep or {}).get('score',0)}\nПредупреждения: {(warns or {}).get('n',0)}",parse_mode="HTML")
        if cmd in ("rep","реп"):
            who=await target(m,args)
            if not who: return await m.answer("Ответь на сообщение участника командой !rep.")
            if who==uid: return await m.answer("Нельзя повышать собственную репутацию.")
            recent=one(db,f"SELECT created FROM iris_rep WHERE chat_id={p} AND uid={p}",(chat,who))
            # A daily per-giver ledger prevents repeated farming.
            with db.con() as c:
                if db.use_postgres: c.execute("CREATE TABLE IF NOT EXISTS iris_rep_log(chat_id BIGINT,giver BIGINT,target BIGINT,created TEXT,PRIMARY KEY(chat_id,giver,target))")
                else: c.execute("CREATE TABLE IF NOT EXISTS iris_rep_log(chat_id INTEGER,giver INTEGER,target INTEGER,created TEXT,PRIMARY KEY(chat_id,giver,target))")
            old=one(db,f"SELECT created FROM iris_rep_log WHERE chat_id={p} AND giver={p} AND target={p}",(chat,uid,who))
            if old and old["created"][:10]==stamp()[:10]: return await m.answer("Ты уже выдавал репутацию этому участнику сегодня.")
            if db.use_postgres: run(db,f"INSERT INTO iris_rep(chat_id,uid,score) VALUES({p},{p},1) ON CONFLICT(chat_id,uid) DO UPDATE SET score=iris_rep.score+1",(chat,who))
            else: run(db,f"INSERT INTO iris_rep(chat_id,uid,score) VALUES({p},{p},1) ON CONFLICT(chat_id,uid) DO UPDATE SET score=score+1",(chat,who))
            if db.use_postgres: run(db,f"INSERT INTO iris_rep_log(chat_id,giver,target,created) VALUES({p},{p},{p},{p}) ON CONFLICT(chat_id,giver,target) DO UPDATE SET created=excluded.created",(chat,uid,who,stamp()))
            else: run(db,f"INSERT INTO iris_rep_log(chat_id,giver,target,created) VALUES({p},{p},{p},{p}) ON CONFLICT(chat_id,giver,target) DO UPDATE SET created=excluded.created",(chat,uid,who,stamp()))
            return await m.answer("⭐ Репутация повышена на +1.")
        if cmd in ("note","заметка"):
            sub=args[0].lower() if args else "list"; body=" ".join(args[1:])
            if sub=="add" and body:
                cur=run(db,f"INSERT INTO iris_notes(chat_id,uid,note,created) VALUES({p},{p},{p},{p})",(chat,uid,body[:1000],stamp()))
                return await m.answer(f"📝 Заметка сохранена. ID: {getattr(cur,'lastrowid','см. список')}")
            if sub in ("del","delete") and len(args)>1 and args[1].isdigit():
                run(db,f"DELETE FROM iris_notes WHERE chat_id={p} AND uid={p} AND id={p}",(chat,uid,int(args[1]))); return await m.answer("Заметка удалена, если принадлежала тебе.")
            return await m.answer("<b>ТВОИ ЗАМЕТКИ</b>\n"+("\n".join(f"#{x['id']} · {x['note']}" for x in rows(db,f"SELECT id,note FROM iris_notes WHERE chat_id={p} AND uid={p} ORDER BY id DESC LIMIT 10",(chat,uid))) or "Заметок нет.")+"\n\nДобавить: !note add текст",parse_mode="HTML")
        if cmd in ("notes","заметки"):
            return await m.answer("<b>ТВОИ ЗАМЕТКИ</b>\n"+("\n".join(f"#{x['id']} · {x['note']}" for x in rows(db,f"SELECT id,note FROM iris_notes WHERE chat_id={p} AND uid={p} ORDER BY id DESC LIMIT 10",(chat,uid))) or "Заметок нет."),parse_mode="HTML")
        if cmd in ("bookmark","закладка"):
            if not m.reply_to_message: return await m.answer("Ответь командой !bookmark на сообщение, которое нужно сохранить.")
            text=(m.reply_to_message.text or m.reply_to_message.caption or "")[:700]
            run(db,f"INSERT INTO iris_bookmarks(chat_id,uid,message_id,text,created) VALUES({p},{p},{p},{p},{p})",(chat,uid,m.reply_to_message.message_id,text,stamp()))
            return await m.answer("🔖 Сообщение добавлено в закладки.")
        if cmd in ("bookmarks","закладки"):
            rr=rows(db,f"SELECT id,message_id,text FROM iris_bookmarks WHERE chat_id={p} AND uid={p} ORDER BY id DESC LIMIT 10",(chat,uid))
            return await m.answer("<b>ЗАКЛАДКИ</b>\n"+("\n".join(f"#{x['id']} · msg {x['message_id']} · {x['text'] or '[медиа]'}" for x in rr) or "Закладок нет."),parse_mode="HTML")
        if cmd in ("clan","клан"):
            sub=args[0].lower() if args else "info"; name=" ".join(args[1:])
            if sub=="create" and name:
                try: run(db,f"INSERT INTO iris_clans(chat_id,name,owner,created) VALUES({p},{p},{p},{p})",(chat,name[:40],uid,stamp()))
                except Exception: return await m.answer("Клан с таким названием уже существует.")
                clan=one(db,f"SELECT id FROM iris_clans WHERE chat_id={p} AND name={p}",(chat,name[:40]))
                run(db,f"INSERT INTO iris_clan_members(chat_id,clan_id,uid,joined) VALUES({p},{p},{p},{p})",(chat,clan["id"],uid,stamp()))
                return await m.answer(f"🏰 Клан «{name[:40]}» создан.")
            if sub=="join" and name:
                clan=one(db,f"SELECT id FROM iris_clans WHERE chat_id={p} AND name={p}",(chat,name[:40]))
                if not clan: return await m.answer("Клан не найден.")
                if db.use_postgres: run(db,f"INSERT INTO iris_clan_members(chat_id,clan_id,uid,joined) VALUES({p},{p},{p},{p}) ON CONFLICT(chat_id,uid) DO UPDATE SET clan_id=excluded.clan_id,joined=excluded.joined",(chat,clan["id"],uid,stamp()))
                else: run(db,f"INSERT INTO iris_clan_members(chat_id,clan_id,uid,joined) VALUES({p},{p},{p},{p}) ON CONFLICT(chat_id,uid) DO UPDATE SET clan_id=excluded.clan_id,joined=excluded.joined",(chat,clan["id"],uid,stamp()))
                return await m.answer(f"Ты вступил в клан «{name[:40]}».")
            if sub=="leave":
                run(db,f"DELETE FROM iris_clan_members WHERE chat_id={p} AND uid={p}",(chat,uid)); return await m.answer("Ты покинул клан.")
            clan=one(db,f"SELECT c.name,c.owner,COUNT(m.uid) AS members FROM iris_clans c LEFT JOIN iris_clan_members m ON m.clan_id=c.id WHERE c.chat_id={p} GROUP BY c.id,c.name,c.owner ORDER BY members DESC LIMIT 1",(chat,))
            return await m.answer(f"🏰 Клан: {clan['name']} · участников: {clan['members']}" if clan else "Кланов пока нет. Создай: !clan create название")
        if cmd in ("marry","брак"):
            who=await target(m,args)
            if not who or who==uid: return await m.answer("Ответь командой !marry на сообщение другого участника.")
            a,b=sorted((uid,who))
            kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💍 Принять",callback_data=f"irm:yes:{chat}:{a}:{b}"),InlineKeyboardButton(text="Отклонить",callback_data=f"irm:no:{chat}:{a}:{b}")]])
            run(db,f"INSERT INTO iris_pairs(chat_id,a,b,status,created) VALUES({p},{p},{p},'pending',{p}) ON CONFLICT(chat_id,a,b) DO UPDATE SET status='pending',created=excluded.created",(chat,a,b,stamp()))
            return await m.answer(f"💍 {m.from_user.full_name} предлагает создать пару с участником <code>{who}</code>.",parse_mode="HTML",reply_markup=kb)
        if cmd in ("divorce","развод"):
            who=await target(m,args)
            if not who: return await m.answer("Ответь командой !divorce на сообщение партнёра.")
            a,b=sorted((uid,who)); run(db,f"UPDATE iris_pairs SET status='ended' WHERE chat_id={p} AND a={p} AND b={p}",(chat,a,b)); return await m.answer("Отношения завершены.")
        if cmd in ("timer","таймер"):
            if len(args)<2: return await m.answer("Формат: !timer 10m текст напоминания")
            match=re.fullmatch(r"(\d+)(s|m|h)",args[0].lower())
            if not match: return await m.answer("Время: 30s, 10m или 2h.")
            seconds=int(match.group(1))*{"s":1,"m":60,"h":3600}[match.group(2)]
            if seconds>86400: return await m.answer("Максимум — 24 часа.")
            message=" ".join(args[1:])
            async def remind():
                await asyncio.sleep(seconds)
                try: await bot.send_message(chat,f"⏰ Напоминание для {m.from_user.full_name}: {message}")
                except Exception: log.exception("Timer delivery failed")
            asyncio.create_task(remind())
            return await m.answer(f"⏰ Напоминание установлено на {args[0]}. Важно: таймеры в текущей версии сбрасываются при перезапуске бота.")
        if cmd=="gstop":
            if not args: return await m.answer("Формат: !gstop ID")
            gid=args[0]
            giveaway=one(db,f"SELECT * FROM iris_giveaways WHERE id={p} AND chat_id={p}",(gid,chat))
            if not giveaway: return await m.answer("Розыгрыш не найден.")
            if uid!=int(giveaway["owner"]) and not db.is_admin(uid): return await m.answer("Недостаточно прав.")
            run(db,f"UPDATE iris_giveaways SET status='cancelled' WHERE id={p}",(gid,))
            return await m.answer("Розыгрыш отменён.")
        if cmd in ("giveaway","розыгрыш"):
            if len(args)<2: return await m.answer("Формат: !giveaway 10m приз")
            mt=re.fullmatch(r"(\d+)(m|h)",args[0].lower())
            if not mt: return await m.answer("Укажи время: 10m или 2h.")
            seconds=int(mt.group(1))*{"m":60,"h":3600}[mt.group(2)]
            if seconds>7*86400: return await m.answer("Максимум 7 дней.")
            gid=secrets.token_hex(4); prize=" ".join(args[1:])[:120]; ends=(datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat()
            run(db,f"INSERT INTO iris_giveaways(id,chat_id,owner,prize,ends,status) VALUES({p},{p},{p},{p},{p},'active')",(gid,chat,uid,prize,ends))
            kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎉 Участвовать",callback_data=f"irg:join:{gid}")]])
            await m.answer(f"🎉 <b>РОЗЫГРЫШ</b>\nПриз: {prize}\nЗавершение: через {args[0]}",parse_mode="HTML",reply_markup=kb)
            async def finish():
                await asyncio.sleep(seconds)
                run(db,f"UPDATE iris_giveaways SET status='finished' WHERE id={p} AND status='active'",(gid,))
                users=rows(db,f"SELECT uid FROM iris_giveaway_users WHERE gid={p}",(gid,))
                winner=random.choice(users) if users else None
                await bot.send_message(chat,f"🏆 Розыгрыш «{prize}» завершён. Победитель: <code>{winner['uid']}</code>" if winner else f"Розыгрыш «{prize}» завершён без участников.",parse_mode="HTML")
            asyncio.create_task(finish())
            return
    @router.callback_query(F.data.startswith("irm:"))
    async def relationship(c):
        _,action,chat,a,b=c.data.split(":"); chat=int(chat); a=int(a); b=int(b)
        if c.from_user.id!=b: return await c.answer("Предложение может принять только второй участник.",show_alert=True)
        p=ph(db)
        run(db,f"UPDATE iris_pairs SET status={p} WHERE chat_id={p} AND a={p} AND b={p} AND status='pending'",("married" if action=="yes" else "declined",chat,a,b))
        await c.answer("Согласие сохранено" if action=="yes" else "Предложение отклонено")
        await c.message.edit_reply_markup(reply_markup=None)
        if action=="yes": await c.message.answer("💍 Поздравляем! Пара создана.")
    dp.include_router(router)
    log.info("FENIX Iris social modules registered")
