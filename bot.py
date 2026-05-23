import os
import uuid
import requests
import razorpay

from datetime import datetime, timedelta
from threading import Thread

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from flask import Flask, request, jsonify, redirect

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")

MONGO_URI = os.getenv("MONGO_URI")

BASE_URL = os.getenv("BASE_URL")

TERABOX_API_URL = os.getenv("TERABOX_API_URL")
TERABOX_API_KEY = os.getenv("TERABOX_API_KEY")

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

FREE_LIMIT = 5

REFERRAL_REWARD = 1

# ================= PRIME PLANS =================

PLANS = {
    "1month": {
        "price": 50,
        "days": 30,
        "name": "1 MONTH"
    },

    "2month": {
        "price": 100,
        "days": 60,
        "name": "2 MONTH"
    },

    "3month": {
        "price": 250,
        "days": 90,
        "name": "3 MONTH"
    }
}

# ================= SETUP =================

bot = telebot.TeleBot(BOT_TOKEN)

app = Flask(__name__)

mongo = MongoClient(MONGO_URI)

db = mongo["terabox_prime_bot"]

users_col = db["users"]
links_col = db["links"]
orders_col = db["orders"]

razorpay_client = razorpay.Client(
    auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
)

# ================= FUNCTIONS =================

def get_user(user, ref_by=None):

    data = users_col.find_one({"user_id": user.id})

    if not data:

        data = {
            "user_id": user.id,
            "username": user.username,
            "name": user.first_name,
            "free_used": 0,
            "referral_bonus": 0,
            "referred_by": None,
            "is_prime": False,
            "prime_expiry": None,
            "created_at": datetime.utcnow()
        }

        # only one time referral
        if (
            ref_by
            and ref_by != user.id
        ):

            already = users_col.find_one({
                "user_id": user.id
            })

            if not already:

                data["referred_by"] = ref_by

                users_col.update_one(
                    {"user_id": ref_by},
                    {"$inc": {"referral_bonus": REFERRAL_REWARD}}
                )

        users_col.insert_one(data)

    return data


def prime_active(data):

    if not data.get("is_prime"):
        return False

    expiry = data.get("prime_expiry")

    if not expiry:
        return False

    return expiry > datetime.utcnow()


def valid_terabox(url):

    text = url.lower()

    return (
        "terabox" in text
        or "1024tera" in text
        or "terafileshare" in text
    )


def call_api(url):

    headers = {
        "Authorization": f"Bearer {TERABOX_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "url": url
    }

    r = requests.post(
        TERABOX_API_URL,
        json=payload,
        headers=headers,
        timeout=40
    )

    r.raise_for_status()

    data = r.json()

    play_url = (
        data.get("play_url")
        or data.get("stream_url")
        or data.get("url")
    )

    if not play_url:
        raise Exception("play_url missing")

    return {
        "title": data.get("title", "TeraBox Video"),
        "play_url": play_url
    }

# ================= START =================

@bot.message_handler(commands=["start"])
def start(msg):

    parts = msg.text.split()

    ref_by = None

    if len(parts) > 1:

        try:
            ref_by = int(parts[1])
        except:
            pass

    user = get_user(msg.from_user, ref_by)

    bot_username = bot.get_me().username

    ref_link = f"https://t.me/{bot_username}?start={msg.from_user.id}"

    total_bonus = user.get("referral_bonus", 0)

    if prime_active(user):

        plan = f"💎 PRIME ACTIVE"

    else:

        plan = (
            f"🎁 FREE USE : "
            f"{user.get('free_used', 0)}/"
            f"{FREE_LIMIT + total_bonus}"
        )

    text = f"""
🔥 𝗧𝗘𝗥𝗔𝗕𝗢𝗫 𝗦𝗧𝗥𝗘𝗔𝗠 𝗕𝗢𝗧 🔥

🎬 TeraBox link paste karo
⚡ Direct video player pao

━━━━━━━━━━━━━━━

{plan}

👥 REFERRAL BONUS : +{total_bonus}

━━━━━━━━━━━━━━━

🔗 YOUR REFERRAL LINK :

{ref_link}

━━━━━━━━━━━━━━━

📌 1 Referral = 1 Extra Link

━━━━━━━━━━━━━━━

💎 PRIME PLANS

💰 ₹50  → 1 MONTH
💰 ₹100 → 2 MONTH
💰 ₹250 → 3 MONTH

━━━━━━━━━━━━━━━

📌 COMMANDS

/prime - Buy Prime
/me - My Account

━━━━━━━━━━━━━━━
"""

    bot.reply_to(msg, text)

