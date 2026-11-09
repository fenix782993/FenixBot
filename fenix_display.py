from html import escape

async def user_label(bot, chat_id, user_id, user=None):
    """Return a safe clickable @username/name label instead of exposing raw Telegram IDs."""
    if user is None:
        try:
            member = await bot.get_chat_member(chat_id, int(user_id))
            user = member.user
        except Exception:
            try:
                user = await bot.get_chat(int(user_id))
            except Exception:
                user = None
    username = getattr(user, "username", None) if user else None
    if username:
        label = "@" + str(username)
    else:
        label = (
            getattr(user, "full_name", None)
            or getattr(user, "first_name", None)
            or "Участник"
        ) if user else "Участник"
    return f'<a href="tg://user?id={int(user_id)}">{escape(str(label))}</a>'
