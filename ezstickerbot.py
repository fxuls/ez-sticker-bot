import codecs
import json
import logging
import os
import requests
import simplejson
import sys
import time
import uuid

from collections import Counter
from io import BytesIO
from PIL import Image
from requests.exceptions import InvalidURL, HTTPError, RequestException, ConnectionError, Timeout, ConnectTimeout
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent
from telegram.error import TelegramError
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, InlineQueryHandler
from urllib.parse import urlparse

# setup logger
logging.getLogger("urllib3.connection").setLevel(logging.CRITICAL)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

dir = os.path.dirname(__file__)

updater = None

config = {}
lang = {}


def start(bot, update):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    message.reply_markdown(get_message(message.chat_id, "start"))


def help_command(bot, update):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    message.reply_text(get_message(message.chat_id, "help"))


def send_stats(bot, update):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    stats_message = get_message(message.chat_id, "stats").format(config['uses'], len(config['users']))
    message.reply_markdown(stats_message)


def send_all_stats(bot, update):
    message = update.message
    user_id = message.chat_id

    # feedback to show bot is processing
    bot.send_chat_action(user_id, 'typing')

    stats_message = get_message(user_id, "stats").format(config['uses'], len(config['users'])) + "\n\n"
    stats_message += get_message(user_id, "langs_auto_set").format(config['langs_auto_set']) + "\n\n"

    opted_in = 0
    opted_out = 0
    for user in config['users'].values():
        if user['opt_in']:
            opted_in += 1
        else:
            opted_out += 1

    stats_message += get_message(user_id, "opted_count").format(opted_in + opted_out, opted_in, opted_out)

    message.reply_markdown(stats_message)


def send_lang_stats(bot, update):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')

    # get message header
    lang_stats_message = get_message(message.chat_id, "lang_stats")

    # count lang usage
    langs = [user['lang'] for user in config['users'].values()]
    lang_usage = dict(Counter(langs))

    sorted_usage = [(code, lang_usage[code]) for code in sorted(lang_usage, key=lang_usage.get, reverse=True)]

    # create stats message entries
    message_lines = {}
    for code, count in sorted_usage:
        lang_stats_message += "\n" + u"\u200E" + "{}: {:,}".format(lang[code]['lang_name'], count)

    # compile stats message in order
    for index in range(0, len(lang)):
        try:
            lang_stats_message += message_lines[str(index)]
        # Skip langs with 0 users
        except KeyError:
            continue

    # send message
    message.reply_markdown(lang_stats_message)


def main():
    get_config()

    # global config
    # config['users'] = {}
    # for user_id in config['lang_prefs']:
    #     config['users'][user_id] = {}
    #     config['users'][user_id]['lang'] = config['lang_prefs'][user_id]
    #     config['users'][user_id]['opt_in'] = True
    # del config['lang_prefs']
    # save_config()

    get_lang()
    global updater
    updater = Updater(config['token'])
    global uses
    uses = config['uses']
    dispatcher = updater.dispatcher

    # register a handler to ignore all non-private updates
    dispatcher.add_handler(MessageHandler(~ Filters.private, do_fucking_nothing))

    # register commands
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('help', help_command))
    dispatcher.add_handler(CommandHandler('stats', send_stats))
    dispatcher.add_handler(CommandHandler('langstats', send_lang_stats))
    dispatcher.add_handler(CommandHandler('restart', restart_bot))
    dispatcher.add_handler(CommandHandler('info', bot_info))
    dispatcher.add_handler(CommandHandler('lang', change_lang_command))
    dispatcher.add_handler(CommandHandler('broadcast', broadcast_command))
    dispatcher.add_handler(CommandHandler(['optin', 'optout'], opt_command))
    dispatcher.add_handler(CommandHandler('allstats', send_all_stats))

    # register invalid command handler
    dispatcher.add_handler(MessageHandler(Filters.command, invalid_command))

    # register media listener
    dispatcher.add_handler(MessageHandler((Filters.photo | Filters.sticker | Filters.document), image_sticker_received))
    dispatcher.add_handler(MessageHandler(Filters.text, url_received))
    dispatcher.add_handler(MessageHandler(Filters.all, invalid_content))

    # register button handlers
    dispatcher.add_handler(CallbackQueryHandler(change_lang, pattern="lang"))

    # register inline share handler
    dispatcher.add_handler(InlineQueryHandler(inline_query_received))

    # register variable dump loop
    updater.job_queue.run_repeating(save_config, 300, 300)

    # register error handler
    dispatcher.add_error_handler(error)

    updater.start_polling(clean=True, timeout=99999)

    print("Bot finished starting")

    updater.idle()


