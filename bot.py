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
    t = url.lower()
    return (
        "terabox" in t
        or "1024tera" in t
        or "terafileshare" in t
        or "terasharefile" in t
    )


def find_video_url(data):
    if isinstance(data, dict):
        for key in ["play_url", "stream_url", "direct_url", "video_url", "download_url", "url", "link"]:
            val = data.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val

        for key in ["data", "result", "file", "video"]:
            val = data.get(key)
            found = find_video_url(val)
            if found:
                return found

    if isinstance(data, list):
        for item in data:
            found = find_video_url(item)
            if found:
                return found

    return None


def call_api(url):
    headers = {
        "Authorization": f"Bearer {TERABOX_API_KEY}",
        "X-API-Key": TERABOX_API_KEY,
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json"
    }

    try:
        attempts = [
            lambda: requests.post(
                TERABOX_API_URL,
                json={"url": url, "link": url, "api_key": TERABOX_API_KEY, "key": TERABOX_API_KEY},
                headers=headers,
                timeout=25
            ),
            lambda: requests.post(
                TERABOX_API_URL,
                data={"url": url, "link": url, "api_key": TERABOX_API_KEY, "key": TERABOX_API_KEY},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=25
            ),
            lambda: requests.get(
                TERABOX_API_URL,
                params={"url": url, "link": url, "api_key": TERABOX_API_KEY, "key": TERABOX_API_KEY},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=25
            )
        ]

        for fn in attempts:
            try:
                r = fn()
                if r.status_code >= 400:
                    continue

                data = r.json()
                play_url = find_video_url(data)

                if play_url:
                    title = "TeraBox Video"
                    if isinstance(data, dict):
                        title = data.get("title") or data.get("name") or data.get("filename") or title

                    return {
                        "title": title,
                        "play_url": play_url,
                        "mode": "api"
                    }

            except:
                continue

    except:
        pass

    return {
        "title": "Open on TeraBox",
        "play_url": url,
        "mode": "site"
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
    total_limit = FREE_LIMIT + user.get("referral_bonus", 0)
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start={msg.from_user.id}"

    bot.reply_to(msg, f"""
🔥 𝗧𝗘𝗥𝗔𝗕𝗢𝗫 𝗧𝗢 𝗩𝗜𝗗𝗘𝗢 𝗕𝗢𝗧 🔥

🎬 TeraBox link bhejo
▶️ Video open link milega

🎁 Free Used: {user.get("free_used", 0)}/{total_limit}
👥 Referral Bonus: +{user.get("referral_bonus", 0)}

🔗 Referral Link:
{ref_link}

📌 1 Referral = 1 Extra Link

/prime - Buy Prime
/me - My Account
/help - Help
/debug - Bot Check
/apitest LINK - API Test
""")


@bot.message_handler(commands=["help"])
def help_cmd(msg):
    bot.reply_to(msg, """
📌 HOW TO USE

1️⃣ TeraBox link bhejo
2️⃣ Bot process karega
3️⃣ Play button par click karo

⚠️ Agar API fail ho, original TeraBox site open hogi.

💎 Prime:
/prime
""")


@bot.message_handler(commands=["debug"])
def debug(msg):
    bot.reply_to(
        msg,
        f"✅ Bot alive\n\nBASE_URL={BASE_URL}\nAPI_URL={TERABOX_API_URL}"
    )


@bot.message_handler(commands=["apitest"])
def apitest(msg):
    parts = msg.text.split(maxsplit=1)

    if len(parts) < 2:
        return bot.reply_to(msg, "Use: /apitest TERABOX_LINK")

    wait = bot.reply_to(msg, "⏳ API testing...")

    try:
        api_data = call_api(parts[1])

        bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=wait.message_id,
            text=f"""
✅ API TEST RESULT

Mode: {api_data['mode']}
Title: {api_data['title']}

URL:
{api_data['play_url'][:500]}
"""
        )

    except Exception as e:
        bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=wait.message_id,
            text=f"❌ API TEST FAILED\n\n{str(e)[:1000]}"
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

    bot.reply_to(msg, """
💎 𝗣𝗥𝗜𝗠𝗘 𝗣𝗟𝗔𝗡𝗦

₹50  → 1 MONTH
₹100 → 2 MONTH
₹250 → 3 MONTH
""", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_"))
def buy_plan(call):
    plan_key = call.data.replace("buy_", "")
    plan = PLANS.get(plan_key)

    if not plan:
        return

    receipt_id = str(uuid.uuid4())[:10]

    rz_order = razorpay_client.order.create({
        "amount": plan["price"] * 100,
        "currency": "INR",
        "receipt": receipt_id,
        "payment_capture": 1
    })

    orders_col.insert_one({
        "receipt_id": receipt_id,
        "razorpay_order_id": rz_order["id"],
        "user_id": call.from_user.id,
        "plan": plan_key,
        "days": plan["days"],
        "price": plan["price"],
        "status": "pending",
        "created_at": datetime.utcnow()
    })

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(f"💳 PAY ₹{plan['price']}", url=f"{BASE_URL}/pay/{rz_order['id']}"))

    bot.send_message(call.message.chat.id, f"""
💎 𝗣𝗥𝗜𝗠𝗘 𝗣𝗟𝗔𝗡

📦 Plan: {plan['name']}
💰 Price: ₹{plan['price']}
📆 Validity: {plan['days']} days
""", reply_markup=kb)


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
        return bot.reply_to(msg, "⚠️ Free limit complete\n\n💎 Prime required", reply_markup=kb)

    wait = bot.reply_to(msg, "⏳ Processing...")

    try:
        api_data = call_api(text)

        code = str(uuid.uuid4())[:8]
        watch_url = f"{BASE_URL}/watch/{code}"

        links_col.insert_one({
            "code": code,
            "user_id": msg.from_user.id,
            "title": api_data["title"],
            "play_url": api_data["play_url"],
            "mode": api_data["mode"],
            "created_at": datetime.utcnow()
        })

        if not prime_active(user):
            users_col.update_one(
                {"user_id": msg.from_user.id},
                {"$inc": {"free_used": 1}}
            )

        kb = InlineKeyboardMarkup()

        if api_data["mode"] == "api":
            kb.add(InlineKeyboardButton("▶️ PLAY VIDEO", url=watch_url))
            kb.add(InlineKeyboardButton("⬇️ DOWNLOAD / OPEN", url=api_data["play_url"]))
            msg_text = f"✅ Video Ready!\n\n🎬 {api_data['title']}"
        else:
            kb.add(InlineKeyboardButton("🌐 OPEN ON TERABOX", url=api_data["play_url"]))
            msg_text = "✅ Link Ready!\n\n⚠️ API direct stream nahi de rahi, isliye site par open hoga."

        bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=wait.message_id,
            text=msg_text,
            reply_markup=kb
        )

    except Exception as e:
        bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=wait.message_id,
            text=f"❌ ERROR\n\n{str(e)[:1000]}"
        )


