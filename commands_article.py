"""Publish and serve the FENIX MANAGER command reference on Telegraph."""
import json
import logging
import aiohttp
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

log=logging.getLogger("fenix.commands_article")
TITLE="FENIX MANAGER — полный список команд"
AUTHOR="FENIX ONLINE"

SECTIONS=[
("Как пользоваться",[
"В группах команды можно вводить с префиксом !, точкой или /. Для действий над участником ответь на его сообщение либо укажи числовой Telegram ID. Бот должен быть администратором группы с необходимыми правами.",
"Уровни доступа: 20 — Помощник; 40 — Модератор; 60 — Администратор; 80 — Главный администратор; 100 — Владелец."
]),
("Основные команды",[
"!help — показать справочник команд.",
"!ping — проверить работу FENIX MANAGER.",
"!setup — инструкция по первоначальной настройке группы.",
"!settings — показать настройки группы.",
"!rules — показать правила группы.",
"!admins — показать руководство группы.",
"!stats [ID] — статистика участника.",
"!chatinfo — информация о беседе.",
"!report текст — отправить обращение руководству."
]),
("Модерация и наказания",[
"!mute 15m причина — ограничить участника на срок; можно ответом на сообщение или с ID.",
"!unmute — снять ограничение.",
"!warn причина — выдать предупреждение.",
"!unwarn ID — снять предупреждение.",
"!getwarn ID — посмотреть число предупреждений.",
"!warnhistory ID — история предупреждений.",
"!warnlist — список предупреждений.",
"!kick — исключить участника.",
"!ban 3 причина — заблокировать участника (число перед причиной задаёт дни; без числа — бессрочно).",
"!unban ID — снять блокировку.",
"!getban ID — проверить блокировку.",
"!banlist — список блокировок.",
"!del — удалить сообщение (ответом).",
"!purge N — удалить последние N сообщений.",
"!pin — закрепить сообщение (ответом).",
"!unpin — снять закрепление.",
"!silence — включить или выключить режим тишины."
]),
("Роли и доступ",[
"!addhelper ID — назначить помощника.",
"!addmoder ID — назначить модератора.",
"!addadmin ID — назначить администратора.",
"!setrole ID уровень — назначить уровень доступа.",
"!removerole ID — снять роль.",
"!roles — список ролей.",
"!newrole приоритет название — создать название уровня.",
"!deleterole приоритет — удалить роль указанного уровня.",
"!access команда уровень — ограничить команду по уровню; !access команда off — отключить её."
]),
("Настройки группы и защита",[
"!welcome текст — задать приветствие; поддерживаются {name} и {id}.",
"!setrules текст — задать правила.",
"!setsettings параметр значение — изменить параметр беседы.",
"!settingsmute on|off — настройка режима ограничений.",
"!settingsinvite on|off — настройка ссылок и приглашений.",
"!filteradd фраза — добавить фильтр.",
"!filterdel фраза — удалить фильтр.",
"!filters — показать фильтры.",
"!addlink https://example.com — добавить разрешённую ссылку.",
"!whitelistlinks — показать разрешённые ссылки.",
"!antispam on|off|status — управление антифлуд-защитой.",
"!triggeradd фраза => ответ — создать автоответ.",
"!triggers — показать автоответы.",
"!triggerdel фраза — удалить автоответ.",
"!logs — показать журнал модерации."
]),
("Профиль и общение",[
"!profile [ID] — карточка участника.",
"!rep — повысить репутацию участнику (ответом на его сообщение); повторное начисление ограничено.",
"!топреп — рейтинг репутации.",
"!note add текст — сохранить личную заметку.",
"!notes — список заметок.",
"!note del ID — удалить свою заметку.",
"!bookmark — сохранить сообщение в закладки (ответом).",
"!bookmarks — список закладок.",
"!kiss — отправить виртуальный поцелуй (ответом).",
"!hug / !obnyat — виртуальное объятие (ответом).",
"!marry — предложить отношения (ответом).",
"!divorce — завершить отношения (ответом).",
"!clan create название — создать клан.",
"!clan join название / !clan leave — вступить или выйти из клана.",
"!clan info — показать информацию о клане беседы."
]),
("Развлечения, таймеры и розыгрыши",[
"!dice — бросить кубик.",
"!duel — вызвать участника на дуэль (ответом на его сообщение).",
"!coin — подбросить монету.",
"!try — случайная игровая реакция.",
"!timer 10m текст — создать сохраняемое напоминание (от 10 секунд до 30 дней)." ,
"!timers — список активных напоминаний.",
"!timerdel ID — отменить напоминание.",
"!vote Вопрос | Вариант 1 | Вариант 2 — создать опрос (до 6 вариантов).",
"!voteresult ID — посмотреть результаты опроса.",
"!voteclose ID — закрыть опрос.",
"!giveaway 1h приз — создать розыгрыш.",
"!gstop ID — завершить или отменить розыгрыш.",
"!circle create название — создать круг.",
"!circle join название / !circle leave — вступить или выйти.",
"!circle info / !circle list — информация о кругах беседы."
]),
("Объединения",[
"!unity — показать объединение текущей беседы.",
"!unites — список объединений.",
"!addunity название — создать объединение и подключить беседу.",
"!removeunity — отключить беседу от объединения.",
"!editunity новое название — переименовать объединение.",
"!deleteunity название — удалить объединение."
]),
("Telegram Stars и подарки",[
"/stars — открыть магазин Telegram Stars.",
"/giftshop — открыть каталог реальных Telegram-подарков для себя.",
"/giftshop TELEGRAM_ID — выбрать подарок другому пользователю.",
"/premiumgift — купить Telegram Premium себе.",
"/premiumgift TELEGRAM_ID — подарить Premium другому пользователю.",
"/myid — узнать свой Telegram ID.",
"/starsorders — история заказов Stars.",
"Платёж проходит в Telegram Stars. Подарок или Premium отправляется только после подтверждения успешной оплаты. Доступность подарков и их стоимость определяются актуальным каталогом Telegram."
]),
("Ограничения Telegram",[
"Бот не может узнать дату создания Telegram-аккаунта, полный список участников с их онлайн-статусами или изменить Telegram-ник пользователя. Некоторые действия доступны только если Telegram выдал боту соответствующие права администратора.",
"Для получения подарка другому человеку нужен его числовой Telegram ID. Пользователь должен быть доступен Telegram API для отправки подарка."
])
]

