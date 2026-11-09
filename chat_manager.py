import re
import json
import logging
from datetime import datetime, timedelta, timezone
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

log = logging.getLogger("fenix.chat_manager")
ROLE_LEVELS = {
    "owner": 100, "владелец": 100,
    "главный администратор": 80, "главный_администратор": 80, "главный": 80,
    "администратор": 60, "admin": 60,
    "модератор": 40, "moder": 40,
    "помощник": 20, "helper": 20,
}
ROLE_NAMES = {100:"Владелец",80:"Главный администратор",60:"Администратор",40:"Модератор",20:"Помощник"}
ALIASES = {
 "help":"help","cmds":"help","команды":"help","помощь":"help",
 "start":"start","начать":"start","ping":"ping","пинг":"ping","status":"ping","статус":"ping","test":"ping","тест":"ping",
 "rules":"rules","правила":"rules","setup":"setup","settings":"settings","setsettings":"setsettings",
 "settingsmute":"settingsmute","settingsinvite":"settingsinvite","welcome":"welcome","setrules":"setrules",
 "admins":"admins","staff":"admins","админы":"admins", "stats":"stats","стата":"stats","статистика":"stats","reg":"reg","рег":"reg","getban":"getban","гетбан":"getban","online":"online","онлайн":"online","wipe":"wipe","вайп":"wipe","newrole":"newrole","deleterole":"deleterole","delrole":"deleterole","editunity":"editunity","voice":"voice","mafia":"mafia","мафия":"mafia","emoji":"emoji","эмодзи":"emoji","enick":"enick","никэмодзи":"enick","chatinfo":"chatinfo","info":"chatinfo","инфо":"chatinfo","чатинфо":"chatinfo",
 "mute":"mute","мут":"mute","unmute":"unmute","унмут":"unmute","kick":"kick","кик":"kick","исключить":"kick",
 "warn":"warn","варн":"warn","пред":"warn","unwarn":"unwarn","унварн":"unwarn","getwarn":"getwarn","предупреждения":"getwarn",
 "warnhistory":"warnhistory","историяварнов":"warnhistory","warnlist":"warnlist","преды":"warnlist",
 "ban":"ban","блок":"ban","unban":"unban","унблок":"unban","banlist":"banlist",
 "addhelper":"addhelper","helper":"addhelper","addmoder":"addmoder","moder":"addmoder","addadmin":"addadmin",
 "setrole":"setrole","role":"setrole","removerole":"removerole","rr":"removerole","roles":"roles","роли":"roles",
 "filters":"filters","фильтры":"filters","filteradd":"filteradd","filterdel":"filterdel","filteredit":"filteredit",
 "addlink":"addlink","whitelistlinks":"whitelistlinks","logs":"logs","логи":"logs",
 "nick":"nick","getnick":"nick","gnick":"nick","ник":"nick","setnick":"setnick","snick":"setnick",
 "removenick":"removenick","rnick":"removenick","nicknames":"nicknames","nlist":"nicknames",
 "nonames":"nonames","безников":"nonames","getbynick":"getbynick","понику":"getbynick",
 "unity":"unity","unites":"unites","addunity":"addunity","removeunity":"removeunity","editunity":"editunity","deleteunity":"deleteunity",
 "pin":"pin","закрепить":"pin","unpin":"unpin","открепить":"unpin","silence":"silence","тишина":"silence","zov":"zov","вызов":"zov","зов":"zov",
 "try":"try","попытка":"try","kiss":"kiss","поцелуй":"kiss","поцеловать":"kiss","obnyat":"hug","обнять":"hug","report":"report","репорт":"report",
}
def ph(db): return "%s" if db.use_postgres else "?"
def now(db): return db._now()
def q(db, sql, args=()):
    with db.con() as c: return c.execute(sql,args)
def rows(db, sql, args=()):
    with db.con() as c: return [dict(x) for x in c.execute(sql,args).fetchall()]
def one(db, sql, args=()):
    with db.con() as c:
        x=c.execute(sql,args).fetchone()
        return dict(x) if x else None
