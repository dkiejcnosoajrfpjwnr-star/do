#!/usr/bin/env python3
# ==========================================
#   بوت تحميل الفيديوهات - Python
#   Owner ID: 7323316462
# ==========================================

import os
import json
import asyncio
import logging
import yt_dlp
from pathlib import Path
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.error import TelegramError

# ──────────────────────────────────────────
#  إعدادات البوت
# ──────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7672706228:AAEQI5VlFCUH31e2A7ZOfuh2J9TC9ssQDIU")
OWNER_ID  = 7323316462
DB_FILE   = "database.json"
TEMP_DIR  = "downloads"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
#  قاعدة البيانات (JSON)
# ──────────────────────────────────────────
def load_db() -> dict:
    if not Path(DB_FILE).exists():
        return {
            "users": {},
            "channels": [],
            "start_message": (
                "مرحباً بك! 👋\n\n"
                "أرسل لي رابط أي فيديو من تيك توك، انستغرام، تويتر، فيسبوك وغيرها "
                "وسأقوم بتحميله لك فوراً 🎬\n\n"
                "ملاحظة: يوتيوب غير مدعوم."
            ),
            "states": {}
        }
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def register_user(db: dict, user_id: int, username: str):
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = {"id": user_id, "username": username or ""}
        save_db(db)

def get_all_users(db: dict) -> list:
    return list(db["users"].values())

def get_state(db: dict, user_id: int):
    return db.get("states", {}).get(str(user_id))

def set_state(db: dict, user_id: int, state: dict):
    if "states" not in db:
        db["states"] = {}
    db["states"][str(user_id)] = state
    save_db(db)

def clear_state(db: dict, user_id: int):
    if "states" in db and str(user_id) in db["states"]:
        del db["states"][str(user_id)]
        save_db(db)

# ──────────────────────────────────────────
#  مجلد التحميل المؤقت
# ──────────────────────────────────────────
Path(TEMP_DIR).mkdir(exist_ok=True)

# ──────────────────────────────────────────
#  تحميل الفيديو باستخدام yt-dlp
# ──────────────────────────────────────────
SUPPORTED_DOMAINS = [
    "tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
    "instagram.com", "twitter.com", "x.com",
    "facebook.com", "fb.watch", "reddit.com",
    "twitch.tv", "dailymotion.com", "vimeo.com",
    "pinterest.com", "snapchat.com", "likee.video",
    "bilibili.com", "ok.ru", "vk.com",
    "soundcloud.com", "streamable.com", "medal.tv",
    "ifunny.co", "9gag.com", "tumblr.com",
    "coub.com", "rumble.com", "odysee.com",
    "loom.com", "linkedin.com",
]

def is_youtube(url: str) -> bool:
    return any(d in url.lower() for d in ["youtube.com", "youtu.be"])

def is_supported(url: str) -> bool:
    return any(d in url.lower() for d in SUPPORTED_DOMAINS)

def extract_url(text: str):
    import re
    match = re.search(r"https?://[^\s]+", text)
    return match.group(0) if match else None

async def download_video(url: str) -> dict:
    try:
        output_template = os.path.join(TEMP_DIR, "%(title).80s.%(ext)s")
        ydl_opts = {
            "outtmpl": output_template,
            "format": (
                "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]"
                "/best[ext=mp4][height<=720]/best[height<=720]/best"
            ),
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "max_filesize": 50 * 1024 * 1024,
        }

        loop = asyncio.get_event_loop()

        def _download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info is None:
                    return None
                title = info.get("title", "فيديو")
                filename = ydl.prepare_filename(info)
                if not os.path.exists(filename):
                    filename = filename.rsplit(".", 1)[0] + ".mp4"
                return {"title": title, "path": filename}

        result = await loop.run_in_executor(None, _download)
        if result and os.path.exists(result["path"]):
            return {"success": True, **result}
        return {"success": False, "error": "لم يتم العثور على الملف بعد التحميل"}

    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        if "File is larger than max-filesize" in err:
            return {"success": False, "error": "حجم الفيديو يتجاوز 50MB المسموح به"}
        return {"success": False, "error": "فشل التحميل، تأكد من الرابط"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}

