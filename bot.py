import os, uuid, requests, razorpay
from datetime import datetime, timedelta
from threading import Thread

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from flask import Flask, request, jsonify, redirect

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
BASE_URL = os.getenv("BASE_URL")

TERABOX_API_URL = os.getenv("TERABOX_API_URL")
TERABOX_API_KEY = os.getenv("TERABOX_API_KEY")

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

FREE_LIMIT = 5
REFERRAL_REWARD = 1

PLANS = {
    "1month": {"price": 50, "days": 30, "name": "1 MONTH"},
    "2month": {"price": 100, "days": 60, "name": "2 MONTH"},
    "3month": {"price": 250, "days": 90, "name": "3 MONTH"},
}

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

mongo = MongoClient(MONGO_URI)
db = mongo["terabox_prime_bot"]

users_col = db["users"]
links_col = db["links"]
orders_col = db["orders"]

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


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

        if ref_by and ref_by != user.id:
            data["referred_by"] = ref_by
            users_col.update_one(
                {"user_id": ref_by},
                {"$inc": {"referral_bonus": REFERRAL_REWARD}},
                upsert=True
            )

        users_col.insert_one(data)

    return data


def prime_active(data):
    expiry = data.get("prime_expiry")
    return bool(data.get("is_prime") and expiry and expiry > datetime.utcnow())


def valid_terabox(url):
    text = url.lower()
    return (
        "terabox" in text
        or "1024tera" in text
        or "terafileshare" in text
        or "terasharefile" in text
    )


def call_api(url):
    headers = {
        "Authorization": f"Bearer {TERABOX_API_KEY}",
        "Content-Type": "application/json"
    }

    r = requests.post(
        TERABOX_API_URL,
        json={"url": url},
        headers=headers,
        timeout=60
    )

    r.raise_for_status()
    data = r.json()

    play_url = (
        data.get("play_url")
        or data.get("stream_url")
        or data.get("direct_url")
        or data.get("video_url")
        or data.get("url")
    )

    if not play_url:
        raise Exception(f"play_url missing: {data}")

    return {
        "title": data.get("title", "TeraBox Video"),
        "play_url": play_url,
        "thumbnail": data.get("thumbnail", "")
    }


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

    total_limit = FREE_LIMIT + user.get("referral_bonus", 0)

    text = f"""
🔥 𝗧𝗘𝗥𝗔𝗕𝗢𝗫 𝗧𝗢 𝗩𝗜𝗗𝗘𝗢 𝗕𝗢𝗧 🔥

🎬 TeraBox link भेजो
▶️ Bot में ही video play होगा

━━━━━━━━━━━━━━━

🎁 Free Used: {user.get("free_used", 0)}/{total_limit}
👥 Referral Bonus: +{user.get("referral_bonus", 0)}

━━━━━━━━━━━━━━━

🔗 Your Referral Link:
{ref_link}

📌 1 Referral = 1 Extra Link

━━━━━━━━━━━━━━━

💎 Prime Plans:
₹50  → 1 Month
₹100 → 2 Month
₹250 → 3 Month

/prime - Buy Prime
/me - My Account
/help - Help
"""
    bot.reply_to(msg, text)


@bot.message_handler(commands=["help"])
def help_cmd(msg):
    bot.reply_to(
        msg,
        """
📌 HOW TO USE

1️⃣ TeraBox link भेजो
2️⃣ Bot video process करेगा
3️⃣ Video bot में play होगा
4️⃣ Free limit के बाद Prime लेना होगा

/prime - Prime Plans
/me - Account
"""
    )


@bot.message_handler(commands=["me"])
def me(msg):
    user = get_user(msg.from_user)
    total_limit = FREE_LIMIT + user.get("referral_bonus", 0)

    if prime_active(user):
        text = f"💎 Prime Active\n📆 Expiry: {user['prime_expiry'].strftime('%d-%m-%Y')}"
    else:
        text = f"🎁 Free Used: {user.get('free_used', 0)}/{total_limit}\n👥 Referral Bonus: +{user.get('referral_bonus', 0)}"

    bot.reply_to(msg, text)


