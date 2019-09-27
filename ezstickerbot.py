import codecs
import json
import logging
import os
import re
import sys
import time
import uuid
from collections import Counter
from io import BytesIO
from urllib.parse import urlparse

import requests
import simplejson
from PIL import Image
from requests.exceptions import InvalidURL, HTTPError, RequestException, ConnectionError, Timeout, ConnectTimeout
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent, \
    InlineQueryResultCachedDocument, Update
from telegram.error import TelegramError, TimedOut
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, InlineQueryHandler, \
    ChosenInlineResultHandler, CallbackContext
from telegram.ext.dispatcher import run_async

# setup logger
logging.getLogger("urllib3.connection").setLevel(logging.CRITICAL)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO,
                    filename="logs.log", filemode="a+")
logger = logging.getLogger(__name__)

dir = os.path.dirname(__file__)

bot: Bot = None

config = {}
lang = {}


def main():
    get_config()
    get_lang()

    updater = Updater(config['token'], use_context=True, workers=10)
    dispatcher = updater.dispatcher
    global bot
    bot = updater.bot

    # register a handler to ignore all non-private updates
    dispatcher.add_handler(MessageHandler(~ Filters.private, do_fucking_nothing))

    # register commands
    dispatcher.add_handler(CommandHandler('broadcast', broadcast_command))
    dispatcher.add_handler(CommandHandler('help', help_command))
    dispatcher.add_handler(CommandHandler('icon', icon_command))
    dispatcher.add_handler(CommandHandler('info', info_command))
    dispatcher.add_handler(CommandHandler('lang', change_lang_command))
    dispatcher.add_handler(CommandHandler('langstats', lang_stats_command))
    dispatcher.add_handler(CommandHandler(['optin', 'optout'], opt_command))
    dispatcher.add_handler(CommandHandler('restart', restart_command))
    dispatcher.add_handler(CommandHandler('start', start_command))
    dispatcher.add_handler(CommandHandler('stats', stats_command))

    # register invalid command handler
    dispatcher.add_handler(MessageHandler(Filters.command, invalid_command))

    # register media listener
    dispatcher.add_handler(MessageHandler((Filters.photo | Filters.document), image_received))
    dispatcher.add_handler(MessageHandler(Filters.sticker, sticker_received))
    dispatcher.add_handler(MessageHandler(Filters.text, url_received))
    dispatcher.add_handler(MessageHandler(Filters.all, invalid_content))

    # register button handlers
    dispatcher.add_handler(CallbackQueryHandler(change_lang_callback, pattern="lang"))
    dispatcher.add_handler(CallbackQueryHandler(icon_cancel_callback, pattern="icon_cancel"))

    # register inline handlers
    dispatcher.add_handler(InlineQueryHandler(share_query_received, pattern=re.compile("^share$", re.IGNORECASE)))
    dispatcher.add_handler(InlineQueryHandler(file_id_query_received, pattern=re.compile("")))
    dispatcher.add_handler(InlineQueryHandler(share_query_received))

    dispatcher.add_handler(ChosenInlineResultHandler(inline_result_chosen))

    # register variable dump loop
    updater.job_queue.run_repeating(save_config, config['save_interval'], config['save_interval'])

    # register error handler
    dispatcher.add_error_handler(handle_error)

    updater.start_polling(clean=True, timeout=99999)

    print("Bot finished starting")

    updater.idle()


#   ____
#  / ___|   ___    _ __    ___
# | |      / _ \  | '__|  / _ \
# | |___  | (_) | | |    |  __/
#  \____|  \___/  |_|     \___|

@run_async
def image_received(update: Update, context: CallbackContext):
    message = update.message
    user_id = message.from_user.id

    # get file id
    if message.document:
        # check that document is image
        document = message.document
        if document.mime_type.lower() in ('image/png', 'image/jpeg', 'image/webp'):
            photo_id = document.file_id
        else:
            # feedback to show bot is processing
            bot.send_chat_action(user_id, 'typing')

            message.reply_markdown(get_message(user_id, 'doc_not_img'))
            return
    else:
        photo_id = message.photo[-1].file_id

    # feedback to show bot is processing
    bot.send_chat_action(user_id, 'upload_document')

    try:
        download_path = download_file(photo_id)
        image = Image.open(download_path)

        create_sticker_file(message, image, context.user_data)

        # delete local file
        os.remove(download_path)
    except TimedOut:
        message.reply_text(get_message(user_id, "send_timeout"))


