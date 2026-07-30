import json
import logging
import os

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8168690441:AAEAdOL4Ioc1BVbV9_U-xEK87_n0_jmMfqI"
ADMIN_IDS = [6235378997, 339202761]  # впиши сюда ID через запятую
CHATS_FILE = "chats.json"
# ================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def load_chats() -> dict:
    if os.path.exists(CHATS_FILE):
        try:
            with open(CHATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Поддержка старого формата (список ID без названий)
                if isinstance(data, list):
                    return {str(chat_id): str(chat_id) for chat_id in data}
                return data
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def save_chats(chats: dict) -> None:
    with open(CHATS_FILE, "w", encoding="utf-8") as f:
        json.dump(chats, f, ensure_ascii=False)


def is_admin(update: Update) -> bool:
    return update.effective_user is not None and update.effective_user.id in ADMIN_IDS


def admin_panel_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📢 Рассылка", callback_data="menu_broadcast")],
        [InlineKeyboardButton("📊 Статистика", callback_data="menu_stats")],
        [InlineKeyboardButton("📋 Список чатов", callback_data="menu_list")],
    ]
    return InlineKeyboardMarkup(keyboard)


def persistent_reply_markup() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [["📋 Меню"]],
        resize_keyboard=True,
    )


# ---------- Отслеживание добавления/удаления бота из чатов ----------

async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = update.my_chat_member
    chat_id = str(result.chat.id)
    new_status = result.new_chat_member.status
    chat_title = result.chat.title or result.chat.full_name or chat_id

    chats = load_chats()

    if new_status in ("member", "administrator"):
        if chat_id not in chats or chats[chat_id] != chat_title:
            chats[chat_id] = chat_title
            save_chats(chats)
            logger.info(f"Бот добавлен в чат {chat_id} ({chat_title})")
    elif new_status in ("left", "kicked"):
        if chat_id in chats:
            del chats[chat_id]
            save_chats(chats)
            logger.info(f"Бот удалён из чата {chat_id}")


# ---------- Команды ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private":
        return
    if not is_admin(update):
        return
    context.user_data["awaiting_broadcast"] = False
    await update.message.reply_text(
        "Бот запущен. Кнопка «📋 Меню» всегда снизу — жми на неё, чтобы открыть панель.",
        reply_markup=persistent_reply_markup(),
    )
    await update.message.reply_text("Админ-панель:", reply_markup=admin_panel_markup())


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /broadcast <текст> — разослать текст во все чаты
    /broadcast (ответом на сообщение) — разослать это сообщение (фото/файл/видео и т.д.)
    """
    if not is_admin(update):
        return

    source_message = update.message.reply_to_message
    text_arg = " ".join(context.args) if context.args else None

    if not source_message and not text_arg:
        await update.message.reply_text(
            "Укажи текст после команды или сделай /broadcast ответом на нужное сообщение."
        )
        return

    await do_broadcast(update, context, source_message=source_message, text_arg=text_arg)


async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, source_message=None, text_arg=None) -> None:
    chats = load_chats()
    if not chats:
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(chat_id=admin_id, text="Нет ни одного чата для рассылки.")
        return

    sent, failed = 0, 0

    for chat_id in list(chats.keys()):
        try:
            if source_message:
                await context.bot.copy_message(
                    chat_id=int(chat_id),
                    from_chat_id=source_message.chat_id,
                    message_id=source_message.message_id,
                )
            else:
                await context.bot.send_message(
                    chat_id=int(chat_id),
                    text=text_arg,
                    parse_mode=ParseMode.HTML,
                )
            sent += 1
        except Exception as e:
            failed += 1
            logger.warning(f"Не удалось отправить в чат {chat_id}: {e}")

    for admin_id in ADMIN_IDS:
        await context.bot.send_message(
            chat_id=admin_id,
            text=f"Готово. Отправлено: {sent}. Ошибок: {failed}.",
        )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id not in ADMIN_IDS:
        await query.answer()
        return

    await query.answer()

    if query.data == "menu_stats":
        chats = load_chats()
        await query.edit_message_text(
            f"Бот состоит в {len(chats)} чатах.",
            reply_markup=admin_panel_markup(),
        )

    elif query.data == "menu_list":
        chats = load_chats()
        if not chats:
            text = "Список чатов пуст."
        else:
            text = "\n".join(f"• {title}" for title in chats.values())
        await query.edit_message_text(text, reply_markup=admin_panel_markup())

    elif query.data == "menu_broadcast":
        context.user_data["awaiting_broadcast"] = True
        await query.edit_message_text(
            "Отправь текст рассылки, либо перешли/ответь сообщением (фото, файл, видео и т.д.), "
            "которое нужно разослать.\n\nДля отмены — /start"
        )


async def awaiting_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return

    message = update.message

    if message.text == "📋 Меню":
        context.user_data["awaiting_broadcast"] = False
        await message.reply_text("Админ-панель:", reply_markup=admin_panel_markup())
        return

    if not context.user_data.get("awaiting_broadcast"):
        return

    context.user_data["awaiting_broadcast"] = False

    if message.text:
        await do_broadcast(update, context, text_arg=message.text)
    else:
        await do_broadcast(update, context, source_message=message)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Админ-панель:",
        reply_markup=admin_panel_markup(),
    )


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(ChatMemberHandler(track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND,
            awaiting_broadcast_handler,
        )
    )

    logger.info("Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