def nodes():
    out=[]
    for heading,items in SECTIONS:
        out.append({"tag":"h3","children":[heading]})
        out.append({"tag":"ul","children":[{"tag":"li","children":[item]} for item in items]})
    out.append({"tag":"p","children":["FENIX ONLINE · FENIX MANAGER"]})
    return out

async def ensure_article(db):
    existing=(db.setting("fenix_commands_article_url","") or "").strip()
    version="fenix-iris-full-2026-11"
    if existing and db.setting("fenix_commands_article_version","") == version:
        return existing
    timeout=aiohttp.ClientTimeout(total=35)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post("https://api.telegra.ph/createAccount",data={
            "short_name":"FENIX","author_name":AUTHOR
        }) as response:
            account=await response.json(content_type=None)
        if not account.get("ok"):
            raise RuntimeError("Telegraph createAccount: "+str(account.get("error")))
        token=account["result"]["access_token"]
        async with session.post("https://api.telegra.ph/createPage",data={
            "access_token":token,"title":TITLE,"author_name":AUTHOR,
            "content":json.dumps(nodes(),ensure_ascii=False),"return_content":"false"
        }) as response:
            page=await response.json(content_type=None)
        if not page.get("ok"):
            raise RuntimeError("Telegraph createPage: "+str(page.get("error")))
        url=page["result"]["url"]
        db.set_setting("fenix_commands_article_url",url)
        db.set_setting("fenix_commands_article_path",page["result"]["path"])
        db.set_setting("fenix_commands_article_version",version)
        log.info("FENIX command reference published: %s",url)
        return url

def register(dp,db):
    router=Router(name="fenix_commands_reference")
    @router.message(Command("commands"))
    async def commands(m):
        url=(db.setting("fenix_commands_article_url","") or "").strip()
        if not url:
            try:
                url=await ensure_article(db)
            except Exception:
                log.exception("On-demand FENIX command article publishing failed")
                return await m.answer("Не удалось опубликовать справочник. Попробуй позже.")
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📖 Открыть полный справочник FENIX MANAGER",url=url)]])
        await m.answer("<b>FENIX MANAGER · СПРАВОЧНИК КОМАНД</b>\nВсе команды, уровни доступа, настройки, модерация, развлечения и Telegram Stars собраны в одной статье.",parse_mode="HTML",reply_markup=kb)
    dp.include_router(router)