@run_async
def sticker_received(update: Update, context: CallbackContext):
    message = update.message
    user_id = message.from_user.id

    sticker_id = message.sticker.file_id

    # feedback to show bot is processing
    bot.send_chat_action(user_id, 'upload_document')

    try:
        download_path = download_file(sticker_id)

        # check if user is making icon
        if 'make_icon' in context.user_data and context.user_data['make_icon']:
            image = Image.open(download_path)
            create_sticker_file(message, image, context.user_data)

        # send them sticker as document
        else:
            document = open(download_path, 'rb')
            sent_message = message.reply_document(document=document, filename="sticker.png",
                                                  caption=get_message(message.chat_id, "forward_to_stickers"),
                                                  quote=True,
                                                  timeout=30)
            # add a keyboard with a forward button to the document
            file_id = sent_message.document.file_id
            markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton(get_message(message.chat_id, "forward"), switch_inline_query=file_id)]])
            sent_message.edit_reply_markup(reply_markup=markup)

        # delete local file
        os.remove(download_path)
    except TelegramError:
        message.reply_text(get_message(user_id, "send_timeout"))


@run_async
def url_received(update: Update, context: CallbackContext):
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
    bot.send_chat_action(message.chat_id, 'upload_document')

    create_sticker_file(message, image, context.user_data)


def create_sticker_file(message, image, user_data):
    # set make_icon if not already set
    if 'make_icon' not in user_data:
        user_data['make_icon'] = False

    # if user is making icon
    if user_data['make_icon']:
        image.thumbnail((100, 100), Image.ANTIALIAS)
        background = Image.new('RGBA', (100, 100), (255, 255, 255, 0))
        background.paste(image, (int(((100 - image.size[0]) / 2)), int(((100 - image.size[1]) / 2))))
        image = background

    # else format image to sticker
    else:
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

        image = image.resize((new_width, new_height), Image.ANTIALIAS)

    # save image object to temporary file
    temp_path = os.path.join(dir, (uuid.uuid4().hex[:6].upper() + '.png'))
    image.save(temp_path, optimize=True)

    # send formatted image as a document
    document = open(temp_path, 'rb')
    try:
        filename = 'icon.png' if user_data['make_icon'] else 'sticker.png'
        sent_message = message.reply_document(document=document, filename=filename,
                                              caption=get_message(message.chat_id, "forward_to_stickers"), quote=True,
                                              timeout=30)
        # add a keyboard with a forward button to the document
        file_id = sent_message.document.file_id
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(get_message(message.chat_id, "forward"), switch_inline_query=file_id)]])
        sent_message.edit_reply_markup(reply_markup=markup)
    except TelegramError:
        message.reply_text(get_message(user_id=message.chat_id, message="send_timeout"))

    # delete local files and close image object
    image.close()
    time.sleep(0.2)
    os.remove(temp_path)

    # remove user from make_icon if icon was created
    if user_data['make_icon']:
        user_data['make_icon'] = False

    # increase total uses count by one
    global config
    config['uses'] += 1
    config['users'][str(message.from_user.id)]['uses'] += 1


def download_file(file_id):
    try:
        # download file
        file = bot.get_file(file_id=file_id, timeout=30)
        temp = file.file_path.split('/')[-1].split('.')
        if len(temp) > 1:
            ext = '.' + file.file_path.split('/')[-1].split('.')[1]
        else:
            ext = '.webp'
        download_path = os.path.join(dir, (file_id + ext))
        file.download(custom_path=download_path)

        return download_path
    except TimedOut:
        raise TimedOut


#  _____                          _       _   _                       _   _
# | ____| __   __   ___   _ __   | |_    | | | |   __ _   _ __     __| | | |   ___   _ __   ___
# |  _|   \ \ / /  / _ \ | '_ \  | __|   | |_| |  / _` | | '_ \   / _` | | |  / _ \ | '__| / __|
# | |___   \ V /  |  __/ | | | | | |_    |  _  | | (_| | | | | | | (_| | | | |  __/ | |    \__ \
# |_____|   \_/    \___| |_| |_|  \__|   |_| |_|  \__,_| |_| |_|  \__,_| |_|  \___| |_|    |___/

@run_async
def change_lang_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    lang_code = query.data.split(':')[-1]
    user_id = str(query.from_user.id)

    global config
    config['users'][user_id]['lang'] = lang_code

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

    # set icon_warned to false
    config['users'][user_id]['icon_warned'] = False

    query.edit_message_text(text=message, reply_markup=None, parse_mode='HTML')
    query.answer()