# ──────────────────────────────────────────
#  التحقق من الاشتراك الإجباري
# ──────────────────────────────────────────
async def check_subscription(context: ContextTypes.DEFAULT_TYPE, user_id: int, channels: list) -> dict:
    if not channels:
        return {"ok": True, "missing": []}
    missing = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=ch["id"], user_id=user_id)
            if member.status in ("left", "kicked", "restricted"):
                missing.append(ch)
        except TelegramError:
            missing.append(ch)
    return {"ok": len(missing) == 0, "missing": missing}

def build_subscribe_keyboard(missing: list) -> InlineKeyboardMarkup:
    buttons = []
    for ch in missing:
        link = ch.get("link") or f"https://t.me/{str(ch['id']).replace('-100', '')}"
        buttons.append([InlineKeyboardButton(f"📢 {ch.get('title', ch['id'])}", url=link)])
    buttons.append([InlineKeyboardButton("✅ لقد اشتركت", callback_data="check_sub")])
    return InlineKeyboardMarkup(buttons)

# ──────────────────────────────────────────
#  لوحة تحكم المالك
# ──────────────────────────────────────────
def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ تعديل رسالة الترحيب",        callback_data="admin_edit_start")],
        [InlineKeyboardButton("➕ إضافة قناة/مجموعة",           callback_data="admin_add_channel")],
        [InlineKeyboardButton("➕➕ إضافة عدة قنوات دفعة واحدة", callback_data="admin_add_multi")],
        [InlineKeyboardButton("📋 القنوات والمجموعات المضافة",  callback_data="admin_list_channels")],
        [InlineKeyboardButton("📢 إذاعة لكل المستخدمين",        callback_data="admin_broadcast")],
    ])

# ──────────────────────────────────────────
#  حل آيدي/رابط القناة
# ──────────────────────────────────────────
async def resolve_channel(context: ContextTypes.DEFAULT_TYPE, raw: str) -> dict:
    chat_id = raw.strip()
    if chat_id.startswith("https://t.me/"):
        chat_id = "@" + chat_id.replace("https://t.me/", "").split("/")[0]
    elif chat_id.startswith("t.me/"):
        chat_id = "@" + chat_id.replace("t.me/", "").split("/")[0]
    try:
        chat_id_val = int(chat_id)
    except ValueError:
        chat_id_val = chat_id
    try:
        chat = await context.bot.get_chat(chat_id=chat_id_val)
        link = None
        try:
            link = await context.bot.export_chat_invite_link(chat_id_val)
        except Exception:
            if chat.username:
                link = f"https://t.me/{chat.username}"
        return {
            "success": True,
            "id": chat.id,
            "title": chat.title or chat.username or str(chat.id),
            "link": link,
            "username": chat.username,
        }
    except TelegramError as e:
        return {"success": False, "error": str(e)}

# ──────────────────────────────────────────
#  /start
# ──────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = load_db()
    register_user(db, user.id, user.username or user.first_name or "")
    clear_state(db, user.id)
    await update.message.reply_text(db["start_message"])

# ──────────────────────────────────────────
#  /admin
# ──────────────────────────────────────────
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("❌ هذا الأمر متاح للمالك فقط.")
        return
    db = load_db()
    await update.message.reply_text(
        f"⚙️ <b>لوحة التحكم</b>\n\n"
        f"👥 المستخدمين: <b>{len(db['users'])}</b>\n"
        f"📢 القنوات المضافة: <b>{len(db['channels'])}</b>",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard()
    )