# ================= ACCOUNT =================

@bot.message_handler(commands=["me"])
def me(msg):

    user = get_user(msg.from_user)

    total_bonus = user.get("referral_bonus", 0)

    total_limit = FREE_LIMIT + total_bonus

    if prime_active(user):

        expiry = user["prime_expiry"].strftime("%d-%m-%Y")

        text = f"""
💎 𝗣𝗥𝗜𝗠𝗘 𝗔𝗖𝗧𝗜𝗩𝗘

📆 Expiry : {expiry}

━━━━━━━━━━━━━━━
"""

    else:

        text = f"""
🎁 FREE ACCOUNT

⚡ Used : {user.get('free_used', 0)}/{total_limit}

👥 Referral Bonus : +{total_bonus}

━━━━━━━━━━━━━━━

💎 ₹50  → 1 MONTH
💎 ₹100 → 2 MONTH
💎 ₹250 → 3 MONTH

━━━━━━━━━━━━━━━
"""

    bot.reply_to(msg, text)

# ================= PRIME MENU =================

@bot.message_handler(commands=["prime"])
def prime(msg):

    kb = InlineKeyboardMarkup(row_width=1)

    kb.add(
        InlineKeyboardButton(
            "💎 1 MONTH - ₹50",
            callback_data="buy_1month"
        ),

        InlineKeyboardButton(
            "💎 2 MONTH - ₹100",
            callback_data="buy_2month"
        ),

        InlineKeyboardButton(
            "💎 3 MONTH - ₹250",
            callback_data="buy_3month"
        )
    )

    text = f"""
💎 𝗣𝗥𝗜𝗠𝗘 𝗣𝗟𝗔𝗡𝗦

━━━━━━━━━━━━━━━

💰 ₹50  →  1 MONTH
💰 ₹100 →  2 MONTH
💰 ₹250 →  3 MONTH

━━━━━━━━━━━━━━━

👇 CHOOSE YOUR PLAN 👇
"""

    bot.reply_to(
        msg,
        text,
        reply_markup=kb
    )

# ================= BUY PLAN =================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith("buy_")
)
def buy_plan(call):

    bot.answer_callback_query(call.id)

    plan_key = call.data.replace("buy_", "")

    plan = PLANS.get(plan_key)

    if not plan:
        return

    order_id = str(uuid.uuid4())[:10]

    razorpay_order = razorpay_client.order.create({
        "amount": plan["price"] * 100,
        "currency": "INR",
        "receipt": order_id,
        "payment_capture": 1
    })

    pay_link = f"https://rzp.io/l/{razorpay_order['id']}"

    orders_col.insert_one({
        "order_id": order_id,
        "razorpay_order_id": razorpay_order["id"],
        "user_id": call.from_user.id,
        "plan": plan_key,
        "days": plan["days"],
        "status": "pending",
        "created_at": datetime.utcnow()
    })

    kb = InlineKeyboardMarkup()

    kb.add(
        InlineKeyboardButton(
            f"💳 PAY ₹{plan['price']}",
            url=pay_link
        )
    )

    bot.send_message(
        call.message.chat.id,
        f"""
💎 𝗣𝗥𝗜𝗠𝗘 𝗣𝗟𝗔𝗡

📦 PLAN : {plan['name']}
💰 PRICE : ₹{plan['price']}
📆 VALIDITY : {plan['days']} DAYS

━━━━━━━━━━━━━━━

👇 CLICK BELOW 👇
""",
        reply_markup=kb
    )