@bot.message_handler(commands=["prime"])
def prime(msg):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("💎 1 MONTH - ₹50", callback_data="buy_1month"),
        InlineKeyboardButton("💎 2 MONTH - ₹100", callback_data="buy_2month"),
        InlineKeyboardButton("💎 3 MONTH - ₹250", callback_data="buy_3month")
    )

    bot.reply_to(
        msg,
        """
💎 𝗣𝗥𝗜𝗠𝗘 𝗣𝗟𝗔𝗡𝗦

₹50  → 1 MONTH
₹100 → 2 MONTH
₹250 → 3 MONTH

👇 Plan choose karo
""",
        reply_markup=kb
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_"))
def buy_plan(call):
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

    orders_col.insert_one({
        "order_id": order_id,
        "razorpay_order_id": razorpay_order["id"],
        "user_id": call.from_user.id,
        "plan": plan_key,
        "days": plan["days"],
        "status": "pending",
        "created_at": datetime.utcnow()
    })

    pay_url = f"https://checkout.razorpay.com/v1/checkout/embedded?order_id={razorpay_order['id']}"

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(f"💳 PAY ₹{plan['price']}", url=pay_url))

    bot.send_message(
        call.message.chat.id,
        f"""
💎 𝗣𝗥𝗜𝗠𝗘 𝗣𝗟𝗔𝗡

📦 Plan: {plan['name']}
💰 Price: ₹{plan['price']}
📆 Validity: {plan['days']} days
""",
        reply_markup=kb
    )


@bot.message_handler(func=lambda m: m.text and not m.text.startswith("/"))
def handle_link(msg):
    text = msg.text.strip()
    user = get_user(msg.from_user)

    if not valid_terabox(text):
        return bot.reply_to(msg, "❌ Valid TeraBox link bhejo.")

    total_limit = FREE_LIMIT + user.get("referral_bonus", 0)

    if not prime_active(user) and user.get("free_used", 0) >= total_limit:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("💎 BUY PRIME", callback_data="buy_1month"))

        return bot.reply_to(
            msg,
            f"⚠️ Free limit complete\n\n🎁 Used: {total_limit}/{total_limit}\n💎 Prime required",
            reply_markup=kb
        )

    wait = bot.reply_to(msg, "⏳ Video processing...")

    try:
        api_data = call_api(text)

        code = str(uuid.uuid4())[:8]
        watch_url = f"{BASE_URL}/watch/{code}"

        links_col.insert_one({
            "code": code,
            "user_id": msg.from_user.id,
            "title": api_data["title"],
            "play_url": api_data["play_url"],
            "created_at": datetime.utcnow()
        })

        if not prime_active(user):
            users_col.update_one(
                {"user_id": msg.from_user.id},
                {"$inc": {"free_used": 1}}
            )

        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("▶️ PLAY IN BOT", url=watch_url))

        bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=wait.message_id,
            text=f"✅ Video Ready!\n\n🎬 {api_data['title']}",
            reply_markup=kb
        )

        try:
            bot.send_video(
                msg.chat.id,
                api_data["play_url"],
                caption=f"🎬 {api_data['title']}"
            )
        except:
            bot.send_message(
                msg.chat.id,
                "⚠️ Telegram direct video play nahi kar paya.\nNeeche button se play karo.",
                reply_markup=kb
            )

    except Exception as e:
        bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=wait.message_id,
            text=f"❌ ERROR\n\n{e}"
        )


@app.route("/razorpay-webhook", methods=["POST"])
def webhook():
    payload = request.json

    try:
        if payload.get("event") == "payment.captured":
            payment = payload["payload"]["payment"]["entity"]
            razorpay_order_id = payment["order_id"]

            order = orders_col.find_one({"razorpay_order_id": razorpay_order_id})

            if order and order.get("status") != "paid":
                expiry = datetime.utcnow() + timedelta(days=order["days"])

                users_col.update_one(
                    {"user_id": order["user_id"]},
                    {
                        "$set": {
                            "is_prime": True,
                            "prime_expiry": expiry
                        }
                    },
                    upsert=True
                )

                orders_col.update_one(
                    {"_id": order["_id"]},
                    {"$set": {"status": "paid"}}
                )

                bot.send_message(
                    order["user_id"],
                    f"🎉 Payment Success!\n\n💎 Prime Activated\n📆 Valid: {order['days']} days"
                )

        return jsonify({"success": True})

    except Exception as e:
        print(e)
        return jsonify({"success": False})


@app.route("/watch/<code>")
def watch(code):
    item = links_col.find_one({"code": code})

    if not item:
        return "Video not found", 404

    video_url = item["play_url"]
    title = item.get("title", "TeraBox Video")

    return f"""
<!DOCTYPE html>
<html>
<head>
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body {{
    margin:0;
    background:#050505;
    color:white;
    font-family:Arial;
}}
.box {{
    padding:15px;
}}
video {{
    width:100%;
    height:auto;
    background:#000;
    border-radius:12px;
}}
h2 {{
    font-size:20px;
}}
</style>
</head>
<body>
<div class="box">
<h2>🎬 {title}</h2>
<video controls autoplay playsinline>
    <source src="{video_url}">
</video>
</div>
</body>
</html>
"""


@app.route("/")
def home():
    return "Bot Running ✅"


def run_web():
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


Thread(target=run_web).start()

print("BOT RUNNING...")
bot.infinity_polling(skip_pending=True)