# ──────────────────────────────────────────
#  هاندلر الرسائل
# ──────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    text  = update.message.text or ""
    db    = load_db()
    register_user(db, user.id, user.username or user.first_name or "")
    state = get_state(db, user.id)

    # ── رسالة الترحيب ──
    if state and state["type"] == "waiting_start_msg":
        db["start_message"] = text
        save_db(db)
        clear_state(db, user.id)
        await update.message.reply_text("✅ تم تحديث رسالة الترحيب بنجاح!")
        return

    # ── قناة واحدة ──
    if state and state["type"] == "waiting_channel":
        result = await resolve_channel(context, text)
        if not result["success"]:
            await update.message.reply_text(
                f"❌ فشل: {result['error']}\n\nتأكد من:\n"
                "• البوت مضاف كأدمن في القناة/المجموعة\n"
                "• الرابط أو الآيدي صحيح"
            )
            return
        channels = db["channels"]
        if any(c["id"] == result["id"] for c in channels):
            await update.message.reply_text("⚠️ هذه القناة/المجموعة مضافة مسبقاً.")
            clear_state(db, user.id)
            return
        channels.append({
            "id": result["id"], "title": result["title"],
            "link": result["link"], "username": result["username"],
        })
        db["channels"] = channels
        save_db(db)
        clear_state(db, user.id)
        await update.message.reply_text(
            f"✅ تمت إضافة: <b>{result['title']}</b>", parse_mode="HTML"
        )
        return

    # ── عدة قنوات ──
    if state and state["type"] == "waiting_multi_channels":
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        channels = db["channels"]
        added = failed = duplicate = 0
        for line in lines:
            result = await resolve_channel(context, line)
            if not result["success"]:
                failed += 1
                continue
            if any(c["id"] == result["id"] for c in channels):
                duplicate += 1
                continue
            channels.append({
                "id": result["id"], "title": result["title"],
                "link": result["link"], "username": result["username"],
            })
            added += 1
        db["channels"] = channels
        save_db(db)
        clear_state(db, user.id)
        await update.message.reply_text(
            f"✅ <b>نتائج الإضافة:</b>\n\n"
            f"✔️ تمت إضافة: {added}\n"
            f"⚠️ مكررة: {duplicate}\n"
            f"❌ فشل: {failed}",
            parse_mode="HTML"
        )
        return

    # ── إذاعة ──
    if state and state["type"] == "waiting_broadcast":
        clear_state(db, user.id)
        users = get_all_users(db)
        sent = failed = 0
        progress = await update.message.reply_text(f"📢 جاري الإذاعة لـ {len(users)} مستخدم...")
        for u in users:
            try:
                await context.bot.send_message(chat_id=u["id"], text=text, parse_mode="HTML")
                sent += 1
            except TelegramError:
                failed += 1
            await asyncio.sleep(0.05)
        await progress.edit_text(
            f"✅ <b>انتهت الإذاعة</b>\n\n✔️ وصلت: {sent}\n❌ فشلت: {failed}",
            parse_mode="HTML"
        )
        return

    # ── رابط الفيديو ──
    url = extract_url(text)
    if url:
        sub = await check_subscription(context, user.id, db["channels"])
        if not sub["ok"]:
            await update.message.reply_text(
                "⚠️ يجب عليك الاشتراك في القنوات التالية أولاً:",
                reply_markup=build_subscribe_keyboard(sub["missing"])
            )
            return

        if is_youtube(url):
            await update.message.reply_text("❌ عذراً، يوتيوب غير مدعوم.")
            return

        processing = await update.message.reply_text("⏳ جاري تحميل الفيديو...")
        result = await download_video(url)

        if not result["success"]:
            await processing.edit_text(f"❌ فشل التحميل: {result['error']}")
            return

        file_path = result["path"]
        title     = result["title"]

        try:
            await processing.edit_text("📤 جاري الإرسال...")
            with open(file_path, "rb") as vf:
                await update.message.reply_video(
                    video=InputFile(vf, filename=f"{title}.mp4"),
                    caption=f"🎬 <b>{title}</b>",
                    parse_mode="HTML",
                    supports_streaming=True,
                )
            await processing.delete()
        except TelegramError:
            try:
                with open(file_path, "rb") as df:
                    await update.message.reply_document(
                        document=InputFile(df, filename=f"{title}.mp4"),
                        caption=f"🎬 <b>{title}</b>",
                        parse_mode="HTML",
                    )
                await processing.delete()
            except TelegramError as e:
                await processing.edit_text(f"❌ فشل الإرسال: {str(e)[:200]}")
        finally:
            try:
                os.remove(file_path)
            except Exception:
                pass
        return

    await update.message.reply_text(
        "أرسل لي رابط فيديو من أي موقع (عدا يوتيوب) وسأحمله لك! 🎬"
    )