@run_async
def share_query_received(update: Update, context: CallbackContext):
    query = update.inline_query
    user_id = query.from_user.id

    # get labels in user's language
    title = get_message(user_id, "share")
    description = get_message(user_id, "share_desc")
    thumb_url = config['share_thumb_url']
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(text=get_message(user_id, "make_sticker_button"), url="https://t.me/EzStickerBot")]])
    input_message_content = InputTextMessageContent(get_message(user_id, "share_text"), parse_mode='Markdown')

    # build response and answer query
    results = [InlineQueryResultArticle(id="share", title=title, description=description, thumb_url=thumb_url,
                                        reply_markup=markup, input_message_content=input_message_content)]
    query.answer(results=results, cache_time=5, is_personal=True)


@run_async
def file_id_query_received(update: Update, context: CallbackContext):
    # get query
    query = update.inline_query
    user_id = query.from_user.id
    results = None

    try:
        file = bot.get_file(query.query)

        id = uuid.uuid4()
        title = get_message(user_id, "your_sticker")
        desc = get_message(user_id, "forward_desc")
        caption = "@EzStickerBot"
        results = [InlineQueryResultCachedDocument(id, title, file.file_id, description=desc, caption=caption)]

        query.answer(results=results, cache_time=5, is_personal=True)
    # if file_id wasn't found show share option
    except TelegramError:
        share_query_received(update, context)


@run_async
def icon_cancel_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)

    # set make_icon in user_data to false
    context.user_data['make_icon'] = False

    query.edit_message_text(text=get_message(user_id, "icon_canceled"), reply_markup=None)
    query.answer()


@run_async
def inline_result_chosen(update: Update, context: CallbackContext):
    chosen_result = update.chosen_inline_result
    result_id = chosen_result.result_id

    global config
    # if was a share increase count by one
    if result_id == 'share':
        config['times_shared'] += 1


