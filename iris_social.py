import asyncio, logging, random, re
from datetime import datetime, timedelta, timezone
from html import escape
from aiogram import Router, F
from aiogram.filters import BaseFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

log=logging.getLogger("fenix.iris_social")
def ph(db):return "%s" if db.use_postgres else "?"
def rows(db,sql,args=()):
    with db.con() as c:return [dict(x) for x in c.execute(sql,args).fetchall()]
def one(db,sql,args=()):
    with db.con() as c:
        x=c.execute(sql,args).fetchone()
        return dict(x) if x else None
def execq(db,sql,args=()):
    with db.con() as c:
        cur=c.execute(sql,args)
        row=cur.fetchone() if "RETURNING" in sql.upper() else None
        return (dict(row) if row else None,getattr(cur,"lastrowid",None))
def init(db):
    with db.con() as c:
        if db.use_postgres:
            sql=[
            "CREATE TABLE IF NOT EXISTS cm_reputation(chat_id BIGINT,uid BIGINT,score INTEGER DEFAULT 0,updated TEXT,PRIMARY KEY(chat_id,uid))",
            "CREATE TABLE IF NOT EXISTS cm_rep_votes(chat_id BIGINT,giver BIGINT,target BIGINT,day TEXT,PRIMARY KEY(chat_id,giver,target,day))",
            "CREATE TABLE IF NOT EXISTS cm_giveaways(id BIGSERIAL PRIMARY KEY,chat_id BIGINT,creator BIGINT,prize TEXT,draw_at TEXT,status TEXT DEFAULT 'open',winner BIGINT,created TEXT)",
            "CREATE TABLE IF NOT EXISTS cm_giveaway_entries(giveaway_id BIGINT,uid BIGINT,created TEXT,PRIMARY KEY(giveaway_id,uid))"]
            for x in sql:c.execute(x)
        else:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS cm_reputation(chat_id INTEGER,uid INTEGER,score INTEGER DEFAULT 0,updated TEXT,PRIMARY KEY(chat_id,uid));
            CREATE TABLE IF NOT EXISTS cm_rep_votes(chat_id INTEGER,giver INTEGER,target INTEGER,day TEXT,PRIMARY KEY(chat_id,giver,target,day));
            CREATE TABLE IF NOT EXISTS cm_giveaways(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,creator INTEGER,prize TEXT,draw_at TEXT,status TEXT DEFAULT 'open',winner INTEGER,created TEXT);
            CREATE TABLE IF NOT EXISTS cm_giveaway_entries(giveaway_id INTEGER,uid INTEGER,created TEXT,PRIMARY KEY(giveaway_id,uid));
            """)
def level(db,chat,uid):
    x=one(db,f"SELECT level FROM cm_roles WHERE chat_id={ph(db)} AND uid={ph(db)}",(chat,uid))
    return int(x["level"]) if x else 0
def register(dp,bot,db,owners=()):
    init(db);router=Router(name="fenix_iris_social");owners=set(owners or ())
    async def ensure_creator(chat_id,user_id):
        try:
            member=await bot.get_chat_member(chat_id,user_id)
            if member.status=="creator":
                p=ph(db)
                execq(db,f"INSERT INTO cm_roles(chat_id,uid,level,title,by_uid,updated) VALUES({','.join([p]*6)}) ON CONFLICT(chat_id,uid) DO UPDATE SET level=100,title='Владелец',updated=excluded.updated",(chat_id,user_id,100,"Владелец",user_id,db._now()))
        except Exception:pass
    rx=re.compile(r"(?i)^[!./](?:dice|кости|rep|reputation|топреп|giveaway|розыгрыш|gstop)\b")
    @router.message(F.text.regexp(rx))
    async def social(m):
        if m.chat.type=="private":return
        raw=m.text.strip();parts=raw[1:].split(maxsplit=1);cmd=parts[0].lower();arg=parts[1] if len(parts)>1 else "";args=arg.split()
        chat,uid,p=m.chat.id,m.from_user.id,ph(db)
        await ensure_creator(chat,uid)
        lv=level(db,chat,uid);owner=uid in owners or db.is_admin(uid)
        if cmd in ("dice","кости"):
            emoji=args[0] if args and args[0] in ("🎲","🎯","🏀","⚽","🎳","🎰") else "🎲"
            await bot.send_dice(chat,emoji=emoji);return
        if cmd in ("rep","reputation"):
            target=m.reply_to_message.from_user.id if m.reply_to_message and m.reply_to_message.from_user else (int(args[0]) if args and args[0].isdigit() else None)
            if not target:return await m.answer("Ответь !rep на сообщение или укажи Telegram ID.")
            if target==uid:return await m.answer("Нельзя повышать собственную репутацию.")
            day=datetime.now(timezone.utc).date().isoformat()
            try:execq(db,f"INSERT INTO cm_rep_votes(chat_id,giver,target,day) VALUES({','.join([p]*4)})",(chat,uid,target,day))
            except Exception:return await m.answer("Ты уже оценивал этого участника сегодня.")
            if db.use_postgres:execq(db,f"INSERT INTO cm_reputation(chat_id,uid,score,updated) VALUES({p},{p},1,{p}) ON CONFLICT(chat_id,uid) DO UPDATE SET score=cm_reputation.score+1,updated=excluded.updated",(chat,target,db._now()))
            else:execq(db,f"INSERT INTO cm_reputation(chat_id,uid,score,updated) VALUES({p},{p},1,{p}) ON CONFLICT(chat_id,uid) DO UPDATE SET score=cm_reputation.score+1,updated=excluded.updated",(chat,target,db._now()))
            x=one(db,f"SELECT score FROM cm_reputation WHERE chat_id={p} AND uid={p}",(chat,target))
            return await m.answer(f"⭐ Репутация <code>{target}</code>: {x['score']}",parse_mode="HTML")
        if cmd=="топреп":
            rr=rows(db,f"SELECT uid,score FROM cm_reputation WHERE chat_id={p} ORDER BY score DESC LIMIT 10",(chat,))
            return await m.answer("<b>⭐ ТОП РЕПУТАЦИИ</b>\n"+("\n".join(f"{i+1}. <code>{x['uid']}</code> — {x['score']}" for i,x in enumerate(rr)) if rr else "Пока нет оценок."),parse_mode="HTML")
        if cmd in ("giveaway","розыгрыш"):
            if lv<40 and not owner:return await m.answer("⛔ Создавать розыгрыши может модератор (уровень 40) и выше.")
            mat=re.match(r"^(\d+)(m|h|d)?\s+(.+)$",arg,re.I)
            if not mat:return await m.answer("Формат: !giveaway 1h Приз (от 1 минуты до 7 дней).")
            amount=int(mat.group(1));unit=(mat.group(2) or "m").lower();seconds=amount*{"m":60,"h":3600,"d":86400}[unit]
            if not 60<=seconds<=604800:return await m.answer("Срок розыгрыша — от 1 минуты до 7 дней.")
            due=(datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat();prize=mat.group(3)[:180]
            if db.use_postgres:
                x,_=execq(db,f"INSERT INTO cm_giveaways(chat_id,creator,prize,draw_at,status,created) VALUES({','.join([p]*6)}) RETURNING id",(chat,uid,prize,due,"open",db._now()));gid=int(x["id"])
            else:
                _,last=execq(db,f"INSERT INTO cm_giveaways(chat_id,creator,prize,draw_at,status,created) VALUES({','.join([p]*6)})",(chat,uid,prize,due,"open",db._now()));gid=int(last)
            kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 Участвовать",callback_data=f"fenixgive:{gid}")]])
            return await m.answer(f"<b>🎉 РОЗЫГРЫШ #{gid}</b>\nПриз: {escape(prize)}\nСрок: {amount}{unit}",parse_mode="HTML",reply_markup=kb)
        if cmd=="gstop":
            if lv<40 and not owner:return await m.answer("⛔ Требуется уровень 40.")
            if not args or not args[0].isdigit():return await m.answer("Формат: !gstop ID")
            execq(db,f"UPDATE cm_giveaways SET status='cancelled' WHERE id={p} AND chat_id={p} AND status='open'",(int(args[0]),chat))
            return await m.answer("Розыгрыш отменён.")
    @router.callback_query(F.data.startswith("fenixgive:"))
    async def enter(c):
        try:
            gid=int(c.data.split(":")[-1]);p=ph(db);g=one(db,f"SELECT status,draw_at FROM cm_giveaways WHERE id={p}",(gid,))
            if not g or g["status"]!="open" or g["draw_at"]<=db._now():return await c.answer("Розыгрыш завершён.",show_alert=True)
            execq(db,f"INSERT INTO cm_giveaway_entries(giveaway_id,uid,created) VALUES({p},{p},{p}) ON CONFLICT(giveaway_id,uid) DO NOTHING",(gid,c.from_user.id,db._now()))
            await c.answer("Ты участвуешь! 🎉")
        except Exception:log.exception("giveaway join failed");await c.answer("Ошибка.",show_alert=True)
    async def worker():
        import asyncio
        while True:
            try:
                p=ph(db);games=rows(db,f"SELECT id,chat_id,prize FROM cm_giveaways WHERE status='open' AND draw_at<={p} ORDER BY draw_at LIMIT 10",(db._now(),))
                for g in games:
                    with db.con() as conn:
                        claimed=conn.execute(f"UPDATE cm_giveaways SET status='drawing' WHERE id={p} AND status='open'",(g["id"],))
                        changed=claimed.rowcount
                    if changed!=1:continue
                    entrants=rows(db,f"SELECT uid FROM cm_giveaway_entries WHERE giveaway_id={p}",(g["id"],))
                    if entrants:
                        winner=random.choice(entrants)["uid"]
                        execq(db,f"UPDATE cm_giveaways SET status='finished',winner={p} WHERE id={p}",(winner,g["id"]))
                        await bot.send_message(g["chat_id"],f"🏆 Розыгрыш #{g['id']} завершён!\nПриз: {escape(g['prize'])}\nПобедитель: <code>{winner}</code>",parse_mode="HTML")
                    else:
                        execq(db,f"UPDATE cm_giveaways SET status='finished' WHERE id={p}",(g["id"],))
                        await bot.send_message(g["chat_id"],f"Розыгрыш #{g['id']} завершён без участников.")
            except Exception:log.exception("giveaway worker failed")
            await asyncio.sleep(15)
    asyncio.create_task(worker());dp.include_router(router);log.info("FENIX social modules registered")
