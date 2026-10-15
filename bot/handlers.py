"""Telegram command and conversation handlers."""

import logging
import warnings
from datetime import datetime, timezone

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Message, MessageEntity, Update
from telegram.warnings import PTBUserWarning
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .config import Config
from .db import Database, Post
from .timeutil import TimeParseError, format_jalali, parse_schedule_time

log = logging.getLogger(__name__)

WAIT_CONTENT, WAIT_TIME, WAIT_CONFIRM = range(3)
CHECK_INTERVAL_SECONDS = 30

KIND_LABELS = {"text": "📝 متن", "photo": "🖼 عکس", "video": "🎬 ویدیو"}

HELP_TEXT = (
    "🌿 ربات مدیریت کانال\n\n"
    "دستورها:\n"
    "/post — انتشار فوری یک پست در کانال\n"
    "/schedule — زمان‌بندی پست برای تاریخ و ساعت مشخص\n"
    "/queue — نمایش پست‌های زمان‌بندی‌شده\n"
    "/cancel شماره — حذف پست از صف (مثلاً ‎/cancel 3‎)\n"
    "/cancel — لغو کاری که در حال انجامش هستید\n"
    "/id — نمایش شناسه عددی شما\n\n"
    "پست می‌تواند متن، عکس یا ویدیو (همراه با کپشن) باشد. "
    "قالب‌بندی متن (بولد، لینک و …) حفظ می‌شود."
)

TIME_HELP = (
    "⏰ زمان انتشار را بفرستید. نمونه‌ها:\n"
    "‎1405/07/28 18:30‎  (تاریخ شمسی)\n"
    "‎2026-10-20 18:30‎  (تاریخ میلادی)\n"
    "‎18:30‎  (امروز، یا فردا اگر این ساعت گذشته باشد)\n\n"
    "ساعت به وقت {tz} است."
)


def register(app: Application, config: Config, db: Database) -> None:
    app.bot_data["config"] = config
    app.bot_data["db"] = db
    admin = filters.User(user_id=list(config.admin_ids))

    content_filter = filters.TEXT & ~filters.COMMAND | filters.PHOTO | filters.VIDEO

    # The confirm buttons live in a private chat with one admin, so per-chat/per-user tracking is enough.
    warnings.filterwarnings("ignore", message=".*per_message=False.*", category=PTBUserWarning)
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("post", start_post, filters=admin),
            CommandHandler("schedule", start_schedule, filters=admin),
        ],
        states={
            WAIT_CONTENT: [MessageHandler(admin & content_filter, receive_content)],
            WAIT_TIME: [MessageHandler(admin & filters.TEXT & ~filters.COMMAND, receive_time)],
            WAIT_CONFIRM: [CallbackQueryHandler(confirm, pattern=r"^(confirm|abort)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel_command, filters=admin)],
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("queue", show_queue, filters=admin))
    app.add_handler(CommandHandler("cancel", cancel_command, filters=admin))
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("id", show_id))

    app.job_queue.run_repeating(publish_due_posts, interval=CHECK_INTERVAL_SECONDS, first=5)


# ---------- helpers ----------

def _cfg(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.bot_data["config"]


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.bot_data["db"]


def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return update.effective_user is not None and update.effective_user.id in _cfg(context).admin_ids


def extract_content(message: Message) -> dict | None:
    """Turn an incoming message into a storable post draft."""
    if message.photo:
        kind, file_id = "photo", message.photo[-1].file_id
        text, entities = message.caption, message.caption_entities
    elif message.video:
        kind, file_id = "video", message.video.file_id
        text, entities = message.caption, message.caption_entities
    elif message.text:
        kind, file_id = "text", None
        text, entities = message.text, message.entities
    else:
        return None
    return {
        "kind": kind,
        "file_id": file_id,
        "text": text,
        "entities": [e.to_dict() for e in entities or ()],
    }


async def send_content(bot: Bot, chat_id: int | str, kind: str, text: str | None,
                       entities: list[dict], file_id: str | None, **kwargs) -> Message:
    ents = MessageEntity.de_list(entities, bot) or None
    if kind == "photo":
        return await bot.send_photo(chat_id, file_id, caption=text, caption_entities=ents, **kwargs)
    if kind == "video":
        return await bot.send_video(chat_id, file_id, caption=text, caption_entities=ents, **kwargs)
    return await bot.send_message(chat_id, text, entities=ents, **kwargs)


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تأیید", callback_data="confirm"),
        InlineKeyboardButton("❌ انصراف", callback_data="abort"),
    ]])


# ---------- basic commands ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _is_admin(update, context):
        await update.message.reply_text(HELP_TEXT)
    else:
        await update.message.reply_text(
            "سلام 🌸\nاین ربات فقط برای مدیران کانال فعال است."
        )


async def show_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"شناسه عددی شما: {update.effective_user.id}")


# ---------- post / schedule conversation ----------

async def start_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    context.user_data["mode"] = "now"
    await update.message.reply_text(
        "📤 پستی که می‌خواهید فوراً منتشر شود را بفرستید (متن، عکس یا ویدیو).\nبرای لغو: /cancel"
    )
    return WAIT_CONTENT


async def start_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    context.user_data["mode"] = "schedule"
    await update.message.reply_text(
        "🗓 پستی که می‌خواهید زمان‌بندی شود را بفرستید (متن، عکس یا ویدیو).\nبرای لغو: /cancel"
    )
    return WAIT_CONTENT