def image_sticker_received(bot, update):
    message = update.message

    # get file id
    if message.document:
        # check that document is image
        document = message.document
        if document.mime_type.lower() in ('image/png', 'image/jpeg', 'image/webp'):
            photo_id = document.file_id
        else:
            # feedback to show bot is processing
            bot.send_chat_action(message.chat_id, 'typing')

            message.reply_markdown(get_message(message.chat_id, 'doc_not_img'))
            return
    elif message.photo:
        photo_id = message.photo[-1].file_id
    else:
        photo_id = message.sticker.file_id

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'upload_photo')

    # download file
    file = bot.get_file(file_id=photo_id)
    temp = file.file_path.split('/')[-1].split('.')
    if len(temp) > 1:
        ext = '.' + file.file_path.split('/')[-1].split('.')[1]
    else:
        ext = '.webp'
    download_path = os.path.join(dir, (photo_id + ext))
    file.download(custom_path=download_path)

    # process image and send to user
    image = format_image(Image.open(download_path))
    return_image(message, image)

    # delete local file
    os.remove(download_path)


def url_received(bot, update):
    message = update.message
    text = message.text.split(' ')

    if len(text) > 1:
        message.reply_text(get_message(message.chat_id, "too_many_urls"))
        return

    text = text[0]
    url = urlparse(text, 'https').geturl()

    # remove extra backslash after https if it exists
    if url.lower().startswith("https:///"):
        url = url.replace("https:///", "https://", 1)

    # get request
    try:
        request = requests.get(url, timeout=3)
        request.raise_for_status()
    except InvalidURL:
        message.reply_markdown(get_message(message.chat_id, "invalid_url").format(url))
        return
    except HTTPError:
        message.reply_markdown(get_message(message.chat_id, "url_does_not_exist").format(url))
        return
    except Timeout or ConnectTimeout:
        message.reply_markdown(get_message(message.chat_id, "url_timeout").format(url))
        return
    except ConnectionError or RequestException:
        message.reply_markdown(get_message(message.chat_id, "unable_to_connect").format(url))
        return

    # read image from url
    try:
        image = Image.open(BytesIO(request.content))
    except OSError:
        message.reply_markdown(get_message(message.chat_id, "url_not_img").format(url))
        return

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'upload_photo')

    # format image and send it to user
    image = format_image(image)
    return_image(message, image)


def format_image(image):
    width, height = image.size
    reference_length = max(width, height)
    ratio = 512 / reference_length
    new_width = width * ratio
    new_height = height * ratio
    # round up if new dimension has .999 or more
    if new_width % 1 >= .999:
        new_width = int(round(new_width))
    else:
        new_width = int(new_width)
    if new_height % 1 >= .999:
        new_height = int(round(new_height))
    else:
        new_height = int(new_height)
    return image.resize((new_width, new_height), Image.ANTIALIAS)


def return_image(message, image):
    temp_path = os.path.join(dir, (uuid.uuid4().hex[:6].upper() + '.png'))
    image.save(temp_path, optimize=True)

    # send formatted image as a document
    document = open(temp_path, 'rb')
    try:
        message.reply_document(document=document, filename='sticker.png',
                               caption=get_message(message.chat_id, "forward_to_stickers"), quote=True, timeout=30)
    except TelegramError:
        message.reply_text(get_message(user_id=message.chat_id, message="send_timeout"))

    # delete local files and close image object
    image.close()
    time.sleep(0.2)
    os.remove(temp_path)

    # increase total uses count by one
    global config
    config['uses'] += 1