def init_schema(db):
    with db.con() as c:
        if db.use_postgres:
            c.execute("""CREATE TABLE IF NOT EXISTS cm_roles(chat_id BIGINT,uid BIGINT,level INTEGER,title TEXT,by_uid BIGINT,updated TEXT,PRIMARY KEY(chat_id,uid))""")
            c.execute("""CREATE TABLE IF NOT EXISTS cm_settings(chat_id BIGINT PRIMARY KEY,title TEXT,welcome TEXT,rules TEXT,mute_mode TEXT DEFAULT 'on',invite_mode TEXT DEFAULT 'on',silence INTEGER DEFAULT 0,created TEXT,updated TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS cm_warns(id BIGSERIAL PRIMARY KEY,chat_id BIGINT,uid BIGINT,by_uid BIGINT,reason TEXT,created TEXT,active INTEGER DEFAULT 1)""")
            c.execute("""CREATE TABLE IF NOT EXISTS cm_logs(id BIGSERIAL PRIMARY KEY,chat_id BIGINT,actor BIGINT,action TEXT,target BIGINT,details TEXT,created TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS cm_filters(id BIGSERIAL PRIMARY KEY,chat_id BIGINT,phrase TEXT,created_by BIGINT,created TEXT,UNIQUE(chat_id,phrase))""")
            c.execute("""CREATE TABLE IF NOT EXISTS cm_links(id BIGSERIAL PRIMARY KEY,chat_id BIGINT,url TEXT,created_by BIGINT,created TEXT,UNIQUE(chat_id,url))""")
            c.execute("""CREATE TABLE IF NOT EXISTS cm_nicks(chat_id BIGINT,uid BIGINT,nick TEXT,by_uid BIGINT,updated TEXT,PRIMARY KEY(chat_id,uid))""")
            c.execute("""CREATE TABLE IF NOT EXISTS cm_unities(id BIGSERIAL PRIMARY KEY,name TEXT UNIQUE,owner_chat BIGINT,created_by BIGINT,created TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS cm_unity_chats(chat_id BIGINT PRIMARY KEY,unity_id BIGINT,added_by BIGINT,created TEXT)""")
        else:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS cm_roles(chat_id INTEGER,uid INTEGER,level INTEGER,title TEXT,by_uid INTEGER,updated TEXT,PRIMARY KEY(chat_id,uid));
            CREATE TABLE IF NOT EXISTS cm_settings(chat_id INTEGER PRIMARY KEY,title TEXT,welcome TEXT,rules TEXT,mute_mode TEXT DEFAULT 'on',invite_mode TEXT DEFAULT 'on',silence INTEGER DEFAULT 0,created TEXT,updated TEXT);
            CREATE TABLE IF NOT EXISTS cm_warns(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,uid INTEGER,by_uid INTEGER,reason TEXT,created TEXT,active INTEGER DEFAULT 1);
            CREATE TABLE IF NOT EXISTS cm_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,actor INTEGER,action TEXT,target INTEGER,details TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS cm_filters(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,phrase TEXT,created_by INTEGER,created TEXT,UNIQUE(chat_id,phrase));
            CREATE TABLE IF NOT EXISTS cm_links(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,url TEXT,created_by INTEGER,created TEXT,UNIQUE(chat_id,url));
            CREATE TABLE IF NOT EXISTS cm_nicks(chat_id INTEGER,uid INTEGER,nick TEXT,by_uid INTEGER,updated TEXT,PRIMARY KEY(chat_id,uid));
            CREATE TABLE IF NOT EXISTS cm_unities(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE,owner_chat INTEGER,created_by INTEGER,created TEXT);
            CREATE TABLE IF NOT EXISTS cm_unity_chats(chat_id INTEGER PRIMARY KEY,unity_id INTEGER,added_by INTEGER,created TEXT);
            """)
def get_role(db, chat_id, uid):
    r=one(db,f"SELECT level,title FROM cm_roles WHERE chat_id={ph(db)} AND uid={ph(db)}",(chat_id,uid))
    return (int(r["level"]),r["title"]) if r else (0,"Участник")
def log_action(db, chat, actor, action, target=None, details=""):
    q(db,f"INSERT INTO cm_logs(chat_id,actor,action,target,details,created) VALUES({','.join([ph(db)]*6)})",(chat,actor,action,target,details,now(db)))
def can(db, chat, uid, level):
    return get_role(db,chat,uid)[0] >= level
def parse_target(m, args):
    if m.reply_to_message and m.reply_to_message.from_user: return m.reply_to_message.from_user.id, args
    if not args: return None,args
    token=args[0]
    if token.lstrip("-").isdigit(): return int(token),args[1:]
    hit=re.search(r"(?:user\?id=|t\.me/)(\d{5,})",token)
    if hit: return int(hit.group(1)),args[1:]
    if token.startswith("@"):
        return None,args
    return None,args
def chat_settings(db, chat):
    p=ph(db)
    x=one(db,f"SELECT * FROM cm_settings WHERE chat_id={p}",(chat,))
    if not x:
        title=""
        q(db,f"INSERT INTO cm_settings(chat_id,title,created,updated) VALUES({p},{p},{p},{p})",(chat,title,now(db),now(db)))
        x=one(db,f"SELECT * FROM cm_settings WHERE chat_id={p}",(chat,))
    return x
def duration(text):
    m=re.fullmatch(r"(\d+)(s|m|h|d)?",text.lower())
    if not m: return 3600
    n=int(m.group(1)); unit=m.group(2) or "m"
    return n*{"s":1,"m":60,"h":3600,"d":86400}[unit]
def register_chat_manager(dp, bot, db, owner_ids):
    init_schema(db)
    router=Router(name="fenix_chat_manager")
    owner_ids=set(owner_ids or ())
    async def ensure_creator(m):
        if m.chat.type=="private": return
        try:
            cm=await bot.get_chat_member(m.chat.id,m.from_user.id)
            if cm.status=="creator":
                p=ph(db); q(db,f"INSERT INTO cm_roles(chat_id,uid,level,title,by_uid,updated) VALUES({','.join([p]*6)}) ON CONFLICT(chat_id,uid) DO UPDATE SET level=100,title='Владелец',updated=excluded.updated",(m.chat.id,m.from_user.id,100,"Владелец",m.from_user.id,now(db)))
        except Exception: pass
    async def reply(m,text,markup=None):
        await m.reply(text,reply_markup=markup,parse_mode="HTML",disable_web_page_preview=True)
    async def target_name(chat,uid):
        try:
            x=await bot.get_chat_member(chat,uid); u=x.user
            return f"{u.full_name} (<code>{uid}</code>)"
        except Exception: return f"<code>{uid}</code>"
    async def do_mute(m, uid, seconds, reason):
        until=datetime.now(timezone.utc)+timedelta(seconds=seconds)
        from aiogram.types import ChatPermissions
        await bot.restrict_chat_member(m.chat.id,uid,ChatPermissions(can_send_messages=False,can_send_audios=False,can_send_documents=False,can_send_photos=False,can_send_videos=False,can_send_video_notes=False,can_send_voice_notes=False,can_send_polls=False,can_send_other_messages=False,can_add_web_page_previews=False),until_date=until)
        log_action(db,m.chat.id,m.from_user.id,"mute",uid,f"{seconds}s; {reason}")
    @router.message(F.new_chat_members)
    async def joined(m:Message):
        s=chat_settings(db,m.chat.id)
        for u in m.new_chat_members:
            if u.is_bot: continue
            if s.get("welcome"): await m.answer(s["welcome"].replace("{name}",u.full_name).replace("{id}",str(u.id)))
    @router.message(F.text)
    async def command_handler(m:Message):
        raw=(m.text or "").strip()
        if raw.lower().startswith("/chatmanager"):
            if m.from_user.id not in owner_ids and not db.is_admin(m.from_user.id):
                return await m.answer("⛔ Доступ только владельцу FENIX.")
            chats=rows(db,"SELECT chat_id,title,updated FROM cm_settings ORDER BY updated DESC LIMIT 50")
            if not chats:
                keyboard=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Как подключить беседу",callback_data="cmui:connect")],
                    [InlineKeyboardButton(text="Обновить",callback_data="cmui:home")]
                ])
                return await m.answer("<b>FENIX · УПРАВЛЕНИЕ БЕСЕДАМИ</b>\n\nПока не подключено ни одной группы.\n\n1. Добавь FENIX в нужную группу.\n2. Выдай боту права администратора: удаление сообщений, блокировка участников и закрепление.\n3. После добавления открой эту панель снова — группа появится автоматически.",parse_mode="HTML",reply_markup=keyboard)
            keyboard=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=(x["title"] or "Беседа")[:32],callback_data=f"cmui:chat:{x['chat_id']}")] for x in chats
            ]+[[InlineKeyboardButton(text="Обновить список",callback_data="cmui:home")]])
            return await m.answer("<b>FENIX MANAGER</b>\nВыбери беседу для управления:",parse_mode="HTML",reply_markup=keyboard)
        command_text=raw
        is_command=raw.startswith(("!","." ,"/")) or raw.lower().startswith(("ирис ","ириска "))
        if not is_command:
            if m.chat.type!="private":
                s=chat_settings(db,m.chat.id)
                if s.get("silence") and not can(db,m.chat.id,m.from_user.id,40):
                    try: await m.delete()
                    except Exception: pass
                    return
                filters=rows(db,f"SELECT phrase FROM cm_filters WHERE chat_id={ph(db)}",(m.chat.id,))
                low=raw.casefold()
                if any(x["phrase"].casefold() in low for x in filters):
                    try: await m.delete()
                    except Exception: pass
                elif re.search(r"https?://|t\.me/",raw,re.I) and not can(db,m.chat.id,m.from_user.id,40):
                    allowed=rows(db,f"SELECT url FROM cm_links WHERE chat_id={ph(db)}",(m.chat.id,))
                    if not any(x["url"].lower() in raw.lower() for x in allowed):
                        try: await m.delete()
                        except Exception: pass
            return
        if raw.lower().startswith(("ирис ","ириска ")):
            command_text=raw.split(maxsplit=1)[1]
        else:
            command_text=raw[1:]
        parts=command_text.split(maxsplit=1); name=parts[0].lower().split("@")[0] if parts else ""; argtext=parts[1] if len(parts)>1 else ""
        cmd=ALIASES.get(name)
        if not cmd: return
        if m.chat.type=="private":
            if cmd in ("help","ping"): 
                return await reply(m,"<b>FENIX MANAGER</b>\nКоманды управления работают внутри привязанной группы. Добавь бота в беседу и выдай права администратора.")
            return
        await ensure_creator(m)
        chat=m.chat.id; uid=m.from_user.id; args=argtext.split()
        access=one(db,f"SELECT min_level,enabled FROM cm_access WHERE chat_id={ph(db)} AND command={ph(db)}",(chat,cmd))
        if access and (not int(access.get("enabled",1)) or get_role(db,chat,uid)[0] < int(access.get("min_level",0))):
            return await reply(m,"⛔ Доступ к этой команде ограничен настройками беседы.")
        if cmd=="help":
            text = (
                "<b>📘 FENIX MANAGER — СПРАВОЧНИК КОМАНД</b>\n\n"
                "<b>👤 Участник</b>\n"
                "<code>!help</code> — справочник; <code>!ping</code> — статус; <code>!rules</code> — правила; <code>!admins</code> — руководство.\n"
                "<code>!report текст</code> — жалоба; <code>!try</code> — попытка; <code>!kiss</code> — поцеловать; <code>!obnyat</code> — обнять.\n\n"
                "<b>🛡 Помощник · 20</b>\n"
                "<code>!stats</code> — статистика; <code>!chatinfo</code> — информация о чате; <code>!logs</code> — журнал.\n"
                "<code>!mute 15m причина</code> — мут; <code>!unmute</code> — снять мут; <code>!kick</code> — исключить.\n"
                "<code>!warn причина</code> — предупреждение; <code>!unwarn</code> — снять; <code>!getwarn</code> — проверить.\n"
                "<code>!warnhistory</code> — история; <code>!warnlist</code> — список.\n"
                "<code>!getnick</code>, <code>!setnick ник</code>, <code>!removenick</code>, <code>!nicknames</code>, <code>!nonames</code>, <code>!getbynick ник</code>, <code>!zov</code>.\n\n"
                "<b>🔨 Модератор · 40</b>\n"
                "<code>!ban</code> — блокировка; <code>!unban ID</code> — разблокировка; <code>!banlist</code> — список.\n"
                "<code>!addhelper ID</code>, <code>!setrole ID роль</code>, <code>!removerole ID</code>, <code>!roles</code>, <code>!silence</code>, <code>!wipe N</code>.\n\n"
                "<b>⚙️ Администратор · 60</b>\n"
                "<code>!addmoder ID</code>, <code>!addadmin ID</code> — назначение; <code>!filters</code> — фильтры.\n"
                "<code>!filteradd фраза</code>, <code>!filterdel фраза</code>, <code>!addlink URL</code>, <code>!whitelistlinks</code>.\n\n"
                "<b>👑 Главный администратор · 80</b>\n"
                "<code>!pin</code>, <code>!unpin</code>, <code>!newrole название уровень</code>, <code>!deleterole название</code>, <code>!welcome текст</code>, <code>!setrules текст</code>.\n\n"
                "<b>🔥 Владелец · 100</b>\n"
                "<code>!setup</code>, <code>!settings</code>, <code>!setsettings</code>, <code>!settingsmute</code>, <code>!settingsinvite</code>.\n"
                "<code>!unity</code>, <code>!unites</code>, <code>!addunity название</code>, <code>!removeunity</code>, <code>!editunity название</code>, <code>!deleteunity название</code>.\n\n"
                "<b>🧩 Дополнительные модули</b>\n"
                "<code>!note add/list/del</code> — заметки; <code>!bookmark</code>/<code>!bookmarks</code> — закладки.\n"
                "<code>!timer 10m текст</code>, <code>!timers</code>, <code>!timerdel ID</code> — таймеры.\n"
                "<code>!vote вопрос | вариант 1 | вариант 2</code>, <code>!voteresult ID</code>, <code>!voteclose ID</code> — голосования.\n"
                "<code>!access команда уровень|off</code> — доступ; <code>!triggeradd фраза => ответ</code>, <code>!triggers</code>, <code>!triggerdel ID</code> — автоответы.\n"
                "<code>!purge N</code>, <code>!del</code> — удаление; <code>!dice</code>, <code>!duel</code> — игры.\n"
                "<code>!rep</code>, <code>!топреп</code> — репутация; <code>!circle create/join/leave/info/list</code> — круги.\n"
                "<code>!giveaway 1h приз</code>, <code>!gstop ID</code> — розыгрыши; <code>!antispam on|off|status</code> — антиспам.\n\n"
                "<b>⭐ Stars-магазин</b>\n"
                "<code>/myid</code> — мой ID; <code>/giftshop ID</code> — магазин; <code>/premiumgift ID</code> — Premium-подарок; <code>/starsorders</code> — заказы.\n\n"
                "<b>📌 Общие правила</b>\n"
                "Префиксы: <code>!</code>, <code>.</code>, <code>/</code>. Для команды над участником ответь на его сообщение или укажи числовой Telegram ID.\n"
                "Время: <code>30s</code> — секунды, <code>15m</code> — минуты, <code>2h</code> — часы, <code>3d</code> — дни."
            )
            return await reply(m, text)

        if cmd=="start":
            return await reply(m,"<b>FENIX MANAGER подключён</b>\nБеседа: "+(m.chat.title or "без названия")+"\nДля списка возможностей используй !help.")
        if cmd=="ping":
            return await reply(m,"<b>FENIX MANAGER</b>\nСтатус: работает\nБеседа: активна")
        if cmd=="rules":
            s=chat_settings(db,chat); return await reply(m,s.get("rules") or "Правила беседы ещё не настроены.")
        if cmd=="setup":
            if not can(db,chat,uid,100) and uid not in owner_ids: return await reply(m,"⛔ Команда доступна владельцу беседы.")
            s=chat_settings(db,chat)
            return await reply(m,"<b>БЫСТРАЯ НАСТРОЙКА БЕСЕДЫ</b>\n\n1. Назначь бота администратором с правами удаления сообщений, блокировок и приглашений.\n2. Добавь администраторов командами !addadmin / !addmoder.\n3. Установи приветствие: !welcome текст\n4. Установи правила: !setrules текст\n5. Проверь настройки: !settings\n\nТекущий режим тишины: "+("включён" if s.get("silence") else "выключен"))
        if cmd in ("settings","settingsmute","settingsinvite"):
            if not can(db,chat,uid,100) and uid not in owner_ids: return await reply(m,"⛔ Только владелец беседы.")
            s=chat_settings(db,chat)
            return await reply(m,f"<b>НАСТРОЙКИ БЕСЕДЫ</b>\nПриветствие: {'установлено' if s.get('welcome') else 'не задано'}\nПравила: {'установлены' if s.get('rules') else 'не заданы'}\nОграничения: {s.get('mute_mode','on')}\nПриглашения: {s.get('invite_mode','on')}\nТишина: {'включена' if s.get('silence') else 'выключена'}\n\n!welcome текст\n!setrules текст\n!setsettings mute on|off\n!setsettings invite on|off\n!settingsmute — показать режим ограничений\n!settingsinvite — показать режим приглашений")
        if cmd=="setsettings":
            if not can(db,chat,uid,100) and uid not in owner_ids: return await reply(m,"⛔ Только владелец беседы.")
            a=args[0].lower() if args else ""; v=args[1].lower() if len(args)>1 else ""
            if a not in ("mute","invite") or v not in ("on","off"): return await reply(m,"Формат: !setsettings mute on|off или !setsettings invite on|off")
            col="mute_mode" if a=="mute" else "invite_mode"; p=ph(db)
            q(db,f"UPDATE cm_settings SET {col}={p},updated={p} WHERE chat_id={p}",(v,now(db),chat))
            log_action(db,chat,uid,"settings",None,f"{a}={v}"); return await reply(m,"✅ Настройка сохранена.")
        if cmd in ("welcome","setrules"):
            if not can(db,chat,uid,80) and uid not in owner_ids: return await reply(m,"⛔ Требуется уровень 80.")
            s=chat_settings(db,chat); col="welcome" if cmd=="welcome" else "rules"
            p=ph(db); q(db,f"UPDATE cm_settings SET {col}={p},updated={p} WHERE chat_id={p}",(argtext,now(db),chat))
            log_action(db,chat,uid,cmd,None,argtext[:500]); return await reply(m,"✅ Текст сохранён." if argtext else "Текст очищен.")
        if cmd=="chatinfo":
            s=chat_settings(db,chat)
            return await reply(m,f"<b>ИНФОРМАЦИЯ О БЕСЕДЕ</b>\nНазвание: {m.chat.title}\nID: <code>{chat}</code>\nТип: {m.chat.type}\nУчастники: {getattr(m.chat,'member_count','неизвестно')}\nРоли: {len(rows(db,f'SELECT uid FROM cm_roles WHERE chat_id={ph(db)}',(chat,)))}")
        if cmd=="admins":
            rr=rows(db,f"SELECT uid,level,title FROM cm_roles WHERE chat_id={ph(db)} AND level>0 ORDER BY level DESC",(chat,))
            if not rr: return await reply(m,"Состав руководства пока не настроен. Владелец может назначить роли.")
            return await reply(m,"<b>РУКОВОДСТВО БЕСЕДЫ</b>\n"+"\n".join(f"• {x['title']} — <code>{x['uid']}</code> · {x['level']}" for x in rr))
        if cmd=="roles":
            return await reply(m,"<b>ИЕРАРХИЯ FENIX</b>\nВладелец — 100\nГлавный администратор — 80\nАдминистратор — 60\nМодератор — 40\nПомощник — 20")
        if cmd in ("addhelper","addmoder","addadmin","setrole","removerole"):
            required={"addhelper":40,"addmoder":60,"addadmin":80,"setrole":80,"removerole":80}[cmd]
            if not can(db,chat,uid,required) and uid not in owner_ids: return await reply(m,f"⛔ Недостаточно прав. Требуется уровень {required}.")
            target,rest=parse_target(m,args)
            if not target: return await reply(m,"Укажи числовой Telegram ID или ответь на сообщение участника.")
            if cmd=="removerole":
                q(db,f"DELETE FROM cm_roles WHERE chat_id={ph(db)} AND uid={ph(db)}",(chat,target)); log_action(db,chat,uid,"role_remove",target); return await reply(m,"Роль снята.")
            level={"addhelper":20,"addmoder":40,"addadmin":60}.get(cmd)
            title={"addhelper":"Помощник","addmoder":"Модератор","addadmin":"Администратор"}.get(cmd)
            if cmd=="setrole":
                if len(rest)<1: return await reply(m,"Формат: !setrole ID роль (20/40/60/80)")
                try: level=int(rest[0])
                except: level=ROLE_LEVELS.get(rest[0].lower(),0)
                if level not in ROLE_NAMES: return await reply(m,"Допустимые уровни: 20, 40, 60, 80.")
                title=ROLE_NAMES[level]
            p=ph(db); q(db,f"INSERT INTO cm_roles(chat_id,uid,level,title,by_uid,updated) VALUES({','.join([p]*6)}) ON CONFLICT(chat_id,uid) DO UPDATE SET level=excluded.level,title=excluded.title,by_uid=excluded.by_uid,updated=excluded.updated",(chat,target,level,title,uid,now(db)))
            log_action(db,chat,uid,"role_set",target,title); return await reply(m,f"✅ Назначена роль <b>{title}</b> · уровень {level}.")
        if cmd in ("mute","unmute","kick","warn","unwarn","getwarn","warnhistory","warnlist","getnick","setnick","removenick","nicknames","nonames","getbynick","ban","unban","banlist","getban"):
            levels={"mute":20,"unmute":20,"kick":20,"warn":20,"unwarn":20,"getwarn":20,"warnhistory":20,"getnick":20,"setnick":20,"removenick":20,"nicknames":20,"nonames":20,"getbynick":20,"ban":40,"unban":40,"banlist":40,"getban":20,"warnlist":20}
            if not can(db,chat,uid,levels[cmd]) and uid not in owner_ids: return await reply(m,"⛔ Недостаточно прав для этой команды.")
            target,rest=parse_target(m,args)
            if cmd in ("nicknames","nonames","banlist","warnlist") and not target: rest=args
            if cmd=="nicknames":
                rr=rows(db,f"SELECT n.uid,n.nick,r.level,r.title FROM cm_nicks n LEFT JOIN cm_roles r ON r.chat_id=n.chat_id AND r.uid=n.uid WHERE n.chat_id={ph(db)} ORDER BY n.nick",(chat,))
                if not rr:
                    return await reply(m,"<b>👥 НИКНЕЙМЫ И ДОЛЖНОСТИ</b>\\nСписок пока пуст.")
                cards=[]
                for item in rr:
                    nickname=html.escape(str(item.get("nick") or "Без ника"))
                    level=int(item.get("level") or 0)
                    role=html.escape(str(item.get("title") or ROLE_NAMES.get(level,"Участник")))
                    cards.append(f"👤 <b>{nickname}</b> — <b>{role}</b>")
                return await reply(m,"<b>👥 НИКНЕЙМЫ И ДОЛЖНОСТИ</b>\\n\\n"+"\\n".join(cards))
            if cmd=="nonames":
                rr=rows(db,f"SELECT uid FROM cm_roles WHERE chat_id={ph(db)} AND level=0",(chat,))
                return await reply(m,"Участники без назначенной роли/ника: "+str(len(rr))+" (Telegram не предоставляет полный список участников боту).")
            if cmd=="banlist":
                rr=rows(db,f"SELECT uid,reason,created FROM cm_warns WHERE chat_id={ph(db)} AND active=2 ORDER BY id DESC LIMIT 30",(chat,))
                return await reply(m,"<b>БЛОКИРОВКИ</b>\n"+("\n".join(f"{x['uid']} · {x['reason']}" for x in rr) if rr else "Список пуст."))
            if cmd=="getbynick":
                if not rest: return await reply(m,"Формат: !getbynick ник")
                x=one(db,f"SELECT uid,nick FROM cm_nicks WHERE chat_id={ph(db)} AND lower(nick)=lower({ph(db)})",(chat," ".join(rest)))
                return await reply(m,f"Найден: <code>{x['uid']}</code> — {x['nick']}" if x else "Ник не найден.")
            if not target and cmd not in ("warnlist",): return await reply(m,"Укажи ID или ответь на сообщение участника.")
            if cmd=="warn":
                reason=" ".join(rest) or "Причина не указана"; p=ph(db)
                q(db,f"INSERT INTO cm_warns(chat_id,uid,by_uid,reason,created,active) VALUES({','.join([p]*6)})",(chat,target,uid,reason,now(db),1)); log_action(db,chat,uid,"warn",target,reason)
                count=one(db,f"SELECT COUNT(*) AS n FROM cm_warns WHERE chat_id={p} AND uid={p} AND active=1",(chat,target))["n"]
                return await reply(m,f"⚠️ Предупреждение выдано. Активных: {count}/3.")
            if cmd in ("getwarn","warnhistory"):
                rr=rows(db,f"SELECT id,reason,created,active FROM cm_warns WHERE chat_id={ph(db)} AND uid={ph(db)} ORDER BY id DESC LIMIT 20",(chat,target))
                return await reply(m,"<b>ИСТОРИЯ ПРЕДУПРЕЖДЕНИЙ</b>\n"+("\n".join(f"#{x['id']} · {x['reason']} · {'активно' if x['active']==1 else 'снято'}" for x in rr) if rr else "Предупреждений нет."))
            if cmd=="unwarn":
                x=one(db,f"SELECT id FROM cm_warns WHERE chat_id={ph(db)} AND uid={ph(db)} AND active=1 ORDER BY id DESC LIMIT 1",(chat,target))
                if x: q(db,f"UPDATE cm_warns SET active=0 WHERE id={ph(db)}",(x["id"],))
                log_action(db,chat,uid,"unwarn",target); return await reply(m,"Последнее активное предупреждение снято." if x else "Активных предупреждений нет.")
            if cmd=="warnlist":
                rr=rows(db,f"SELECT uid,COUNT(*) AS n FROM cm_warns WHERE chat_id={ph(db)} AND active=1 GROUP BY uid ORDER BY n DESC LIMIT 30")
                return await reply(m,"<b>АКТИВНЫЕ ПРЕДУПРЕЖДЕНИЯ</b>\n"+("\n".join(f"{x['uid']} — {x['n']}" for x in rr) if rr else "Список пуст."))
            if cmd=="mute":
                secs=duration(rest[0]) if rest and re.fullmatch(r"\d+(s|m|h|d)?",rest[0].lower()) else 3600
                reason=" ".join(rest[1:] if rest and re.fullmatch(r"\d+(s|m|h|d)?",rest[0].lower()) else rest) or "Причина не указана"
                try: await do_mute(m,target,secs,reason)
                except Exception as e: return await reply(m,"Не удалось выдать мут. Проверь права бота и статус участника.")
                return await reply(m,f"🔇 Участник ограничен на {secs} сек. Причина: {reason}")
            if cmd=="unmute":
                from aiogram.types import ChatPermissions
                try: await bot.restrict_chat_member(chat,target,ChatPermissions(can_send_messages=True,can_send_audios=True,can_send_documents=True,can_send_photos=True,can_send_videos=True,can_send_video_notes=True,can_send_voice_notes=True,can_send_polls=True,can_send_other_messages=True,can_add_web_page_previews=True))
                except Exception: return await reply(m,"Не удалось снять ограничение. Проверь права бота.")
                log_action(db,chat,uid,"unmute",target); return await reply(m,"Ограничение снято.")
            if cmd=="kick":
                reason=" ".join(rest) or "Без причины"
                try: await bot.ban_chat_member(chat,target); await bot.unban_chat_member(chat,target,only_if_banned=True)
                except Exception: return await reply(m,"Не удалось исключить участника. Проверь права бота.")
                log_action(db,chat,uid,"kick",target,reason); return await reply(m,"Участник исключён.")
            if cmd=="ban":
                days=int(rest[0]) if rest and rest[0].isdigit() else 0
                reason=" ".join(rest[1:] if rest and rest[0].isdigit() else rest) or "Без причины"
                try: await bot.ban_chat_member(chat,target,until_date=datetime.now(timezone.utc)+timedelta(days=days) if days else None)
                except Exception: return await reply(m,"Не удалось заблокировать участника. Проверь права бота.")
                p=ph(db); q(db,f"INSERT INTO cm_warns(chat_id,uid,by_uid,reason,created,active) VALUES({','.join([p]*6)})",(chat,target,uid,reason,now(db),2)); log_action(db,chat,uid,"ban",target,reason); return await reply(m,"Участник заблокирован.")
            if cmd=="unban":
                try: await bot.unban_chat_member(chat,target,only_if_banned=True)
                except Exception: return await reply(m,"Не удалось снять блокировку.")
                log_action(db,chat,uid,"unban",target); return await reply(m,"Блокировка снята.")
            if cmd=="getban":
                try:
                    member=await bot.get_chat_member(chat,target)
                    return await reply(m, "Участник не заблокирован." if member.status!="kicked" else "Участник заблокирован.")
                except Exception:
                    return await reply(m,"Не удалось получить статус блокировки. Возможно, участник не состоит в беседе.")
            if cmd=="getnick":
                x=one(db,f"SELECT nick FROM cm_nicks WHERE chat_id={ph(db)} AND uid={ph(db)}",(chat,target))
                return await reply(m,f"Ник: {x['nick']}" if x else "Ник не установлен.")
            if cmd=="setnick":
                if not rest: return await reply(m,"Формат: !setnick ID ник")
                nick=" ".join(rest); p=ph(db)
                if db.use_postgres: q(db,f"INSERT INTO cm_nicks(chat_id,uid,nick,by_uid,updated) VALUES({','.join([p]*5)}) ON CONFLICT(chat_id,uid) DO UPDATE SET nick=excluded.nick,by_uid=excluded.by_uid,updated=excluded.updated",(chat,target,nick,uid,now(db)))
                else: q(db,f"INSERT INTO cm_nicks(chat_id,uid,nick,by_uid,updated) VALUES({','.join([p]*5)}) ON CONFLICT(chat_id,uid) DO UPDATE SET nick=excluded.nick,by_uid=excluded.by_uid,updated=excluded.updated",(chat,target,nick,uid,now(db)))
                log_action(db,chat,uid,"nickname_set",target,nick); return await reply(m,"Ник сохранён в системе FENIX. Telegram-имя пользователя не меняется.")
            if cmd=="removenick":
                q(db,f"DELETE FROM cm_nicks WHERE chat_id={ph(db)} AND uid={ph(db)}",(chat,target)); log_action(db,chat,uid,"nickname_remove",target); return await reply(m,"Ник удалён.")
        if cmd=="stats":
            target,rest=parse_target(m,args)
            target=target or uid
            user=db.user(target) or {}
            warns=one(db,f"SELECT COUNT(*) AS n FROM cm_warns WHERE chat_id={ph(db)} AND uid={ph(db)} AND active=1",(chat,target))
            nick=one(db,f"SELECT nick FROM cm_nicks WHERE chat_id={ph(db)} AND uid={ph(db)}",(chat,target))
            role=get_role(db,chat,target)
            return await reply(m,f"<b>СТАТИСТИКА УЧАСТНИКА</b>\nID: <code>{target}</code>\nИгровой ник: {user.get('nick') or (nick or {}).get('nick') or 'не указан'}\nРоль в беседе: {role[1]} ({role[0]})\nПредупреждения: {(warns or {}).get('n',0)}")
        if cmd=="reg":
            target,rest=parse_target(m,args); target=target or uid
            user=db.user(target)
            if user and user.get("created"):
                return await reply(m,f"Дата регистрации в FENIX: <code>{user['created']}</code>\nДата регистрации Telegram через Bot API недоступна.")
            return await reply(m,"Дата регистрации Telegram не предоставляется Bot API. Пользователь ещё не найден в базе FENIX.")
        if cmd=="online":
            return await reply(m,"Telegram Bot API не предоставляет боту полный список участников и их статус онлайн. Используй !admins для просмотра руководства.")
        if cmd=="wipe":
            if not can(db,chat,uid,40) and uid not in owner_ids: return await reply(m,"⛔ Требуется уровень 40.")
            kind=(args[0].lower() if args else "")
            table={"warns":"cm_warns","предупреждения":"cm_warns","filters":"cm_filters","фильтры":"cm_filters","logs":"cm_logs","логи":"cm_logs","nicks":"cm_nicks","ники":"cm_nicks"}.get(kind)
            if not table: return await reply(m,"Формат: !wipe warns|filters|logs|nicks")
            q(db,f"DELETE FROM {table} WHERE chat_id={ph(db)}",(chat,)); log_action(db,chat,uid,"wipe",None,kind)
            return await reply(m,"Список очищен.")
        if cmd=="newrole":
            if not can(db,chat,uid,80) and uid not in owner_ids: return await reply(m,"⛔ Требуется уровень 80.")
            if len(args)<2 or not args[0].isdigit(): return await reply(m,"Формат: !newrole приоритет название")
            level=int(args[0]); title=" ".join(args[1:])
            if level not in (20,40,60,80): return await reply(m,"Допустимые приоритеты: 20, 40, 60, 80. Уровни базовой иерархии зарезервированы.")
            db.set_setting(f"cm_role_name:{chat}:{level}",title)
            return await reply(m,f"Название уровня {level} сохранено: {title}")
        if cmd=="deleterole":
            if not can(db,chat,uid,80) and uid not in owner_ids: return await reply(m,"⛔ Требуется уровень 80.")
            if not args or not args[0].isdigit(): return await reply(m,"Формат: !deleterole приоритет")
            level=int(args[0]); q(db,f"DELETE FROM cm_roles WHERE chat_id={ph(db)} AND level={ph(db)}",(chat,level))
            return await reply(m,"Роли указанного уровня удалены у участников.")
        if cmd in ("voice","mafia","emoji","enick"):
            return await reply(m,"Эта функция пока не активирована в Chat Manager. Голосовая генерация, полноценная игра «Мафия» и изменение Telegram-эмодзи статуса/ника требуют отдельных модулей и разрешений Telegram.")
        if cmd in ("filters","filteradd","filterdel","filteredit","addlink","whitelistlinks","silence","pin","unpin","logs","zov"):
            required=60 if cmd in ("filters","filteradd","filterdel","filteredit","addlink","whitelistlinks") else (80 if cmd in ("pin","unpin") else (20 if cmd in ("logs","zov") else 40))
            if not can(db,chat,uid,required) and uid not in owner_ids: return await reply(m,"⛔ Недостаточно прав.")
            p=ph(db)
            if cmd=="filteradd":
                if not argtext: return await reply(m,"Формат: !filteradd слово или фраза")
                try: q(db,f"INSERT INTO cm_filters(chat_id,phrase,created_by,created) VALUES({','.join([p]*4)})",(chat,argtext,uid,now(db)))
                except Exception: pass
                log_action(db,chat,uid,"filter_add",None,argtext); return await reply(m,"Фильтр добавлен.")
            if cmd=="filterdel":
                if not argtext: return await reply(m,"Формат: !filterdel слово")
                q(db,f"DELETE FROM cm_filters WHERE chat_id={p} AND lower(phrase)=lower({p})",(chat,argtext)); return await reply(m,"Фильтр удалён.")
            if cmd in ("filters","filteredit"):
                rr=rows(db,f"SELECT phrase FROM cm_filters WHERE chat_id={p} ORDER BY phrase",(chat,))
                return await reply(m,"<b>ФИЛЬТРЫ</b>\n"+("\n".join("• "+x["phrase"] for x in rr) if rr else "Фильтры не добавлены."))
            if cmd=="addlink":
                if not re.match(r"https?://",argtext): return await reply(m,"Укажи ссылку с https://")
                try: q(db,f"INSERT INTO cm_links(chat_id,url,created_by,created) VALUES({','.join([p]*4)})",(chat,argtext,uid,now(db)))
                except Exception: pass
                return await reply(m,"Ссылка добавлена в белый список.")
            if cmd=="whitelistlinks":
                rr=rows(db,f"SELECT url FROM cm_links WHERE chat_id={p}",(chat,))
                return await reply(m,"<b>РАЗРЕШЁННЫЕ ССЫЛКИ</b>\n"+("\n".join(x["url"] for x in rr) if rr else "Список пуст."))
            if cmd=="silence":
                s=chat_settings(db,chat); val=0 if s.get("silence") else 1
                q(db,f"UPDATE cm_settings SET silence={p},updated={p} WHERE chat_id={p}",(val,now(db),chat)); log_action(db,chat,uid,"silence",None,str(val))
                return await reply(m,"Режим тишины "+("включён" if val else "выключен")+".")
            if cmd=="pin":
                if not m.reply_to_message: return await reply(m,"Ответь командой !pin на сообщение.")
                try: await bot.pin_chat_message(chat,m.reply_to_message.message_id); return await reply(m,"Сообщение закреплено.")
                except Exception: return await reply(m,"Боту нужно право закреплять сообщения.")
            if cmd=="unpin":
                try: await bot.unpin_chat_message(chat); return await reply(m,"Закрепление снято.")
                except Exception: return await reply(m,"Не удалось открепить сообщение.")
            if cmd=="logs":
                rr=rows(db,f"SELECT action,target,details,created FROM cm_logs WHERE chat_id={p} ORDER BY id DESC LIMIT 15",(chat,))
                return await reply(m,"<b>ЖУРНАЛ ДЕЙСТВИЙ</b>\n"+("\n".join(f"{x['created']} · {x['action']} · {x['target'] or ''} · {x['details']}" for x in rr) if rr else "Записей пока нет."))
            if cmd=="zov":
                return await reply(m,"Упоминание всех участников Telegram API не позволяет надёжно получить полный список участников. Используй объявление в беседе с текстом команды.")
        if cmd=="report":
            if not argtext: return await reply(m,"Формат: !report текст обращения")
            admins=rows(db,f"SELECT uid FROM cm_roles WHERE chat_id={ph(db)} AND level>=40",(chat,))
            for a in admins:
                try: await bot.send_message(a["uid"],f"🚨 Репорт из {m.chat.title}\nОт: {m.from_user.full_name} ({uid})\n{argtext}")
                except Exception: pass
            return await reply(m,"Обращение передано руководству беседы.")
        if cmd=="try": return await reply(m,f"🎲 {m.from_user.full_name}, удача сегодня на твоей стороне!" if uid%2 else f"🎲 {m.from_user.full_name}, попробуй ещё раз!")
        if cmd in ("kiss","hug"):
            target,rest=parse_target(m,args)
            if not target and m.reply_to_message and m.reply_to_message.from_user: target=m.reply_to_message.from_user.id
            if not target: return await reply(m,"Ответь на сообщение участника или укажи его Telegram ID.")
            verb="поцеловал(а)" if cmd=="kiss" else "обнял(а)"
            return await reply(m,f"{m.from_user.full_name} {verb} {await target_name(chat,target)} 💛")
        if cmd in ("unity","unites","addunity","removeunity","editunity","deleteunity"):
            if not can(db,chat,uid,100) and uid not in owner_ids: return await reply(m,"⛔ Только владелец беседы.")
            p=ph(db)
            if cmd=="addunity":
                if not argtext: return await reply(m,"Формат: !addunity название объединения")
                name=argtext.strip()
                try:
                    if db.use_postgres: q(db,f"INSERT INTO cm_unities(name,owner_chat,created_by,created) VALUES({','.join([p]*4)}) ON CONFLICT(name) DO NOTHING",(name,chat,uid,now(db)))
                    else: q(db,f"INSERT OR IGNORE INTO cm_unities(name,owner_chat,created_by,created) VALUES({','.join([p]*4)})",(name,chat,uid,now(db)))
                except Exception: pass
                u=one(db,f"SELECT id FROM cm_unities WHERE name={p}",(name,))
                if u:
                    if db.use_postgres: q(db,f"INSERT INTO cm_unity_chats(chat_id,unity_id,added_by,created) VALUES({','.join([p]*4)}) ON CONFLICT(chat_id) DO UPDATE SET unity_id=excluded.unity_id",(chat,u["id"],uid,now(db)))
                    else: q(db,f"INSERT INTO cm_unity_chats(chat_id,unity_id,added_by,created) VALUES({','.join([p]*4)}) ON CONFLICT(chat_id) DO UPDATE SET unity_id=excluded.unity_id",(chat,u["id"],uid,now(db)))
                return await reply(m,"Беседа подключена к объединению.")
            if cmd=="removeunity":
                q(db,f"DELETE FROM cm_unity_chats WHERE chat_id={p}",(chat,)); return await reply(m,"Беседа отключена от объединения.")
            if cmd=="unites":
                rr=rows(db,"SELECT name,id FROM cm_unities ORDER BY name")
                return await reply(m,"<b>ОБЪЕДИНЕНИЯ</b>\n"+("\n".join(f"{x['name']} · #{x['id']}" for x in rr) if rr else "Объединений нет."))
            u=one(db,f"SELECT u.name,u.id FROM cm_unity_chats c JOIN cm_unities u ON u.id=c.unity_id WHERE c.chat_id={p}",(chat,))
            if cmd=="deleteunity" and args:
                q(db,f"DELETE FROM cm_unities WHERE name={p}",(" ".join(args),)); return await reply(m,"Объединение удалено.")
            if cmd=="editunity":
                if not u or not argtext: return await reply(m,"Формат: !editunity новое название")
                q(db,f"UPDATE cm_unities SET name={p} WHERE id={p}",(argtext.strip(),u["id"]))
                return await reply(m,"Название объединения изменено.")
            return await reply(m,f"Текущее объединение: {u['name']}" if u else "Эта беседа не подключена к объединению.")
    @router.callback_query(F.data=="chat_manager_admin")
    async def chat_manager_admin(c):
        if c.from_user.id not in owner_ids and not db.is_admin(c.from_user.id):
            return await c.answer("Нет доступа",show_alert=True)
        chats=rows(db,"SELECT chat_id,title,updated FROM cm_settings ORDER BY updated DESC LIMIT 50")
        body="<b>FENIX MANAGER</b>\n\n"
        if chats:
            body += "\n".join(f"• {x['title'] or 'Без названия'} — <code>{x['chat_id']}</code>" for x in chats)
        else:
            body += "Пока нет подключённых групп. Добавь FENIX в беседу и назначь администратором — после этого группа появится в панели автоматически."
        body += "\n\nКоманды: !settings · !setup · !welcome · !setrules · !roles · !admins · !logs"
        keyboard=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Обновить",callback_data="chat_manager_admin")],
            [InlineKeyboardButton(text="Назад",callback_data="owner")]
        ])
        # Owner panel may be a photo/media message, or a message without text.
        # Edit the correct field; if Telegram has nothing editable, send a new screen.
        try:
            if c.message.text is not None:
                await c.message.edit_text(body,parse_mode="HTML",reply_markup=keyboard)
            elif c.message.caption is not None:
                await c.message.edit_caption(caption=body,parse_mode="HTML",reply_markup=keyboard)
            else:
                await c.message.answer(body,parse_mode="HTML",reply_markup=keyboard,disable_web_page_preview=True)
        except Exception:
            log.exception("Failed to display Chat Manager admin screen")
            await c.message.answer(body,parse_mode="HTML",reply_markup=keyboard,disable_web_page_preview=True)
        await c.answer()
    @router.message(Command("chatmanager"))
    async def global_chat_manager(m: Message):
        if m.from_user.id not in owner_ids and not db.is_admin(m.from_user.id):
            return await m.answer("⛔ Доступ только владельцу FENIX.")
        chats=rows(db,"SELECT chat_id,title,updated FROM cm_settings ORDER BY updated DESC LIMIT 50")
        if not chats:
            return await m.answer("Пока нет подключённых групп. Добавь FENIX в беседу и назначь администратором — после этого группа появится в панели автоматически.")
        text="<b>FENIX · ПОДКЛЮЧЁННЫЕ БЕСЕДЫ</b>\n\n"+"\n".join(f"• {x['title'] or 'Без названия'} · <code>{x['chat_id']}</code>" for x in chats)
        await m.answer(text,parse_mode="HTML")
    @router.my_chat_member()
    async def bot_membership(update):
        chat=update.chat
        if chat.type not in ("group","supergroup"): return
        chat_settings(db,chat.id)
        p=ph(db)
        q(db,f"UPDATE cm_settings SET title={p},updated={p} WHERE chat_id={p}",(chat.title or "",now(db),chat.id))
        log.info("Chat Manager linked group: %s (%s)",chat.title,chat.id)
    def cmui_keyboard(chat_id):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Настройки беседы",callback_data=f"cmui:section:{chat_id}:settings")],
            [InlineKeyboardButton(text="🛡 Модерация",callback_data=f"cmui:section:{chat_id}:moderation")],
            [InlineKeyboardButton(text="👥 Роли и руководство",callback_data=f"cmui:section:{chat_id}:roles")],
            [InlineKeyboardButton(text="🎁 Telegram-подарки",callback_data="cmui:gifts")],
            [InlineKeyboardButton(text="📖 Список команд",callback_data="cmui:commands")],
            [InlineKeyboardButton(text="← К списку бесед",callback_data="cmui:home")]
        ])
    async def cmui_show(c, body, keyboard):
        try:
            if c.message.text is not None:
                await c.message.edit_text(body,parse_mode="HTML",reply_markup=keyboard,disable_web_page_preview=True)
            elif c.message.caption is not None:
                await c.message.edit_caption(caption=body,parse_mode="HTML",reply_markup=keyboard)
            else:
                await c.message.answer(body,parse_mode="HTML",reply_markup=keyboard,disable_web_page_preview=True)
        except Exception:
            await c.message.answer(body,parse_mode="HTML",reply_markup=keyboard,disable_web_page_preview=True)
    @router.callback_query(F.data.startswith("cmui:"))
    async def cmui_callback(c):
        if c.from_user.id not in owner_ids and not db.is_admin(c.from_user.id):
            return await c.answer("Нет доступа",show_alert=True)
        data=c.data.split(":")
        action=data[1] if len(data)>1 else ""
        if action=="connect":
            await cmui_show(c,"<b>ПОДКЛЮЧЕНИЕ БЕСЕДЫ</b>\n\nДобавь бота в группу и назначь администратором. После события добавления Telegram автоматически зарегистрирует беседу. Затем снова открой /chatmanager.",InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="← Назад",callback_data="cmui:home")]]))
        elif action=="home":
            chats=rows(db,"SELECT chat_id,title FROM cm_settings ORDER BY updated DESC LIMIT 50")
            if not chats:
                await cmui_show(c,"<b>FENIX · УПРАВЛЕНИЕ БЕСЕДАМИ</b>\n\nПока нет подключённых групп. Добавь бота в группу и выдай ему права администратора.",InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Как подключить",callback_data="cmui:connect")]]))
            else:
                kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=(x["title"] or "Беседа")[:32],callback_data=f"cmui:chat:{x['chat_id']}")] for x in chats]+[[InlineKeyboardButton(text="Обновить",callback_data="cmui:home")]])
                await cmui_show(c,"<b>FENIX MANAGER</b>\nВыбери беседу:",kb)
        elif action=="chat" and len(data)>2:
            chat_id=int(data[2]); s=chat_settings(db,chat_id)
            info=one(db,f"SELECT title FROM cm_settings WHERE chat_id={ph(db)}",(chat_id,)) or {}
            body=f"<b>{info.get('title') or 'Беседа'}</b>\n<code>{chat_id}</code>\n\nПриветствие: {'установлено' if s.get('welcome') else 'не задано'}\nПравила: {'установлены' if s.get('rules') else 'не заданы'}\nРежим тишины: {'включён' if s.get('silence') else 'выключен'}"
            await cmui_show(c,body,cmui_keyboard(chat_id))
        elif action=="section" and len(data)>3:
            chat_id=int(data[2]); section=data[3]; s=chat_settings(db,chat_id)
            back=cmui_keyboard(chat_id)
            if section=="settings":
                body=f"<b>⚙️ НАСТРОЙКИ</b>\nПриветствие: {'есть' if s.get('welcome') else 'нет'}\nПравила: {'есть' if s.get('rules') else 'нет'}\nТишина: {'включена' if s.get('silence') else 'выключена'}\nОграничение ссылок: {'включено' if s.get('invite_mode')=='on' else 'выключено'}"
                kb=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=("🔕 Выключить тишину" if s.get("silence") else "🔔 Включить тишину"),callback_data=f"cmui:toggle:{chat_id}:silence")],
                    [InlineKeyboardButton(text="Как изменить приветствие",callback_data=f"cmui:hint:{chat_id}:welcome")],
                    [InlineKeyboardButton(text="Как изменить правила",callback_data=f"cmui:hint:{chat_id}:rules")],
                    [InlineKeyboardButton(text="← Назад",callback_data=f"cmui:chat:{chat_id}")]
                ])
                await cmui_show(c,body,kb)
            elif section=="moderation":
                await cmui_show(c,"<b>🛡 МОДЕРАЦИЯ</b>\n\nДействия над участником выполняются в самой группе ответом на его сообщение: !mute 15m, !unmute, !warn причина, !ban причина, !kick.\n\nФильтры: !filteradd фраза и !filterdel фраза. Белый список ссылок: !addlink https://example.com.",back)
            elif section=="roles":
                rr=rows(db,f"SELECT uid,level,title FROM cm_roles WHERE chat_id={ph(db)} AND level>0 ORDER BY level DESC",(chat_id,))
                body="<b>👥 РОЛИ И РУКОВОДСТВО</b>\n"+("\n".join(f"• {x['title']} · <code>{x['uid']}</code> · {x['level']}" for x in rr) if rr else "Роли ещё не назначены.")
                await cmui_show(c,body,back)
            else:
                await cmui_show(c,"<b>FENIX MANAGER</b>\nИспользуй кнопки настроек и модерации. Полный справочник команд доступен отдельной статьёй.",back)
        elif action=="commands":
            article=(db.setting("fenix_commands_article_url","") or "").strip()
            kb=InlineKeyboardMarkup(inline_keyboard=([[InlineKeyboardButton(text="📖 Открыть справочник команд",url=article)]] if article else [])+[[InlineKeyboardButton(text="← Назад",callback_data="cmui:home")]])
            await cmui_show(c,"<b>FENIX MANAGER · КОМАНДЫ</b>\nПолный справочник команд проекта.",kb)
        elif action=="gifts":
            me=await bot.get_me()
            url=f"https://t.me/{me.username}?start=fenix_gifts"
            await cmui_show(c,"<b>🎁 TELEGRAM-ПОДАРКИ</b>\nНажми кнопку ниже, чтобы открыть магазин FENIX в личном чате. Там можно купить настоящий подарок Telegram или Premium за Stars.",InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 Открыть магазин подарков",url=url)],[InlineKeyboardButton(text="← Назад",callback_data="cmui:home")]]))
        elif action=="toggle" and len(data)>3:
            chat_id=int(data[2]); setting=data[3]
            if setting=="silence":
                s=chat_settings(db,chat_id); val=0 if s.get("silence") else 1; p=ph(db)
                q(db,f"UPDATE cm_settings SET silence={p},updated={p} WHERE chat_id={p}",(val,now(db),chat_id))
                log_action(db,chat_id,c.from_user.id,"silence_panel",None,str(val))
                await c.answer("Режим тишины обновлён")
                await cmui_show(c,f"<b>⚙️ НАСТРОЙКИ</b>\nРежим тишины теперь {'включён' if val else 'выключен'}.",InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="← К настройкам",callback_data=f"cmui:section:{chat_id}:settings")]]))
                return
        elif action=="hint" and len(data)>3:
            field=data[3]
            text_hint=("В группе отправь: !welcome текст приветствия" if field=="welcome" else "В группе отправь: !setrules текст правил")
            await cmui_show(c,"<b>ИЗМЕНЕНИЕ ТЕКСТА</b>\n\n"+text_hint,InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="← К настройкам",callback_data=f"cmui:section:{data[2]}:settings")]]))
        await c.answer()
    dp.include_router(router)
    log.info("FENIX Chat Manager router registered")
