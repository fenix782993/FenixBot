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
"FENIX MANAGER работает в группах. Команды менеджера вводятся с ! или точкой; для команд бота используются /. Можно отвечать на сообщение участника или указывать его числовой Telegram ID. Бот должен быть администратором группы с нужными правами.",
"Уровни доступа: 20 — Помощник; 40 — Модератор; 60 — Администратор; 80 — Главный администратор; 100 — Владелец. Уровень проверяется для каждой команды отдельно.",
"Для открытия меню используй /fenix. Для этой страницы — /help или /commands. Список возможностей зависит от включённых модулей, прав Telegram и настроек конкретной группы."
]),
("Команды бота FENIX",[
"/start — открыть главное меню бота.",
"/help и /commands — получить ссылку на этот полный справочник.",
"/id — узнать свой Telegram ID.",
"/fenixid и /idcard — открыть карточку FENIX ID.",
"/invite — открыть реферальный раздел и получить персональную ссылку.",
"/media_video — отправить сведения о видео или публикации в раздел медиа.",
"/cancel — отменить текущий пошаговый ввод.",
"/chatid — показать ID чата и пользователя, а также привязки служебных чатов (для администраторов бота)."
]),
("Состав и служебные чаты",[
"/staffhelp — инструкция по управлению составом.",
"/bind_admin_chat — привязать текущую группу как административный чат.",
"/bind_leader_chat — привязать текущую группу как лидерский чат.",
"/stafflist — показать состав привязанного чата.",
"/nnick ИгровойНик Должность — назначить или изменить должность игрока.",
"/staffremove ИгровойНик — снять должность с игрока.",
"/setlabel — настроить подпись/метку состава (если доступно владельцу)."
]),
("FENIX ID и профиль",[
"Карточка FENIX ID открывается командами /fenixid или /idcard. Команда /id показывает Telegram ID. Дополнительные поля и разделы кабинета доступны через меню бота, если профиль зарегистрирован.",
"/invite — реферальная ссылка. Приглашённый пользователь должен перейти по ней и запустить бота.",
"/media_video — передать ссылку и данные о публикации для учёта FENIX MEDIA."
]),
("Premium Custom Emoji",[
"/emojipack — импортировать Premium Custom Emoji по ссылке на набор Telegram.",
"/emojipacks — показать импортированные наборы.",
"/emojipackremove — удалить импортированный набор.",
"/emojilist — показать сохранённые emoji ID.",
"/emojistatus — проверить состояние и количество emoji.",
"/emojiids85 — служебная команда импорта/проверки emoji (только владелец).",
"/btnlist — показать каталог кнопок и их ключи.",
"/setbtnemoji НОМЕР_КНОПКИ НОМЕР_ЭМОДЗИ — назначить emoji по номерам из списков.",
"/setbtnemojiid КЛЮЧ ID_ЭМОДЗИ — назначить emoji по ключу кнопки и custom_emoji_id.",
"/resetbtnemoji — сбросить индивидуальные назначения.",
"/premiumall — запустить пошаговую настройку Premium Emoji.",
"/premiumstop — остановить пошаговую настройку.",
"/clearbuttonemoji — очистить назначения emoji кнопок.",
"/setbtnstyle — изменить доступный стиль кнопок. Команды настройки emoji доступны владельцу."
]),
("Команды Chat Manager в группе",[
"Команды ниже вводятся в группе с !. Можно ответить на сообщение участника вместо Telegram ID. Для модерации у FENIX должны быть права администратора Telegram.",
"!start / !начать — проверить подключение менеджера.",
"!help / !cmds / !команды / !помощь — вывести полный список команд в чате.",
"!ping / !пинг / !status / !статус / !test / !тест — проверить работу менеджера.",
"!rules / !правила — показать правила беседы.",
"!chatinfo / !info / !инфо / !чатинфо — информация о беседе.",
"!admins / !staff / !админы — список руководства.",
"!roles / !роли — иерархия ролей.",
"!stats [ID] / !стата / !статистика — карточка участника: ник, роль и активные предупреждения.",
"!reg [ID] / !рег — дата регистрации в базе FENIX; дату создания Telegram-аккаунта Bot API не раскрывает.",
"!online / !онлайн — объяснение ограничения Telegram API: бот не видит полный онлайн-статус участников.",
"!report ТЕКСТ / !репорт ТЕКСТ — отправить обращение руководству.",
"!try / !попытка — игровая случайная реакция.",
"!kiss / !поцелуй / !поцеловать — виртуальный поцелуй; ответь на сообщение или укажи ID.",
"!obnyat / !обнять — виртуальное объятие; ответь на сообщение или укажи ID."
]),
("Модерация и игровые ники",[
"!mute 15m ПРИЧИНА / !мут — ограничить участника. Форматы времени: 30s, 15m, 2h, 3d; если срок не указан, применяется час.",
"!unmute / !унмут — снять ограничение.",
"!kick / !кик / !исключить — исключить участника.",
"!warn ПРИЧИНА / !варн / !пред — выдать предупреждение.",
"!unwarn ID / !унварн — снять предупреждение.",
"!getwarn ID / !предупреждения — история предупреждений участника.",
"!warnhistory ID / !историяварнов — история предупреждений участника.",
"!warnlist / !преды — список предупреждений беседы.",
"!ban [ДНИ] ПРИЧИНА / !блок — заблокировать участника; число дней необязательно.",
"!unban ID / !унблок — снять блокировку.",
"!getban ID / !гетбан — проверить блокировку.",
"!banlist — список блокировок.",
"!getnick ID / !nick / !gnick / !ник — посмотреть сохранённый игровой ник.",
"!setnick ID НИК / !snick — установить игровой ник.",
"!removenick ID / !rnick — удалить игровой ник.",
"!nicknames / !nlist — список сохранённых игровых ников.",
"!nonames / !безников — записи без игрового ника.",
"!getbynick НИК / !понику — найти пользователя по игровому нику.",
"!wipe warns|filters|logs|nicks / !вайп — очистить предупреждения, фильтры, журнал или игровые ники (40+)."
]),
("Роли и уровни доступа",[
"!addhelper ID / !helper — назначить помощника (40+).",
"!addmoder ID / !moder — назначить модератора (60+).",
"!addadmin ID — назначить администратора (80+).",
"!setrole ID 0|20|40|60|80|100 / !role — установить уровень роли (80+).",
"!removerole ID / !rr — снять роль (80+).",
"!newrole ПРИОРИТЕТ НАЗВАНИЕ — задать название для уровня 20, 40, 60 или 80 (80+).",
"!deleterole ПРИОРИТЕТ / !delrole — удалить назначения указанного уровня (80+).",
"!+модер ID, !+админ ID, !повысить ID, !понизить ID — изменить ранг участника с учётом прав вызывающего.",
"Уровни: 20 — Помощник; 40 — Модератор; 60 — Администратор; 80 — Главный администратор; 100 — Владелец."
]),
("Настройки, фильтры и ссылки",[
"!setup — инструкция первичной настройки (владелец беседы).",
"!settings — показать настройки беседы (владелец).",
"!settingsmute — показать режим ограничений (владелец).",
"!settingsinvite — показать режим приглашений (владелец).",
"!setsettings mute on|off — включить или выключить режим ограничений (владелец).",
"!setsettings invite on|off — включить или выключить ограничения приглашений (владелец).",
"!welcome ТЕКСТ — установить приветствие; пустой текст очищает его (80+). В тексте доступны {name} и {id}.",
"!setrules ТЕКСТ — установить правила; пустой текст очищает их (80+).",
"!silence / !тишина — переключить режим тишины (60+).",
"!filters / !фильтры / !filteredit — показать список фильтров (60+).",
"!filteradd ФРАЗА — добавить запрещённую фразу (60+).",
"!filterdel ФРАЗА — удалить фразу из фильтра (60+).",
"!addlink https://site.ru — добавить разрешённую ссылку (60+).",
"!whitelistlinks — показать белый список ссылок (60+).",
"!pin / !закрепить — закрепить сообщение, отправляется ответом на него (60+).",
"!unpin / !открепить — снять закрепление (60+)."
]),
("Журнал, вызов и объединения",[
"!logs / !логи — последние действия в журнале.",
"!zov / !зов / !вызов — пояснение по объявлению для участников; Telegram не позволяет боту гарантированно получить полный список участников для массового упоминания.",
"!unity — показать объединение текущей беседы.",
"!unites — список объединений.",
"!addunity НАЗВАНИЕ — создать объединение и подключить к нему беседу (владелец).",
"!removeunity — отключить беседу от объединения (владелец).",
"!editunity НОВОЕ_НАЗВАНИЕ — переименовать объединение (владелец).",
"!deleteunity НАЗВАНИЕ — удалить объединение (владелец)."
]),
("Зарезервированные команды",[
"!voice, !mafia / !мафия, !emoji / !эмодзи, !enick / !никэмодзи — команды присутствуют как заглушки и сейчас не выполняют действий."
]),
("Панель управления FENIX",[
"/chatmanager — открыть список подключённых бесед и панель управления; доступ владельцу/администратору бота.",
"В панели доступны просмотр бесед, настройки, модерация, роли, магазин Telegram-подарков и ссылка на этот справочник."
]),
("Ограничения Telegram и безопасность",[
"Telegram Bot API не предоставляет боту полный список участников и их онлайн-статус, а также точную дату создания Telegram-аккаунта.",
"Для модерации бот должен быть администратором группы с соответствующими правами. Команды ограничены уровнями доступа; владелец группы автоматически получает уровень 100.",
"Не отправляй пароли, токены и платёжные данные в групповой чат."
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
    saved_token=(db.setting("fenix_commands_article_token","") or "").strip()
    saved_path=(db.setting("fenix_commands_article_path","") or "").strip()
    version="fenix-manager-full-2026-11-09-v6"
    if existing and db.setting("fenix_commands_article_version","") == version:
        return existing
    timeout=aiohttp.ClientTimeout(total=35)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        token=saved_token
        page=None
        if token and saved_path:
            async with session.post("https://api.telegra.ph/editPage",data={
                "access_token":token,"path":saved_path,"title":TITLE,"author_name":AUTHOR,
                "content":json.dumps(nodes(),ensure_ascii=False),"return_content":"false"
            }) as response:
                page=await response.json(content_type=None)
        if not page or not page.get("ok"):
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
        db.set_setting("fenix_commands_article_token",token)
        db.set_setting("fenix_commands_article_version",version)
        log.info("FENIX command reference published: %s",url)
        return url

def register(dp,db):
    router=Router(name="fenix_commands_reference")
    @router.message(Command("help"))
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
        await m.answer("<b>FENIX MANAGER · СПРАВОЧНИК КОМАНД</b>\nВсе команды FENIX BOT и FENIX MANAGER, роли, настройки, модерация, инструменты, развлечения и Telegram Stars собраны в одной статье.",parse_mode="HTML",reply_markup=kb)
    dp.include_router(router)