@run_async
def invalid_command(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    message.reply_text(get_message(message.chat_id, "invalid_command"))


@run_async
def invalid_content(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')

    message.reply_text(get_message(message.chat_id, "cant_process"))
    message.reply_markdown(get_message(message.chat_id, "send_sticker_photo"))


def do_fucking_nothing(update: Update, context: CallbackContext):
    pass


#   ____                                                       _
#  / ___|   ___    _ __ ___    _ __ ___     __ _   _ __     __| |  ___
# | |      / _ \  | '_ ` _ \  | '_ ` _ \   / _` | | '_ \   / _` | / __|
# | |___  | (_) | | | | | | | | | | | | | | (_| | | | | | | (_| | \__ \
#  \____|  \___/  |_| |_| |_| |_| |_| |_|  \__,_| |_| |_|  \__,_| |___/

@run_async
def broadcast_command(update: Update, context: CallbackContext):
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
    context.job_queue.run_once(broadcast_thread, 2, context=broadcast_message)


@run_async
def change_lang_command(update: Update, context: CallbackContext):
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


@run_async
def help_command(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    message.reply_text(get_message(message.chat_id, "help"))


@run_async
def icon_command(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')

    # set make_icon to True in user_data
    context.user_data['make_icon'] = True

    # create keyboard with cancel button
    keyboard = [[
        InlineKeyboardButton(get_message(message.chat_id, "cancel"), callback_data="icon_cancel")
    ]]
    markup = InlineKeyboardMarkup(keyboard)

    # if user has not been sent icon info message send it
    if not get_user_config(message.chat_id, 'icon_warned'):
        message.reply_markdown(get_message(message.chat_id, "icon_command_info"))

        global config
        config['users'][str(message.chat_id)]['icon_warned'] = True

    message.reply_markdown(get_message(message.chat_id, "icon_command"), reply_markup=markup)


@run_async
def info_command(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    keyboard = [
        [InlineKeyboardButton(get_message(message.chat_id, "contact_dev"), url=config['contact_dev_link']),
         InlineKeyboardButton(get_message(message.chat_id, "source"),
                              url=config['source_link'])],
        [InlineKeyboardButton(get_message(message.chat_id, "rate"),
                              url=config['rate_link']),
         InlineKeyboardButton(get_message(message.chat_id, "share"), switch_inline_query="share")]]
    markup = InlineKeyboardMarkup(keyboard)
    message.reply_markdown(get_message(message.chat_id, "info").format(config['uses']), reply_markup=markup)


@run_async
def lang_stats_command(update: Update, context: CallbackContext):
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


@run_async
def opt_command(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')

    # get user opt_in status
    global config
    user_id = str(message.from_user.id)
    opt_in = get_user_config(user_id, "opt_in")

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


def restart_command(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    if update.message.from_user.id in config['admins']:
        message.reply_text(get_message(update.message.chat_id, "restarting"))
        save_config()
        os.execl(sys.executable, sys.executable, *sys.argv)
    else:
        message.reply_text(get_message(update.message.chat_id, "no_permission"))


@run_async
def start_command(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    message.reply_markdown(get_message(message.chat_id, "start"))


@run_async
def stats_command(update: Update, context: CallbackContext):
    message = update.message
    user_id = message.chat_id

    # feedback to show bot is processing
    bot.send_chat_action(user_id, 'typing')

    opted_in = 0
    opted_out = 0
    for user in config['users'].values():
        if user['opt_in']:
            opted_in += 1
        else:
            opted_out += 1

    personal_uses = get_user_config(user_id, "uses")
    stats_message = get_message(user_id, "stats").format(config['uses'], len(config['users']), personal_uses,
                                                         config['langs_auto_set'], config['times_shared'],
                                                         opted_in + opted_out, opted_in, opted_out)
    message.reply_markdown(stats_message)


#  _   _   _     _   _
# | | | | | |_  (_) | |  ___
# | | | | | __| | | | | / __|
# | |_| | | |_  | | | | \__ \
#  \___/   \__| |_| |_| |___/


@run_async
def broadcast_thread(context: CallbackContext):
    # check that message was included with the job obj
    if context.job.context is None:
        print("Broadcast thread created without message stored in job context")
        return

    global config
    index = 0
    for user_id in list(config['users']):
        # check if user is opted in
        opt_in = get_user_config(user_id, "opt_in")

        # catch any errors thrown by users who have stopped bot
        try:
            if opt_in and not config['override_opt_out']:
                bot.send_message(chat_id=int(user_id), text=context.job.context, parse_mode='HTML',
                                 disable_web_page_preview=True)
                # send opt out message
                if config['send_opt_out_message']:
                    bot.send_message(chat_id=int(user_id), text=get_message(user_id, "opt_out_info"))
        except TelegramError:
            pass

        index += 1
        if index >= config['broadcast_batch_size']:
            time.sleep(config['broadcast_batch_interval'])
            index = 0


def get_config():
    path = os.path.join(dir, 'config.json')
    with open(path) as config_file:
        global config
        config = json.load(config_file)
    config_file.close()


def get_lang():
    path = os.path.join(dir, 'lang.json')
    data = json.load(codecs.open(path, 'r', 'utf-8-sig'))
    for lang_code in data:
        for message in data[lang_code]:
            data[lang_code][message] = data[lang_code][message].replace('\\n', '\n')
    global lang
    lang = data


def get_message(user_id, message):
    lang_pref = get_user_config(user_id, "lang")

    # if message doesn't have translation in user's language default to english
    if message not in lang[lang_pref]:
        lang_pref = 'en'

    return lang[lang_pref][message]


def get_user_config(user_id, key):
    global config
    user_id = str(user_id)

    # if user not registered register with default values
    if user_id not in config['users']:
        config['users'][user_id] = config['default_user'].copy()

        # attempt to automatically set language
        lang_code = bot.get_chat(user_id).get_member(user_id).user.language_code.lower()
        if lang_code is not None and lang_code[:2] in lang:
            config['users'][user_id]['lang'] = lang_code[:2]
            if lang_code[:2] != 'en':
                config['langs_auto_set'] += 1
    # if user is registered but does not have requested key set to default value from config
    elif key not in config['users'][user_id]:
        try:
            config['users'][user_id][key] = config['default_user'][key].copy()
        # if value isn't a type with a copy function like a string or int
        except AttributeError:
            config['users'][user_id][key] = config['default_user'][key]

    # return value
    return config['users'][user_id][key]


# logs bot errors thrown
def handle_error(update: Update, context: CallbackContext):
    # prevent spammy errors from logging
    if context.error in ("Forbidden: bot was blocked by the user", "Timed out"):
        return
    logger.warning('Update "{}" caused error "{}"'.format(update, context.error))


def save_config(context: CallbackContext = None):
    data = json.dumps(config)
    path = os.path.join(dir, 'config.json')
    with open(path, "w") as config_file:
        config_file.write(simplejson.dumps(simplejson.loads(data), indent=4, sort_keys=True))
    config_file.close()


if __name__ == '__main__':
    main()
