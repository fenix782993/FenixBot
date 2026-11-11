from aiogram import F
from aiogram.types import InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
import json

class ArenaStates(StatesGroup):
    custom_stake = State()

STAKES=(50,100,150,200)
def register_arena(dp, bot, db, markup, subscribed, channel_url):
    def game_name(code): return "Камень, ножницы, бумага" if code=="rps" else "Крестики-нолики"
    async def show_rps(rid):
        r=db.arena_room(rid)
        if not r or r["status"]!="playing": return
        score=json.loads(r["board"] or '{"wins":[0,0],"round":1}')
        kb=markup([[InlineKeyboardButton(text="🪨 Камень",callback_data=f"rps:{rid}:rock"),InlineKeyboardButton(text="✂️ Ножницы",callback_data=f"rps:{rid}:scissors"),InlineKeyboardButton(text="📄 Бумага",callback_data=f"rps:{rid}:paper")]])
        for uid in (r["host"],r["opponent"]):
            own=r["p1_choice"] if uid==r["host"] else r["p2_choice"]
            await bot.send_message(uid,f"✊ <b>КНБ · матч #{rid}</b>\nРаунд {score['round']} · Счёт {score['wins'][0]}:{score['wins'][1]}\n"+("Ход принят. Ждём соперника." if own else "Выбери ход:"),parse_mode="HTML",reply_markup=None if own else kb)
    async def show_ttt(rid):
        r=db.arena_room(rid)
        if not r or r["status"]!="playing": return
        board=json.loads(r["board"] or '[null,null,null,null,null,null,null,null,null]')
        rows=[[InlineKeyboardButton(text=board[y*3+x] or "·",callback_data=f"ttt:{rid}:{y*3+x}") for x in range(3)] for y in range(3)]
        for uid in (r["host"],r["opponent"]):
            await bot.send_message(uid,f"❌ <b>Крестики-нолики · матч #{rid}</b>\nХод: {'ты' if uid==r['turn'] else 'соперник'}",parse_mode="HTML",reply_markup=markup(rows))
    async def create_room(target,game,stake,uid):
        rid=db.arena_room_create(game,uid,stake)
        if not rid: return await target.answer("Недостаточно тестовых звёзд. Стартовый баланс — 1000 ⭐.")
        await target.answer(f"✅ Матч #{rid} создан. Ставка ⭐ {stake} заблокирована до завершения.",reply_markup=markup([[InlineKeyboardButton(text="🎮 Открыть лобби",callback_data="arena_lobby")]]))
    @dp.message(F.text == "/arena")
    async def arena_command(m):
        if not await subscribed(m.from_user.id):
            return await m.answer("🔒 Для входа подпишись на канал.",reply_markup=markup([[InlineKeyboardButton(text="📢 Подписаться",url=channel_url)],[InlineKeyboardButton(text="✅ Проверить подписку",callback_data="check_subscription")]]))
        bal=db.arena_wallet(m.from_user.id)
        await m.answer(f"🔥 <b>FENIX ARENA</b>\n⭐ Баланс: {bal:g} тестовых звёзд\nРегистрация игрового аккаунта не нужна. Вывод и обмен на деньги отключены.",parse_mode="HTML",reply_markup=markup([[InlineKeyboardButton(text="🎮 Открыть лобби",callback_data="arena_lobby")]]))
    @dp.callback_query(F.data=="arena_wallet")
    async def wallet(c): await c.answer(f"Тестовый баланс: {db.arena_wallet(c.from_user.id):g} ⭐",show_alert=True)
    @dp.callback_query(F.data=="arena_lobby")
    async def lobby(c):
        if not await subscribed(c.from_user.id): return await c.answer("Сначала подпишись на канал.",show_alert=True)
        rooms=db.arena_waiting(12); rows=[]
        for r in rooms: rows.append([InlineKeyboardButton(text=f"#{r['id']} • {game_name(r['game'])} • {float(r['stake']):g} ⭐",callback_data=f"arena_join:{r['id']}")])
        rows += [[InlineKeyboardButton(text="✊ Создать КНБ",callback_data="arena_create:rps"),InlineKeyboardButton(text="❌ Создать крестики-нолики",callback_data="arena_create:ttt")],[InlineKeyboardButton(text="⭐ Мой баланс",callback_data="arena_wallet")]]
        await c.message.edit_text("🎮 <b>FENIX ARENA — ЛОББИ</b>\nВыбери открытый матч или создай свой."+("\nОткрытых матчей пока нет." if not rooms else ""),parse_mode="HTML",reply_markup=markup(rows)); await c.answer()
    @dp.callback_query(F.data.startswith("arena_create:"))
    async def choose_game(c):
        game=c.data.split(":",1)[1]
        if game not in ("rps","ttt"): return await c.answer("Неизвестная игра",show_alert=True)
        rows=[[InlineKeyboardButton(text=f"⭐ {v}",callback_data=f"arena_stake:{game}:{v}") for v in STAKES[:2]],[InlineKeyboardButton(text=f"⭐ {v}",callback_data=f"arena_stake:{game}:{v}") for v in STAKES[2:]],[InlineKeyboardButton(text="✍️ Другая сумма",callback_data=f"arena_custom:{game}")],[InlineKeyboardButton(text="⬅️ Лобби",callback_data="arena_lobby")]]
        await c.message.edit_text(f"🎮 <b>{game_name(game)}</b>\nВыбери ставку за одного игрока:",parse_mode="HTML",reply_markup=markup(rows)); await c.answer()
    @dp.callback_query(F.data.startswith("arena_custom:"))
    async def custom(c,state):
        game=c.data.split(":",1)[1]
        if game not in ("rps","ttt"): return await c.answer("Ошибка игры",show_alert=True)
        await state.update_data(arena_game=game); await state.set_state(ArenaStates.custom_stake)
        await c.message.answer("Введи целое число от 10 до 1000 тестовых звёзд."); await c.answer()
    @dp.message(ArenaStates.custom_stake)
    async def custom_value(m,state):
        raw=(m.text or "").strip()
        if not raw.isdigit() or not 10<=int(raw)<=1000: return await m.answer("Укажи сумму от 10 до 1000.")
        data=await state.get_data(); await state.clear(); await create_room(m,data["arena_game"],int(raw),m.from_user.id)
    @dp.callback_query(F.data.startswith("arena_stake:"))
    async def stake(c):
        try: _,game,amount=c.data.split(":"); amount=int(amount)
        except Exception: return await c.answer("Некорректная ставка",show_alert=True)
        await create_room(c.message,game,amount,c.from_user.id); await c.answer()
    @dp.callback_query(F.data.startswith("arena_join:"))
    async def join(c):
        try: rid=int(c.data.split(":")[1])
        except Exception: return await c.answer("Неверный матч",show_alert=True)
        result=db.arena_join(rid,c.from_user.id)
        if result!="ok": return await c.answer({"missing":"Матч не найден","closed":"Матч уже занят","self":"Нельзя играть самому с собой","funds":"Недостаточно тестовых звёзд"}.get(result,"Не удалось войти"),show_alert=True)
        await c.answer("Ты вошёл в матч!")
        if db.arena_room(rid)["game"]=="rps": await show_rps(rid)
        else: await show_ttt(rid)
    @dp.callback_query(F.data.startswith("rps:"))
    async def rps_move(c):
        try: _,rs,choice=c.data.split(":"); rid=int(rs)
        except Exception: return await c.answer("Неверный ход",show_alert=True)
        if choice not in ("rock","paper","scissors"): return await c.answer("Неверный ход",show_alert=True)
        r=db.arena_room(rid); uid=c.from_user.id
        if not r or r["status"]!="playing" or uid not in (r["host"],r["opponent"]): return await c.answer("Матч недоступен",show_alert=True)
        field="p1_choice" if uid==r["host"] else "p2_choice"
        if r[field]: return await c.answer("Ты уже сделал ход.",show_alert=True)
        db.arena_move(rid,uid,None,r["turn"],"playing",choice if field=="p1_choice" else None,choice if field=="p2_choice" else None)
        r=db.arena_room(rid); await c.answer("Ход принят")
        if not (r["p1_choice"] and r["p2_choice"]):
            try: await c.message.edit_text("Ход принят. Ожидаем соперника…")
            except Exception: pass
            return
        a,b=r["p1_choice"],r["p2_choice"]; beats={"rock":"scissors","scissors":"paper","paper":"rock"}; score=json.loads(r["board"] or '{"wins":[0,0],"round":1}')
        if a!=b: score["wins"][0 if beats[a]==b else 1]+=1
        labels={"rock":"Камень","paper":"Бумага","scissors":"Ножницы"}
        if max(score["wins"])>=3:
            winner=r["host"] if score["wins"][0]>=3 else r["opponent"]; db.arena_settle(rid,winner)
            for player in (r["host"],r["opponent"]):
                own=a if player==r["host"] else b; opp=b if player==r["host"] else a
                await bot.send_message(player,f"🏆 <b>Матч #{rid} завершён!</b>\n{labels[own]} — {labels[opp]}\nСчёт: {score['wins'][0]}:{score['wins'][1]}\nПобедитель: <code>{winner}</code>\nНачислено: ⭐ {float(r['stake'])*1.75:g}\nБаланс: ⭐ {db.arena_wallet(player):g}",parse_mode="HTML")
        else:
            score["round"]+=1; db.arena_move(rid,uid,json.dumps(score),r["turn"],"playing",None,None)
            for player in (r["host"],r["opponent"]):
                own=a if player==r["host"] else b; opp=b if player==r["host"] else a
                await bot.send_message(player,f"Раунд завершён: {labels[own]} — {labels[opp]}\nСчёт {score['wins'][0]}:{score['wins'][1]}. Следующий раунд!",parse_mode="HTML")
            await show_rps(rid)
    @dp.callback_query(F.data.startswith("ttt:"))
    async def ttt_move(c):
        try: _,rs,ps=c.data.split(":"); rid=int(rs); pos=int(ps)
        except Exception: return await c.answer("Неверный ход",show_alert=True)
        r=db.arena_room(rid); uid=c.from_user.id
        if not r or r["status"]!="playing" or uid not in (r["host"],r["opponent"]): return await c.answer("Матч недоступен",show_alert=True)
        if uid!=int(r["turn"]): return await c.answer("Сейчас не твой ход",show_alert=True)
        board=json.loads(r["board"] or '[null,null,null,null,null,null,null,null,null]')
        if not 0<=pos<=8 or board[pos] is not None: return await c.answer("Клетка занята",show_alert=True)
        mark="X" if uid==r["host"] else "O"; board[pos]=mark
        lines=((0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6))
        winner=uid if any(board[a]==board[b]==board[z]==mark for a,b,z in lines) else None; draw=winner is None and all(x is not None for x in board)
        nxt=r["opponent"] if uid==r["host"] else r["host"]; db.arena_move(rid,uid,json.dumps(board),nxt,"playing"); await c.answer()
        if winner is not None or draw:
            db.arena_settle(rid,winner)
            result="🤝 Ничья! Ставки возвращены." if draw else f"🏆 Победил <code>{winner}</code>! Начислено ⭐ {float(r['stake'])*1.75:g}"
            for player in (r["host"],r["opponent"]): await bot.send_message(player,f"❌ <b>Матч #{rid} завершён</b>\n{result}\nБаланс: ⭐ {db.arena_wallet(player):g}",parse_mode="HTML")
        else: await show_ttt(rid)