def inline_query_received(bot, update):
    # get query
    query = update.inline_query
    user_id = query.from_user.id

    # build InlineQueryResultArticle arguments individually
    title = get_message(user_id, "share")
    description = get_message(user_id, "share_desc")
    thumb_url = "https://i.imgur.com/wKPBstd.jpg"
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(text=get_message(user_id, "make_sticker_button"), url="https://t.me/EzStickerBot")]])
    input_message_content = InputTextMessageContent(get_message(user_id, "share_text"), parse_mode='Markdown')

    # set id to preferred langs order
    id = int(get_message(user_id, "order"))

    results = [
        InlineQueryResultArticle(id=id, title=title, description=description, thumb_url=thumb_url, reply_markup=markup,
                                 input_message_content=input_message_content)]
    query.answer(results=results, cache_time=60, is_personal=True)


def invalid_command(bot, update):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    message.reply_text(get_message(message.chat_id, "invalid_command"))


def invalid_content(bot, update):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')

    message.reply_text(get_message(message.chat_id, "cant_process"))
    message.reply_markdown(get_message(message.chat_id, "send_sticker_photo"))


def bot_info(bot, update):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    keyboard = [
        [InlineKeyboardButton(get_message(message.chat_id, "contact_dev"), url="https://t.me/fxuls"),
         InlineKeyboardButton(get_message(message.chat_id, "source"),
                              url="https://github.com/fxuls/ez-sticker-bot")],
        [InlineKeyboardButton(get_message(message.chat_id, "rate"),
                              url="https://telegram.me/storebot?start=ezstickerbot"),
         InlineKeyboardButton(get_message(message.chat_id, "share"), switch_inline_query="")]]
    markup = InlineKeyboardMarkup(keyboard)
    message.reply_markdown(get_message(update.message.chat_id, "info").format(config['uses']), reply_markup=markup)


def restart_bot(bot, update):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    if update.message.from_user.id in config['admins']:
        message.reply_text(get_message(update.message.chat_id, "restarting"))
        save_config()
        os.execl(sys.executable, sys.executable, *sys.argv)
    else:
        message.reply_text(get_message(update.message.chat_id, "no_permission"))


def broadcast_command(bot, update):
    message = update.message
    chat_id = update.message.chat_id

    # feedback to show bot is processing
    bot.send_chat_action(chat_id, 'typing')

    # check for permission
    if chat_id not in config['admins']:
        message.reply_text(get_message(chat_id, "no_permission"))
        return

    target_message = message.reply_to_message

    # check that command was used in reply to a message
    if target_message is None:
        message.reply_markdown(get_message(chat_id, "broadcast_in_reply"))
        return

    broadcast_message = target_message.text_html
    # check that target message is a text message
    if broadcast_message is None:
        message.reply_markdown(get_message(chat_id, "broadcast_only_text"))
        return

    message.reply_text(get_message(chat_id, "will_broadcast"))
    updater.job_queue.run_once(broadcast_thread, 2, context=broadcast_message)


def broadcast_thread(bot, job):
    # check that message was included with the job obj
    if job.context is None:
        print("Broadcast thread created without message stored in job context")
        return

    global config
    index = 0
    for user_id in list(config['users']):
        # check if user is opted in
        try:
            opt_in = config['users'][user_id]['opt_in']
        except KeyError:
            # set opt_in default to true
            config['users'][user_id]['opt_in'] = True
            opt_in = True

        # catch any errors thrown by users who have stopped bot
        try:
            if opt_in and not config['override_opt_out']:
                bot.send_message(chat_id=int(user_id), text=job.context, parse_mode='HTML',
                                 disable_web_page_preview=True)
                # send opt out message
                if config['send_opt_out_message']:
                    bot.send_message(chat_id=int(user_id), text=get_message(user_id, "opt_out_info"))
        except TelegramError:
            pass

        index += 1
        if index >= 10:
            time.sleep(15)
            index = 0