# ================= HANDLE LINK =================

@bot.message_handler(func=lambda m: True)
def handle_link(msg):

    text = msg.text.strip()

    user = get_user(msg.from_user)

    if not valid_terabox(text):

        return bot.reply_to(
            msg,
            "❌ Valid TeraBox link bhejo."
        )

    total_limit = FREE_LIMIT + user.get("referral_bonus", 0)

    if (
        not prime_active(user)
        and user.get("free_used", 0) >= total_limit
    ):

        kb = InlineKeyboardMarkup()

        kb.add(
            InlineKeyboardButton(
                "💎 BUY PRIME",
                callback_data="buy_1month"
            )
        )

        return bot.reply_to(
            msg,
            f"""
⚠️ FREE LIMIT COMPLETE

🎁 LIMIT : {total_limit}/{total_limit}

💎 PRIME REQUIRED
""",
            reply_markup=kb
        )

    wait = bot.reply_to(
        msg,
        "⏳ Video processing..."
    )

    try:

        api_data = call_api(text)

        code = str(uuid.uuid4())[:8]

        watch_url = f"{BASE_URL}/watch/{code}"

        links_col.insert_one({
            "code": code,
            "user_id": msg.from_user.id,
            "play_url": api_data["play_url"],
            "created_at": datetime.utcnow()
        })

        if not prime_active(user):

            users_col.update_one(
                {"user_id": msg.from_user.id},
                {"$inc": {"free_used": 1}}
            )

        kb = InlineKeyboardMarkup()

        kb.add(
            InlineKeyboardButton(
                "▶️ PLAY VIDEO",
                url=watch_url
            )
        )

        bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=wait.message_id,
            text=f"""
✅ 𝗩𝗜𝗗𝗘𝗢 𝗥𝗘𝗔𝗗𝗬

🎬 {api_data['title']}

━━━━━━━━━━━━━━━

⚡ FAST STREAM PLAYER
""",
            reply_markup=kb
        )

    except Exception as e:

        bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=wait.message_id,
            text=f"❌ ERROR\n\n{e}"
        )

# ================= WEBHOOK =================

@app.route("/razorpay-webhook", methods=["POST"])
def webhook():

    payload = request.json

    try:

        event = payload.get("event")

        if event == "payment.captured":

            payment = payload["payload"]["payment"]["entity"]

            razorpay_order_id = payment["order_id"]

            order = orders_col.find_one({
                "razorpay_order_id": razorpay_order_id
            })

            if order:

                expiry = datetime.utcnow() + timedelta(days=order["days"])

                users_col.update_one(
                    {"user_id": order["user_id"]},
                    {
                        "$set": {
                            "is_prime": True,
                            "prime_expiry": expiry
                        }
                    }
                )

                orders_col.update_one(
                    {"_id": order["_id"]},
                    {
                        "$set": {
                            "status": "paid"
                        }
                    }
                )

                bot.send_message(
                    order["user_id"],
                    f"""
🎉 𝗣𝗔𝗬𝗠𝗘𝗡𝗧 𝗦𝗨𝗖𝗖𝗘𝗦𝗦

💎 PRIME ACTIVATED
📆 VALID : {order['days']} DAYS

━━━━━━━━━━━━━━━

🔥 Enjoy Unlimited Streaming
"""
                )

        return jsonify({"success": True})

    except Exception as e:

        print(e)

        return jsonify({
            "success": False
        })

# ================= WATCH =================

@app.route("/watch/<code>")
def watch(code):

    item = links_col.find_one({"code": code})

    if not item:
        return "Video not found"

    return redirect(item["play_url"])

# ================= HOME =================

@app.route("/")
def home():

    return "Bot Running ✅"

# ================= RUN =================

def run_web():

    port = int(os.getenv("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
    )

Thread(target=run_web).start()

print("BOT RUNNING...")

bot.infinity_polling(skip_pending=True)