@app.route("/pay/<razorpay_order_id>")
def pay_page(razorpay_order_id):
    order = orders_col.find_one({"razorpay_order_id": razorpay_order_id})

    if not order:
        return "Order not found", 404

    return f"""
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
</head>
<body style="background:#050505;color:white;font-family:Arial;padding:25px;">
<h2>💎 Prime Payment</h2>
<p>Amount: ₹{order['price']}</p>
<p>Validity: {order['days']} days</p>
<button onclick="payNow()" style="padding:14px 22px;background:#7c3aed;color:white;border:0;border-radius:10px;font-size:18px;">Pay Now</button>
<script>
function payNow(){{
var options={{
"key":"{RAZORPAY_KEY_ID}",
"amount":"{order['price'] * 100}",
"currency":"INR",
"name":"TeraBox Video Bot",
"description":"Prime Membership",
"order_id":"{razorpay_order_id}",
"handler":function(response){{ alert("Payment successful. Prime will activate automatically."); window.location.href="/"; }},
"theme":{{"color":"#7c3aed"}}
}};
var rzp=new Razorpay(options);
rzp.open();
}}
</script>
</body>
</html>
"""


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
                    {"$set": {"is_prime": True, "prime_expiry": expiry}},
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

    if item.get("mode") == "site":
        return redirect(item["play_url"])

    video_url = item["play_url"]
    title = item.get("title", "TeraBox Video")

    return f"""
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
</head>
<body style="background:#000;color:white;font-family:Arial;padding:15px;">
<h2>🎬 {title}</h2>
<video id="v" controls autoplay playsinline style="width:100%;border-radius:12px;background:#111;">
<source src="{video_url}">
</video>
<p id="err" style="color:red;"></p>
<script>
const v=document.getElementById("v");
v.onerror=function(){{document.getElementById("err").innerText="Video play nahi ho raha. API direct MP4/M3U8 URL return nahi kar rahi.";}}
</script>
<br><br>
<a href="{video_url}" style="color:#00ffcc;">Open / Download</a>
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