async def receive_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = extract_content(update.message)
    if draft is None:
        await update.message.reply_text("فقط متن، عکس یا ویدیو پشتیبانی می‌شود. دوباره بفرستید.")
        return WAIT_CONTENT
    context.user_data["draft"] = draft

    if context.user_data.get("mode") == "schedule":
        await update.message.reply_text(TIME_HELP.format(tz=_cfg(context).timezone.key))
        return WAIT_TIME

    await update.message.reply_text("👇 پیش‌نمایش پست:")
    await send_content(context.bot, update.effective_chat.id, **draft)
    await update.message.reply_text("این پست الان در کانال منتشر شود؟", reply_markup=_confirm_keyboard())
    return WAIT_CONFIRM


async def receive_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tz = _cfg(context).timezone
    try:
        send_at = parse_schedule_time(update.message.text, tz)
    except TimeParseError:
        await update.message.reply_text("❗️ قالب زمان درست نیست.\n\n" + TIME_HELP.format(tz=tz.key))
        return WAIT_TIME
    if send_at <= datetime.now(tz):
        await update.message.reply_text("❗️ این زمان گذشته است. یک زمان در آینده بفرستید.")
        return WAIT_TIME

    context.user_data["send_at"] = send_at.isoformat()
    await update.message.reply_text("👇 پیش‌نمایش پست:")
    await send_content(context.bot, update.effective_chat.id, **context.user_data["draft"])
    await update.message.reply_text(
        f"این پست در تاریخ {format_jalali(send_at, tz)} منتشر شود؟",
        reply_markup=_confirm_keyboard(),
    )
    return WAIT_CONFIRM


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "abort" or "draft" not in context.user_data:
        context.user_data.clear()
        await query.edit_message_text("❌ لغو شد.")
        return ConversationHandler.END

    draft = context.user_data["draft"]
    cfg = _cfg(context)

    if context.user_data.get("mode") == "schedule":
        send_at = datetime.fromisoformat(context.user_data["send_at"])
        post_id = _db(context).add_post(created_by=update.effective_user.id, send_at=send_at, **draft)
        await query.edit_message_text(
            f"✅ پست شماره {post_id} برای {format_jalali(send_at, cfg.timezone)} زمان‌بندی شد.\n"
            f"برای حذف: ‎/cancel {post_id}‎"
        )
    else:
        try:
            await send_content(context.bot, cfg.channel_id, **draft)
        except Exception as exc:  # noqa: BLE001 - report any Telegram error to the admin
            log.exception("Publishing failed")
            await query.edit_message_text(f"⚠️ انتشار ناموفق بود:\n{exc}")
            return ConversationHandler.END
        await query.edit_message_text("✅ پست در کانال منتشر شد.")

    context.user_data.clear()
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if context.args:
        await _cancel_post(update, context, context.args[0])
        return None  # stay in the current conversation state, if any
    had_draft = bool(context.user_data)
    context.user_data.clear()
    await update.message.reply_text("❌ لغو شد." if had_draft else "کاری برای لغو وجود ندارد.")
    return ConversationHandler.END


async def _cancel_post(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_id: str) -> None:
    try:
        post_id = int(raw_id.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
    except ValueError:
        await update.message.reply_text("شماره پست باید عدد باشد. مثال: ‎/cancel 3‎")
        return
    if _db(context).cancel(post_id):
        await update.message.reply_text(f"🗑 پست شماره {post_id} از صف حذف شد.")
    else:
        await update.message.reply_text(f"پست در انتظاری با شماره {post_id} پیدا نشد.")


# ---------- queue ----------

def _summary(post: Post, limit: int = 40) -> str:
    text = (post.text or "").replace("\n", " ").strip()
    if len(text) > limit:
        text = text[:limit] + "…"
    return text or "(بدون متن)"


async def show_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    posts = _db(context).pending()
    if not posts:
        await update.message.reply_text("📭 صف خالی است.")
        return
    tz = _cfg(context).timezone
    lines = ["🗓 پست‌های زمان‌بندی‌شده:\n"]
    for p in posts:
        lines.append(f"#{p.id} • {format_jalali(p.send_at, tz)} • {KIND_LABELS[p.kind]}\n{_summary(p)}\n")
    lines.append("برای حذف: ‎/cancel شماره‎")
    await update.message.reply_text("\n".join(lines))


# ---------- scheduler job ----------

async def publish_due_posts(context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    cfg = _cfg(context)
    for post in db.due(datetime.now(timezone.utc)):
        try:
            await send_content(context.bot, cfg.channel_id, post.kind, post.text, post.entities, post.file_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("Scheduled post %s failed", post.id)
            db.mark_failed(post.id, str(exc))
            await _notify(context.bot, post.created_by, f"⚠️ انتشار پست شماره {post.id} ناموفق بود:\n{exc}")
            continue
        db.mark_sent(post.id)
        log.info("Published scheduled post %s", post.id)
        await _notify(context.bot, post.created_by, f"✅ پست شماره {post.id} در کانال منتشر شد.")


async def _notify(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text)
    except Exception:  # noqa: BLE001 - the admin may have blocked the bot
        log.warning("Could not notify %s", chat_id)