# ──────────────────────────────────────────
#  هاندلر الأزرار
# ──────────────────────────────────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user  = query.from_user
    data  = query.data
    db    = load_db()

    await query.answer()

    if data == "check_sub":
        sub = await check_subscription(context, user.id, db["channels"])
        if sub["ok"]:
            await query.edit_message_text("✅ شكراً! يمكنك الآن إرسال روابط الفيديوهات 🎬")
        else:
            await query.edit_message_text(
                "❌ لم تشترك في جميع القنوات بعد. يرجى الاشتراك ثم المحاولة.",
                reply_markup=build_subscribe_keyboard(sub["missing"])
            )
        return

    if user.id != OWNER_ID:
        return

    if data == "admin_edit_start":
        set_state(db, user.id, {"type": "waiting_start_msg"})
        await query.edit_message_text("✏️ أرسل الآن رسالة الترحيب الجديدة:")
        return

    if data == "admin_add_channel":
        set_state(db, user.id, {"type": "waiting_channel"})
        await query.edit_message_text(
            "📢 أرسل آيدي القناة/المجموعة أو رابطها:\n\n"
            "مثال:\n• @mychannel\n• -1001234567890\n• https://t.me/mychannel\n\n"
            "⚠️ تأكد أن البوت مضاف كأدمن في القناة/المجموعة."
        )
        return

    if data == "admin_add_multi":
        set_state(db, user.id, {"type": "waiting_multi_channels"})
        await query.edit_message_text(
            "📋 أرسل الآيديات أو الروابط سطراً بسطر:\n\n"
            "مثال:\n@channel1\n@channel2\n-1001234567890\nhttps://t.me/channel3\n\n"
            "⚠️ تأكد أن البوت مضاف كأدمن في جميع القنوات/المجموعات."
        )
        return

    if data == "admin_list_channels":
        channels = db["channels"]
        if not channels:
            await query.edit_message_text(
                "📋 لا توجد قنوات أو مجموعات مضافة.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")
                ]])
            )
            return
        text = "📋 <b>القنوات والمجموعات المضافة:</b>\n\n"
        buttons = []
        for i, ch in enumerate(channels):
            text += f"{i+1}. <b>{ch['title']}</b> (<code>{ch['id']}</code>)\n"
            buttons.append([InlineKeyboardButton(
                f"🗑 حذف: {ch['title']}", callback_data=f"del_ch:{ch['id']}"
            )])
        buttons.append([InlineKeyboardButton("🗑🗑 حذف كل القنوات والمجموعات", callback_data="del_all_channels")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("del_ch:"):
        ch_id_raw = data.replace("del_ch:", "")
        try:
            ch_id = int(ch_id_raw)
        except ValueError:
            ch_id = ch_id_raw
        channels = db["channels"]
        ch = next((c for c in channels if c["id"] == ch_id), None)
        db["channels"] = [c for c in channels if c["id"] != ch_id]
        save_db(db)
        await query.edit_message_text(
            f"✅ تم حذف: <b>{ch['title'] if ch else ch_id}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="admin_list_channels")
            ]])
        )
        return

    if data == "del_all_channels":
        db["channels"] = []
        save_db(db)
        await query.edit_message_text(
            "✅ تم حذف جميع القنوات والمجموعات.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")
            ]])
        )
        return

    if data == "admin_broadcast":
        set_state(db, user.id, {"type": "waiting_broadcast"})
        await query.edit_message_text(
            f"📢 أرسل الرسالة التي تريد إذاعتها لجميع المستخدمين ({len(db['users'])} مستخدم):"
        )
        return

    if data == "admin_back":
        await query.edit_message_text(
            f"⚙️ <b>لوحة التحكم</b>\n\n"
            f"👥 المستخدمين: <b>{len(db['users'])}</b>\n"
            f"📢 القنوات المضافة: <b>{len(db['channels'])}</b>",
            parse_mode="HTML",
            reply_markup=admin_main_keyboard()
        )
        return

# ──────────────────────────────────────────
#  تشغيل البوت
# ──────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("✅ البوت يعمل...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
