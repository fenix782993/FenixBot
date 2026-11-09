import asyncio, logging, re
from datetime import datetime, timedelta, timezone
from html import escape
from aiogram import Router, F
from aiogram.filters import BaseFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

log=logging.getLogger("fenix.modules")
from fenix_display import user_label
def ph(db): return "%s" if db.use_postgres else "?"
class CursorResult:
    def __init__(self, row=None, rowcount=0, lastrowid=None):
        self._row=row
        self.rowcount=rowcount
        self.lastrowid=lastrowid
    def fetchone(self):
        return self._row

def run(db,sql,args=()):
    with db.con() as c:
        cur=c.execute(sql,args)
        row=cur.fetchone() if "RETURNING" in sql.upper() else None
        return CursorResult(dict(row) if row is not None else None,cur.rowcount,getattr(cur,"lastrowid",None))
def one(db,sql,args=()):
    with db.con() as c:
        x=c.execute(sql,args).fetchone()
        return dict(x) if x else None
def rows(db,sql,args=()):
    with db.con() as c: return [dict(x) for x in c.execute(sql,args).fetchall()]
def stamp(db): return db._now()
def init(db):
    with db.con() as c:
        if db.use_postgres:
            sql=[
            "CREATE TABLE IF NOT EXISTS cm_access(chat_id BIGINT,command TEXT,min_level INTEGER DEFAULT 0,enabled INTEGER DEFAULT 1,PRIMARY KEY(chat_id,command))",
            "CREATE TABLE IF NOT EXISTS cm_triggers(id BIGSERIAL PRIMARY KEY,chat_id BIGINT,phrase TEXT,response TEXT,created_by BIGINT,created TEXT,UNIQUE(chat_id,phrase))",
            "CREATE TABLE IF NOT EXISTS cm_reports(id BIGSERIAL PRIMARY KEY,chat_id BIGINT,reporter_uid BIGINT,target_uid BIGINT,body TEXT,status TEXT DEFAULT 'open',created TEXT)",
            "CREATE TABLE IF NOT EXISTS cm_notes(id BIGSERIAL PRIMARY KEY,chat_id BIGINT,uid BIGINT,author_uid BIGINT,body TEXT,created TEXT)",
            "CREATE TABLE IF NOT EXISTS cm_bookmarks(id BIGSERIAL PRIMARY KEY,chat_id BIGINT,uid BIGINT,message_id BIGINT,body TEXT,created TEXT,UNIQUE(chat_id,uid,message_id))",
            "CREATE TABLE IF NOT EXISTS cm_timers(id BIGSERIAL PRIMARY KEY,chat_id BIGINT,uid BIGINT,body TEXT,due_at TEXT,status TEXT DEFAULT 'pending',created TEXT)",
            "CREATE TABLE IF NOT EXISTS cm_votes(id BIGSERIAL PRIMARY KEY,chat_id BIGINT,creator BIGINT,question TEXT,status TEXT DEFAULT 'open',created TEXT)",
            "CREATE TABLE IF NOT EXISTS cm_vote_options(id BIGSERIAL PRIMARY KEY,vote_id BIGINT,label TEXT)",
            "CREATE TABLE IF NOT EXISTS cm_vote_ballots(vote_id BIGINT,uid BIGINT,option_id BIGINT,created TEXT,PRIMARY KEY(vote_id,uid))",
            "CREATE TABLE IF NOT EXISTS cm_message_events(id BIGSERIAL PRIMARY KEY,chat_id BIGINT,uid BIGINT,created TEXT)",
            "CREATE TABLE IF NOT EXISTS cm_antispam(chat_id BIGINT PRIMARY KEY,enabled INTEGER DEFAULT 1,threshold INTEGER DEFAULT 8,window_sec INTEGER DEFAULT 10,mute_sec INTEGER DEFAULT 30)"]
            for x in sql:c.execute(x)
        else:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS cm_access(chat_id INTEGER,command TEXT,min_level INTEGER DEFAULT 0,enabled INTEGER DEFAULT 1,PRIMARY KEY(chat_id,command));
            CREATE TABLE IF NOT EXISTS cm_triggers(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,phrase TEXT,response TEXT,created_by INTEGER,created TEXT,UNIQUE(chat_id,phrase));
            CREATE TABLE IF NOT EXISTS cm_reports(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,reporter_uid INTEGER,target_uid INTEGER,body TEXT,status TEXT DEFAULT 'open',created TEXT);
            CREATE TABLE IF NOT EXISTS cm_notes(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,uid INTEGER,author_uid INTEGER,body TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS cm_bookmarks(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,uid INTEGER,message_id INTEGER,body TEXT,created TEXT,UNIQUE(chat_id,uid,message_id));
            CREATE TABLE IF NOT EXISTS cm_timers(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,uid INTEGER,body TEXT,due_at TEXT,status TEXT DEFAULT 'pending',created TEXT);
            CREATE TABLE IF NOT EXISTS cm_votes(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,creator INTEGER,question TEXT,status TEXT DEFAULT 'open',created TEXT);
            CREATE TABLE IF NOT EXISTS cm_vote_options(id INTEGER PRIMARY KEY AUTOINCREMENT,vote_id INTEGER,label TEXT);
            CREATE TABLE IF NOT EXISTS cm_vote_ballots(vote_id INTEGER,uid INTEGER,option_id INTEGER,created TEXT,PRIMARY KEY(vote_id,uid));
            CREATE TABLE IF NOT EXISTS cm_message_events(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,uid INTEGER,created TEXT);
            CREATE TABLE IF NOT EXISTS cm_antispam(chat_id INTEGER PRIMARY KEY,enabled INTEGER DEFAULT 1,threshold INTEGER DEFAULT 8,window_sec INTEGER DEFAULT 10,mute_sec INTEGER DEFAULT 30);
            """)
def level(db,chat,uid):
    try:
        x=one(db,f"SELECT level FROM cm_roles WHERE chat_id={ph(db)} AND uid={ph(db)}",(chat,uid))
        return int(x["level"]) if x else 0
    except Exception:return 0
def register(dp,bot,db,owner_ids=()):
    init(db); router=Router(name="fenix_modules"); owners=set(owner_ids or ())
    commands="note|notes|bookmark|bookmarks|unbookmark|timer|timers|timerdel|vote|voteresult|voteclose|access|triggeradd|triggerdel|triggers|purge|del|report|antispam"
    async def ensure_creator(chat_id, user_id):
        try:
            member=await bot.get_chat_member(chat_id,user_id)
            if member.status=="creator":
                p=ph(db);stamp_value=stamp(db)
                run(db,f"INSERT INTO cm_roles(chat_id,uid,level,title,by_uid,updated) VALUES({','.join([p]*6)}) ON CONFLICT(chat_id,uid) DO UPDATE SET level=100,title='Владелец',updated=excluded.updated",(chat_id,user_id,100,"Владелец",user_id,stamp_value))
        except Exception:pass
    pattern=re.compile(r"(?i)^[!./](?:"+commands+r")(?:@[a-zA-Z0-9_]+)?(?=$|[^a-zA-Z0-9_])")
    @router.message(F.text.regexp(pattern))
    async def command(m):
        if m.chat.type=="private":return await m.answer("Эта команда работает в групповой беседе.")
        raw=m.text.strip()
        text=raw[1:]
        parts=text.split(maxsplit=1); cmd=parts[0].lower().split("@")[0]; arg=parts[1] if len(parts)>1 else ""; args=arg.split()
        chat,uid,p=m.chat.id,m.from_user.id,ph(db)
        await ensure_creator(chat,uid)
        lv=level(db,chat,uid); owner=uid in owners or db.is_admin(uid)
        ac=one(db,f"SELECT min_level,enabled FROM cm_access WHERE chat_id={p} AND command={p}",(chat,cmd))
        if ac and (not int(ac["enabled"]) or lv<int(ac["min_level"])):return await m.answer("⛔ Доступ к команде ограничен.")
        if cmd=="antispam":
            if lv<60 and not owner:return await m.answer("⛔ Требуется уровень 60.")
            value=args[0].lower() if args else "status"
            if value not in ("on","off","status"):return await m.answer("Формат: !antispam on|off|status")
            if value!="status":
                run(db,f"INSERT INTO cm_antispam(chat_id,enabled) VALUES({p},{p}) ON CONFLICT(chat_id) DO UPDATE SET enabled=excluded.enabled",(chat,1 if value=="on" else 0))
            cfg=one(db,f"SELECT enabled,threshold,window_sec,mute_sec FROM cm_antispam WHERE chat_id={p}",(chat,)) or {"enabled":1,"threshold":8,"window_sec":10,"mute_sec":30}
            return await m.answer(f"🛡 Антиспам: {'включён' if cfg['enabled'] else 'выключен'}. Порог: {cfg['threshold']} сообщений за {cfg['window_sec']} сек.; мут: {cfg['mute_sec']} сек.")
        if cmd=="access":
            if lv<80 and not owner:return await m.answer("⛔ Требуется уровень 80.")
            if len(args)<2:return await m.answer("Формат: !access команда уровень|off (0/20/40/60/80).")
            key,val=args[0].lower(),args[1].lower()
            if val=="off":run(db,f"INSERT INTO cm_access(chat_id,command,min_level,enabled) VALUES({p},{p},0,0) ON CONFLICT(chat_id,command) DO UPDATE SET enabled=0",(chat,key))
            else:
                try:n=int(val)
                except ValueError:n=-1
                if n not in (0,20,40,60,80):return await m.answer("Уровень должен быть 0, 20, 40, 60, 80 или off.")
                run(db,f"INSERT INTO cm_access(chat_id,command,min_level,enabled) VALUES({p},{p},{p},1) ON CONFLICT(chat_id,command) DO UPDATE SET min_level=excluded.min_level,enabled=1",(chat,key,n))
            return await m.answer("✅ Доступ сохранён.")
        if cmd=="triggeradd":
            if lv<60 and not owner:return await m.answer("⛔ Требуется уровень 60.")
            if "=>" not in arg:return await m.answer("Формат: !triggeradd фраза => ответ")
            phrase,response=[v.strip() for v in arg.split("=>",1)]
            if not phrase or not response:return await m.answer("Заполни фразу и ответ.")
            try:run(db,f"INSERT INTO cm_triggers(chat_id,phrase,response,created_by,created) VALUES({','.join([p]*5)})",(chat,phrase,response,uid,stamp(db)))
            except Exception:return await m.answer("Такая фраза уже есть.")
            return await m.answer("✅ Автоответ добавлен.")
        if cmd in ("triggerdel","triggers"):
            if lv<60 and not owner:return await m.answer("⛔ Требуется уровень 60.")
            if cmd=="triggerdel":
                run(db,f"DELETE FROM cm_triggers WHERE chat_id={p} AND lower(phrase)=lower({p})",(chat,arg));return await m.answer("Триггер удалён.")
            rr=rows(db,f"SELECT phrase,response FROM cm_triggers WHERE chat_id={p} ORDER BY id",(chat,))
            return await m.answer("<b>АВТООТВЕТЫ</b>\n"+("\n".join("• "+escape(x["phrase"])+" → "+escape(x["response"]) for x in rr) if rr else "Список пуст."),parse_mode="HTML")
        if cmd=="note":
            if not args:return await m.answer("!note add текст | !note list | !note del ID")
            sub=args[0].lower();target=m.reply_to_message.from_user.id if m.reply_to_message and m.reply_to_message.from_user else uid
            if sub=="add":
                body=arg.split(maxsplit=1)[1] if len(args)>1 else ""
                if not body:return await m.answer("Укажи текст заметки.")
                run(db,f"INSERT INTO cm_notes(chat_id,uid,author_uid,body,created) VALUES({','.join([p]*5)})",(chat,target,uid,body[:2000],stamp(db)))
                return await m.answer(f"Заметка сохранена для {await user_label(bot,chat,target)}.",parse_mode="HTML")
            if sub=="list":
                rr=rows(db,f"SELECT id,body FROM cm_notes WHERE chat_id={p} AND uid={p} ORDER BY id DESC LIMIT 20",(chat,target))
                return await m.answer("<b>ЗАМЕТКИ</b>\n"+("\n".join(f"#{x['id']} · {escape(x['body'])}" for x in rr) if rr else "Нет заметок."),parse_mode="HTML")
            if sub=="del" and len(args)>1 and args[1].isdigit():
                x=one(db,f"SELECT author_uid FROM cm_notes WHERE id={p} AND chat_id={p}",(int(args[1]),chat))
                if x and (int(x["author_uid"])==uid or lv>=60 or owner):
                    run(db,f"DELETE FROM cm_notes WHERE id={p} AND chat_id={p}",(int(args[1]),chat));return await m.answer("Заметка удалена.")
            return await m.answer("Не удалось выполнить действие.")
        if cmd=="notes":
            rr=rows(db,f"SELECT id,body FROM cm_notes WHERE chat_id={p} AND uid={p} ORDER BY id DESC LIMIT 20",(chat,uid))
            return await m.answer("<b>ТВОИ ЗАМЕТКИ</b>\n"+("\n".join(f"#{x['id']} · {escape(x['body'])}" for x in rr) if rr else "Заметок нет."),parse_mode="HTML")
        if cmd=="bookmark":
            if not m.reply_to_message:return await m.answer("Ответь !bookmark на нужное сообщение.")
            body=(m.reply_to_message.text or m.reply_to_message.caption or "")[:1200]
            try:run(db,f"INSERT INTO cm_bookmarks(chat_id,uid,message_id,body,created) VALUES({','.join([p]*5)})",(chat,uid,m.reply_to_message.message_id,body,stamp(db)))
            except Exception:pass
            return await m.answer("🔖 Добавлено в закладки.")
        if cmd=="bookmarks":
            rr=rows(db,f"SELECT id,message_id,body FROM cm_bookmarks WHERE chat_id={p} AND uid={p} ORDER BY id DESC LIMIT 20",(chat,uid))
            return await m.answer("<b>ЗАКЛАДКИ</b>\n"+("\n".join(f"#{x['id']} · msg {x['message_id']} · {escape(x['body'][:100])}" for x in rr) if rr else "Закладок нет."),parse_mode="HTML")
        if cmd=="unbookmark":
            if not args or not args[0].isdigit():return await m.answer("Формат: !unbookmark ID")
            run(db,f"DELETE FROM cm_bookmarks WHERE id={p} AND chat_id={p} AND uid={p}",(int(args[0]),chat,uid));return await m.answer("Закладка удалена.")
        if cmd=="timer":
            if len(args)<2 or not re.fullmatch(r"[0-9]+(s|m|h|d)?",args[0].lower()):return await m.answer("Формат: !timer 10m напоминание")
            mat=re.fullmatch(r"([0-9]+)(s|m|h|d)?",args[0].lower()); secs=int(mat.group(1))*{"s":1,"m":60,"h":3600,"d":86400}[mat.group(2) or "m"]
            if not 10<=secs<=2592000:return await m.answer("Срок: от 10 секунд до 30 дней.")
            due=(datetime.now(timezone.utc)+timedelta(seconds=secs)).isoformat();body=arg.split(maxsplit=1)[1]
            run(db,f"INSERT INTO cm_timers(chat_id,uid,body,due_at,status,created) VALUES({','.join([p]*6)})",(chat,uid,body[:1000],due,"pending",stamp(db)))
            return await m.answer("⏰ Напоминание сохранено.")
        if cmd=="timers":
            rr=rows(db,f"SELECT id,body,due_at FROM cm_timers WHERE chat_id={p} AND uid={p} AND status='pending' ORDER BY due_at LIMIT 20",(chat,uid))
            return await m.answer("<b>МОИ НАПОМИНАНИЯ</b>\n"+("\n".join(f"#{x['id']} · {escape(x['body'])} · {x['due_at']}" for x in rr) if rr else "Активных напоминаний нет."),parse_mode="HTML")
        if cmd=="timerdel":
            if not args or not args[0].isdigit():return await m.answer("Формат: !timerdel ID")
            if lv<40 and not owner:
                run(db,f"DELETE FROM cm_timers WHERE id={p} AND chat_id={p} AND uid={p} AND status='pending'",(int(args[0]),chat,uid))
            else:
                run(db,f"DELETE FROM cm_timers WHERE id={p} AND chat_id={p} AND status='pending'",(int(args[0]),chat))
            return await m.answer("Напоминание отменено, если оно было активным.")
        if cmd=="vote":
            vals=[x.strip() for x in arg.split("|") if x.strip()]
            if len(vals)<3 or len(vals)>7:return await m.answer("Формат: !vote Вопрос | Вариант 1 | Вариант 2 (до 6 вариантов)")
            if db.use_postgres:
                cur=run(db,f"INSERT INTO cm_votes(chat_id,creator,question,status,created) VALUES({','.join([p]*5)}) RETURNING id",(chat,uid,vals[0],"open",stamp(db)));vid=int(cur.fetchone()["id"])
            else:
                cur=run(db,f"INSERT INTO cm_votes(chat_id,creator,question,status,created) VALUES({','.join([p]*5)})",(chat,uid,vals[0],"open",stamp(db)));vid=int(cur.lastrowid)
            kb=[]
            for label in vals[1:]:
                if db.use_postgres:
                    cur=run(db,f"INSERT INTO cm_vote_options(vote_id,label) VALUES({p},{p}) RETURNING id",(vid,label));oid=int(cur.fetchone()["id"])
                else:
                    cur=run(db,f"INSERT INTO cm_vote_options(vote_id,label) VALUES({p},{p})",(vid,label));oid=int(cur.lastrowid)
                kb.append([InlineKeyboardButton(text=label[:50],callback_data=f"fenixvote:{vid}:{oid}")])
            return await m.answer("<b>🗳 "+escape(vals[0])+"</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        if cmd=="voteclose":
            if not args or not args[0].isdigit():return await m.answer("Формат: !voteclose ID")
            vote=one(db,f"SELECT creator FROM cm_votes WHERE id={p} AND chat_id={p}",(int(args[0]),chat))
            if not vote:return await m.answer("Голосование не найдено.")
            if int(vote["creator"])!=uid and lv<40 and not owner:return await m.answer("Закрыть голосование может автор или модератор.")
            run(db,f"UPDATE cm_votes SET status='closed' WHERE id={p}",(int(args[0]),))
            return await m.answer("Голосование закрыто.")
        if cmd=="voteresult":
            if not args or not args[0].isdigit():return await m.answer("Формат: !voteresult ID")
            vid=int(args[0]);vote=one(db,f"SELECT question,status FROM cm_votes WHERE id={p} AND chat_id={p}",(vid,chat))
            if not vote:return await m.answer("Голосование не найдено.")
            result=rows(db,f"SELECT o.label,COUNT(b.uid) AS total FROM cm_vote_options o LEFT JOIN cm_vote_ballots b ON b.option_id=o.id WHERE o.vote_id={p} GROUP BY o.id,o.label ORDER BY total DESC,o.id",(vid,))
            total=sum(int(x["total"]) for x in result)
            body="<b>"+escape(vote["question"])+"</b>\nСтатус: "+escape(vote["status"])+" · голосов: "+str(total)+"\n"+"\n".join(f"{escape(x['label'])}: {x['total']} ({round(int(x['total'])*100/total) if total else 0}%)" for x in result)
            return await m.answer(body,parse_mode="HTML")
        if cmd=="del":
            if not m.reply_to_message:return await m.answer("Ответь !del на сообщение.")
            try:await bot.delete_message(chat,m.reply_to_message.message_id);return await m.answer("Удалено.")
            except Exception:return await m.answer("Не удалось удалить. Проверь права бота.")
        if cmd=="purge":
            if lv<40 and not owner:return await m.answer("⛔ Требуется уровень 40.")
            if not args or not args[0].isdigit():return await m.answer("Формат: !purge количество (до 100)")
            deleted=0
            for mid in range(max(1,m.message_id-min(100,int(args[0]))),m.message_id):
                try:await bot.delete_message(chat,mid);deleted+=1
                except Exception:pass
            try:await m.delete()
            except Exception:pass
            return await bot.send_message(chat,f"🧹 Удалено: {deleted}")
        if cmd=="report":
            if not arg:return await m.answer("Формат: !report текст")
            target=m.reply_to_message.from_user.id if m.reply_to_message and m.reply_to_message.from_user else None
            if db.use_postgres:
                cur=run(db,f"INSERT INTO cm_reports(chat_id,reporter_uid,target_uid,body,status,created) VALUES({','.join([p]*6)}) RETURNING id",(chat,uid,target,arg[:2000],"open",stamp(db)));rid=int(cur.fetchone()["id"])
            else:
                cur=run(db,f"INSERT INTO cm_reports(chat_id,reporter_uid,target_uid,body,status,created) VALUES({','.join([p]*6)})",(chat,uid,target,arg[:2000],"open",stamp(db)));rid=int(cur.lastrowid)
            admins=rows(db,f"SELECT uid FROM cm_roles WHERE chat_id={p} AND level>=40",(chat,))
            kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Закрыть репорт #{rid}",callback_data=f"fenixreport:{rid}")]])
            for a in admins:
                try:await bot.send_message(a["uid"],f"🚨 Репорт #{rid} из {escape(m.chat.title or 'беседы')}\n{escape(arg)}",parse_mode="HTML",reply_markup=kb)
                except Exception:pass
            return await m.answer(f"Репорт #{rid} передан руководству.")

    class SpamFilter(BaseFilter):
        async def __call__(self,m):
            if not m.text or m.chat.type=="private" or not m.from_user or m.from_user.is_bot:return False
            if m.text.startswith(("!","/", ".")):return False
            if level(db,m.chat.id,m.from_user.id)>=40:return False
            p=ph(db);cfg=one(db,f"SELECT enabled,threshold,window_sec,mute_sec FROM cm_antispam WHERE chat_id={p}",(m.chat.id,)) or {"enabled":1,"threshold":8,"window_sec":10,"mute_sec":30}
            if not int(cfg["enabled"]):return False
            cutoff=(datetime.now(timezone.utc)-timedelta(seconds=int(cfg["window_sec"]))).isoformat()
            run(db,f"INSERT INTO cm_message_events(chat_id,uid,created) VALUES({p},{p},{p})",(m.chat.id,m.from_user.id,stamp(db)))
            count=one(db,f"SELECT COUNT(*) AS n FROM cm_message_events WHERE chat_id={p} AND uid={p} AND created>={p}",(m.chat.id,m.from_user.id,cutoff))
            if int((count or {}).get("n",0))>=int(cfg["threshold"]):return {"spam_mute":int(cfg["mute_sec"])}
            return False
    @router.message(F.text,SpamFilter())
    async def spam_action(m,spam_mute):
        try:await m.delete()
        except Exception:pass
        try:
            from aiogram.types import ChatPermissions
            await bot.restrict_chat_member(m.chat.id,m.from_user.id,ChatPermissions(can_send_messages=False),until_date=datetime.now(timezone.utc)+timedelta(seconds=spam_mute))
            await bot.send_message(m.chat.id,f"🛡 Антиспам: участник ограничен на {spam_mute} сек. за флуд.")
        except Exception:log.exception("Anti-spam restriction failed")
    class TriggerFilter(BaseFilter):
        async def __call__(self,m):
            if not m.text or m.chat.type=="private" or m.text.startswith(("!","/",".")):return False
            for x in rows(db,f"SELECT phrase,response FROM cm_triggers WHERE chat_id={ph(db)}",(m.chat.id,)):
                if x["phrase"].casefold() in m.text.casefold():return {"answer_text":x["response"]}
            return False
    @router.message(F.text,TriggerFilter())
    async def trigger(m,answer_text):
        await m.reply(answer_text)

    @router.callback_query(F.data.startswith("fenixvote:"))
    async def vote(c):
        try:
            _,v,o=c.data.split(":");v=int(v);o=int(o);p=ph(db)
            x=one(db,f"SELECT status FROM cm_votes WHERE id={p}",(v,));y=one(db,f"SELECT id FROM cm_vote_options WHERE id={p} AND vote_id={p}",(o,v))
            if not x or x["status"]!="open" or not y:return await c.answer("Голосование закрыто.",show_alert=True)
            run(db,f"INSERT INTO cm_vote_ballots(vote_id,uid,option_id,created) VALUES({p},{p},{p},{p}) ON CONFLICT(vote_id,uid) DO UPDATE SET option_id=excluded.option_id,created=excluded.created",(v,c.from_user.id,o,stamp(db)))
            await c.answer("Голос учтён.")
        except Exception:log.exception("vote callback failed");await c.answer("Ошибка.",show_alert=True)
    @router.callback_query(F.data.startswith("fenixreport:"))
    async def report(c):
        try:
            rid=int(c.data.split(":")[-1]);p=ph(db);x=one(db,f"SELECT chat_id FROM cm_reports WHERE id={p}",(rid,))
            if not x:return await c.answer("Не найден.",show_alert=True)
            if level(db,x["chat_id"],c.from_user.id)<40 and c.from_user.id not in owners and not db.is_admin(c.from_user.id):return await c.answer("Нет доступа.",show_alert=True)
            run(db,f"UPDATE cm_reports SET status='closed' WHERE id={p}",(rid,));await c.message.edit_reply_markup(reply_markup=None);await c.answer("Закрыто.")
        except Exception:log.exception("report callback failed");await c.answer("Ошибка.",show_alert=True)

    async def timers():
        while True:
            try:
                p=ph(db);due=rows(db,f"SELECT id,chat_id,body FROM cm_timers WHERE status='pending' AND due_at<={p} ORDER BY due_at LIMIT 20",(stamp(db),))
                for x in due:
                    cur=run(db,f"UPDATE cm_timers SET status='sent' WHERE id={p} AND status='pending'",(x["id"],))
                    if getattr(cur,"rowcount",0)==1:
                        try:await bot.send_message(x["chat_id"],"⏰ Напоминание: "+escape(x["body"]),parse_mode="HTML")
                        except Exception:log.exception("timer delivery failed")
            except Exception:log.exception("timer loop failed")
            try:
                cutoff=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
                run(db,f"DELETE FROM cm_message_events WHERE created<{p}",(cutoff,))
            except Exception:pass
            await asyncio.sleep(10)
    asyncio.create_task(timers())
    dp.include_router(router)
    log.info("FENIX Manager automation modules registered")