def opt_command(bot, update):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')

    # get user opt_in status
    global config
    user_id = str(message.from_user.id)
    try:
        opt_in = config['users'][user_id]['opt_in']
    except KeyError:
        config['users'][user_id]['opt_in'] = True
        opt_in = True

    command = message.text.split(' ')[0][1:].lower()
    if command == 'optin':
        if opt_in:
            message.reply_text(get_message(user_id, "already_opted_in"))
        else:
            config['users'][user_id]['opt_in'] = True
            message.reply_text(get_message(user_id, "opted_in"))
    else:
        if not opt_in:
            message.reply_text(get_message(user_id, "already_opted_out"))
        else:
            config['users'][user_id]['opt_in'] = False
            message.reply_text(get_message(user_id, "opted_out"))


def change_lang_command(bot, update):
    ordered_langs = [None] * len(lang)
    for lang_code in lang.keys():
        ordered_langs[int(lang[lang_code]['order'])] = lang_code
    keyboard = [[]]
    row = 0
    for lang_code in ordered_langs:
        if len(keyboard[row]) == 3:
            row += 1
            keyboard.append([])
        # noinspection PyTypeChecker
        keyboard[row].append(
            InlineKeyboardButton(lang[lang_code]['lang_name'], callback_data="lang:{}".format(lang_code)))
    markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(get_message(update.message.chat_id, "select_lang"), reply_markup=markup)


def change_lang(bot, update):
    query = update.callback_query
    lang_code = query.data.split(':')[-1]
    user_id = query.from_user.id
    global config
    config['users'][str(user_id)]['lang'] = lang_code

    # replace instances of $userid with username or name if no username
    message = get_message(user_id, "lang_set").split(' ')
    for i in range(len(message)):
        word = message[i]
        if word[0] == '$':
            try:
                id = int(''.join(c for c in word if c.isdigit()))
                user = bot.get_chat(id)
                message[i] = '<a href="tg://user?id={}">{}{}</a>'.format(id, user.first_name,
                                                                         ' ' + user.last_name if user.last_name else '')
            except ValueError:
                message[i] = 'UNKNOWN_USER_ID'
                continue
            except TelegramError:
                message[i] = 'INVALID_USER_ID'
                continue
    message = ' '.join(message)

    query.edit_message_text(text=message, reply_markup=None, parse_mode='HTML')
    query.answer()


def get_message(user_id, message):
    global config
    user_id = str(user_id)
    if user_id not in config['users']:
        # create user entry in users and set default values
        config['users'][user_id] = {}
        config['users'][user_id]['opt_in'] = True

        # attempt to automatically set language
        lang_code = updater.bot.get_chat(user_id).get_member(user_id).user.language_code.lower()
        if lang_code is not None and lang_code[:2] in lang:
            config['users'][user_id]['lang'] = lang_code[:2]
            if lang_code[:2] != 'en':
                config['langs_auto_set'] += 1
        else:
            config['users'][user_id]['lang'] = 'en'
    lang_pref = config['users'][user_id]['lang']
    # if message doesn't have translation in user's language default to english
    if message not in lang[lang_pref]:
        lang_pref = 'en'
    return lang[lang_pref][message]


def get_lang():
    path = os.path.join(dir, 'lang.json')
    data = json.load(codecs.open(path, 'r', 'utf-8-sig'))
    for lang_code in data:
        for message in data[lang_code]:
            data[lang_code][message] = data[lang_code][message].replace('\\n', '\n')
    global lang
    lang = data


def get_config():
    path = os.path.join(dir, 'config.json')
    with open(path) as config_file:
        global config
        config = json.load(config_file)
    config_file.close()


def save_config(bot=None, job=None):
    data = json.dumps(config)
    path = os.path.join(dir, 'config.json')
    with open(path, "w") as config_file:
        config_file.write(simplejson.dumps(simplejson.loads(data), indent=4, sort_keys=True))
    config_file.close()


# logs bot errors thrown
def error(bot, update, error):
    # prevent spammy errors from logging
    if error in ("Forbidden: bot was blocked by the user", "Timed out"):
        return
    logger.warning('Update "{}" caused error "{}"'.format(update, error))


def do_fucking_nothing(bot, update):
    pass


if __name__ == '__main__':
    main()
