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
("Общие команды группы",[
"!start — проверить подключение FENIX MANAGER.",
"!help, !cmds, !команды, !помощь — краткая справка.",
"!ping, !пинг, !status — проверить работу менеджера.",
"!setup — инструкция по первоначальной настройке группы.",
"!settings — показать настройки группы.",
"!rules — показать правила.",
"!admins — показать руководство группы.",
"!roles — показать иерархию ролей.",
"!stats ID — статистика участника.",
"!reg — регистрация участника (если включён соответствующий модуль).",
"!online — показать доступные сведения об онлайне.",
"!chatinfo — информация о беседе.",
"!report ТЕКСТ — отправить обращение руководству."
]),
("Модерация и наказания",[
"!mute 15m ПРИЧИНА — ограничить участника на срок; можно ответом или с ID.",
"!unmute — снять ограничение.",
"!kick — исключить участника из группы.",
"!warn ПРИЧИНА — выдать предупреждение.",
"!unwarn ID — снять предупреждение.",
"!getwarn ID — посмотреть число предупреждений.",
"!warnhistory ID — история предупреждений.",
"!warnlist — список предупреждений.",
"!ban [ДНИ] ПРИЧИНА — заблокировать участника; без срока — бессрочно.",
"!unban ID — снять блокировку.",
"!getban ID — проверить блокировку.",
"!banlist — список блокировок.",
"!del — удалить сообщение (ответом).",
"!purge N — удалить последние N сообщений.",
"!pin — закрепить сообщение (ответом).",
"!unpin — снять закрепление.",
"!silence — переключить режим тишины.",
"!wipe warns|filters|logs|nicks — очистить выбранный тип данных; команда требует повышенных прав."
]),
("Роли и уровни доступа",[
"!addhelper ID — назначить помощника.",
"!addmoder ID — назначить модератора.",
"!addadmin ID — назначить администратора.",
"!setrole ID 0|20|40|60|80|100 — установить уровень доступа.",
"!removerole ID — снять роль.",
"!newrole УРОВЕНЬ НАЗВАНИЕ — создать название роли.",
"!deleterole УРОВЕНЬ — удалить пользовательскую роль.",
"!access КОМАНДА УРОВЕНЬ — задать минимальный уровень для команды; !access КОМАНДА off — отключить ограничение.",
"+Модер ID — назначить ранг модератора.",
"+Админ ID — назначить ранг администратора.",
"Повысить ID — повысить участника на один уровень; Понизить ID — понизить на один уровень. Изменение ограничено правами вызывающего."
]),
("Настройки, фильтры и защита",[
"!welcome ТЕКСТ — задать приветствие; поддерживаются {name} и {id}.",
"!setrules ТЕКСТ — установить правила группы.",
"!setsettings mute on|off — включить или выключить режим ограничений.",
"!setsettings invite on|off — настроить режим приглашений.",
"!settingsmute — показать режим ограничений.",
"!settingsinvite — показать режим приглашений.",
"!filteradd ФРАЗА — добавить фильтр.",
"!filterdel ФРАЗА — удалить фильтр.",
"!filteredit СТАРАЯ => НОВАЯ — изменить фильтр (если поддерживается настройками модуля).",
"!filters — список фильтров.",
"!addlink URL — добавить разрешённую ссылку.",
"!whitelistlinks — показать разрешённые ссылки.",
"!antispam on|off|status — управление антифлуд-защитой.",
"!triggeradd ФРАЗА => ОТВЕТ — добавить автоответ.",
"!triggers — список автоответов.",
"!triggerdel ФРАЗА — удалить автоответ.",
"!logs — журнал действий и модерации."
]),
("Заметки, закладки, таймеры и опросы",[
"!note add ТЕКСТ — сохранить заметку.",
"!notes или !note list — список заметок.",
"!note del ID — удалить заметку.",
"!bookmark — сохранить сообщение в закладки (ответом).",
"!bookmarks — показать закладки.",
"!unbookmark ID — удалить закладку.",
"!timer 10m ТЕКСТ — создать напоминание (от 10 секунд до 30 дней).",
"!timers — список активных напоминаний.",
"!timerdel ID — отменить напоминание.",
"!vote ВОПРОС | ВАРИАНТ 1 | ВАРИАНТ 2 — создать опрос (до 6 вариантов).",
"!voteresult ID — посмотреть результаты.",
"!voteclose ID — закрыть опрос.",
"!report ТЕКСТ — отправить жалобу/обращение."
]),
("Общение и социальные функции",[
"!profile [ID] и !профиль [ID] — карточка участника.",
"!rep — повысить репутацию участнику (ответом на сообщение); начисление ограничено.",
"!топреп — рейтинг репутации.",
"!kiss — виртуальный поцелуй (ответом на сообщение).",
"!hug или !obnyat — виртуальное объятие (ответом).",
"!marry — предложить отношения (ответом на сообщение).",
"!divorce — завершить отношения.",
"!clan create НАЗВАНИЕ — создать клан.",
"!clan join НАЗВАНИЕ — вступить в клан.",
"!clan leave — выйти из клана.",
"!clan info — информация о клане.",
"!circle create НАЗВАНИЕ — создать круг.",
"!circle join НАЗВАНИЕ — вступить в круг.",
"!circle leave — выйти из круга.",
"!circle info и !circle list — сведения о кругах."
]),
("Игры, розыгрыши и объединения",[
"!dice или !кости — бросить кубик.",
"!duel или !дуэль — вызвать участника на дуэль (ответом).",
"!coin — подбросить монету.",
"!try или !попытка — случайная игровая реакция.",
"!giveaway 1h ПРИЗ — создать розыгрыш.",
"!gstop ID — завершить или отменить розыгрыш.",
"!unity — показать объединение беседы.",
"!unites — список объединений.",
"!addunity НАЗВАНИЕ — создать объединение и подключить беседу.",
"!removeunity — отключить беседу от объединения.",
"!editunity НОВОЕ_НАЗВАНИЕ — переименовать объединение.",
"!deleteunity НАЗВАНИЕ — удалить объединение."
]),
("Telegram Stars и подарки",[
"/stars — открыть магазин Telegram Stars.",
"/giftshop — открыть каталог Telegram-подарков.",
"/giftshop TELEGRAM_ID — выбрать подарок другому пользователю.",
"/premiumgift — купить Telegram Premium себе.",
"/premiumgift TELEGRAM_ID — подарить Premium другому пользователю.",
"/starsorders — история заказов Stars.",
"Оплата проводится средствами Telegram Stars. Подарок или Premium отправляется после подтверждения успешной оплаты; доступность и стоимость определяет актуальный каталог Telegram."
]),
("Ограничения Telegram и безопасность",[
"Бот не может получить полный список участников с их онлайн-статусами, узнать точную дату создания аккаунта или менять Telegram-ник пользователя.",
"Для модерации бот должен быть администратором группы с соответствующими правами. Не все команды доступны всем ролям.",
"Не отправляй пароли, токены и платёжные данные в групповой чат. При ошибке проверь права бота, привязку группы и свой уровень доступа."
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
    version="fenix-manager-full-2026-11-09-v3"
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
    @router.message(Command("help"))\n    @router.message(Command("commands"))
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
