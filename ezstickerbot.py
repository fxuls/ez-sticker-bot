import codecs
import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from collections import Counter
from datetime import datetime
from io import BytesIO
from urllib.parse import urlparse

import requests
import simplejson
from PIL import Image
from requests.exceptions import (ConnectionError, ConnectTimeout, HTTPError,
                                 InvalidURL, RequestException, Timeout)
from telegram import (Bot, InlineKeyboardButton, InlineKeyboardMarkup,
                      InlineQueryResultArticle,
                      InlineQueryResultCachedDocument, InputTextMessageContent,
                      Update)
from telegram.error import BadRequest, TelegramError, TimedOut, Unauthorized
from telegram.ext import (CallbackContext, CallbackQueryHandler,
                          ChosenInlineResultHandler, CommandHandler, Filters,
                          InlineQueryHandler, MessageHandler, Updater)
from telegram.ext.dispatcher import run_async

directory = os.path.dirname(__file__)

# set up logging
log_formatter = logging.Formatter(
    "\n%(asctime)s [%(name)s] [%(levelname)s] %(message)s")
logger = logging.getLogger()
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(
    os.path.join(directory, "ez-sticker-bot.log"))
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

bot: Bot = None

config = {}
users = {}
lang = {}

recent_uses = {}


def main():
    load_files()

    updater = Updater(config['token'], use_context=True, workers=10)
    dispatcher = updater.dispatcher
    global bot
    bot = updater.bot

    # register a handler to ignore all non-private updates
    dispatcher.add_handler(MessageHandler(~Filters.private,
                                          do_fucking_nothing))

    # register commands
    dispatcher.add_handler(CommandHandler('broadcast', broadcast_command))
    dispatcher.add_handler(CommandHandler('donate', donate_command))
    dispatcher.add_handler(CommandHandler('help', help_command))
    dispatcher.add_handler(CommandHandler('icon', icon_command))
    dispatcher.add_handler(CommandHandler('info', info_command))
    dispatcher.add_handler(CommandHandler('lang', change_lang_command))
    dispatcher.add_handler(CommandHandler('langstats', lang_stats_command))
    dispatcher.add_handler(CommandHandler('log', log_command))
    dispatcher.add_handler(CommandHandler(['optin', 'optout'], opt_command))
    dispatcher.add_handler(CommandHandler('restart', restart_command))
    dispatcher.add_handler(CommandHandler('start', start_command))
    dispatcher.add_handler(CommandHandler('stats', stats_command))

    # register invalid command handler
    dispatcher.add_handler(MessageHandler(Filters.command, invalid_command))

    # register media listener
    dispatcher.add_handler(
        MessageHandler((Filters.document), document_received))
    dispatcher.add_handler(MessageHandler((Filters.video), video_received))
    dispatcher.add_handler(MessageHandler((Filters.photo), image_received))
    dispatcher.add_handler(MessageHandler(Filters.sticker, sticker_received))
    dispatcher.add_handler(MessageHandler(Filters.text, url_received))
    dispatcher.add_handler(MessageHandler(Filters.all, invalid_content))

    # register button handlers
    dispatcher.add_handler(
        CallbackQueryHandler(change_lang_callback, pattern="lang"))
    dispatcher.add_handler(
        CallbackQueryHandler(icon_cancel_callback, pattern="icon_cancel"))

    # register inline handlers
    dispatcher.add_handler(
        InlineQueryHandler(share_query_received,
                           pattern=re.compile("^share$", re.IGNORECASE)))
    dispatcher.add_handler(
        InlineQueryHandler(file_id_query_received, pattern=re.compile("")))
    dispatcher.add_handler(InlineQueryHandler(share_query_received))

    dispatcher.add_handler(ChosenInlineResultHandler(inline_result_chosen))

    # register variable dump loop
    updater.job_queue.run_repeating(save_files, config['save_interval'],
                                    config['save_interval'])

    # register error handler
    dispatcher.add_error_handler(handle_error)

    updater.start_polling(clean=True, timeout=99999)

    print("Bot finished starting")

    updater.idle()


#  core functions


def validate_chat_id(chat_id):
    chat_id = str(chat_id)
    allowed_chat_ids = config['allowed_chat_ids']
    if allowed_chat_ids:
        # if user set allowed chat ids, return True if chat_id is in the list
        return chat_id in allowed_chat_ids
    else:
        # if user didn't set allowed chat ids, return True (allow all)
        return True


def restricted(func):

    def wrapper(update, context):
        chat_id = update.message.chat_id
        print(f"Received `{func.__name__}` in {chat_id}.")
        if validate_chat_id(chat_id):
            func(update, context)
        else:
            # log unauthorized access
            print(
                f"Unauthorized access denied for {chat_id} ({update.message.from_user.name})"  # noqa: E501
            )

    return wrapper


@restricted
@run_async
def document_received(update: Update, context: CallbackContext):
    message = update.message
    document = message.document

    # check if document is video
    if document.mime_type.startswith('video/'):
        video_received(update, context)
        return

    # check if document is image
    if document.mime_type.startswith('image/'):
        image_received(update, context)
        return


@restricted
@run_async
def image_received(update: Update, context: CallbackContext):
    message = update.message
    user_id = message.from_user.id

    # check spam filter
    cooldown_info = user_on_cooldown(user_id)
    if cooldown_info[0]:
        minutes = int(config['spam_interval'] / 60)
        message_text = get_message(user_id, 'spam_limit_reached').format(
            config['spam_max'], minutes, cooldown_info[1], cooldown_info[2])
        message.reply_markdown(message_text)
        return

    # get file id
    if message.document:
        # check that document is image
        document = message.document
        if document.mime_type.lower() in ('image/png', 'image/jpeg',
                                          'image/webp'):
            photo_id = document.file_id
        else:
            # feedback to show bot is processing
            bot.send_chat_action(user_id, 'typing')

            message.reply_markdown(get_message(user_id, 'doc_not_img'))
            return
        # check that document is not too large
        if document.file_size > config['max_file_size']:
            # feedback to show bot is processing
            bot.send_chat_action(user_id, 'typing')

            message.reply_text(get_message(user_id, 'file_too_large'))
            return
    else:
        photo_id = message.photo[-1].file_id

    # feedback to show bot is processing
    bot.send_chat_action(user_id, 'upload_document')

    try:
        download_path = download_file(photo_id)
        image = Image.open(download_path)

        create_sticker_file(message, image, context)

        # delete local file
        os.remove(download_path)
    except TimedOut:
        message.reply_text(get_message(user_id, "send_timeout"))
    except FileNotFoundError:
        # if file does not exist ignore
        pass


@restricted
@run_async
def sticker_received(update: Update, context: CallbackContext):
    message = update.message
    user_id = message.from_user.id

    # check spam filter
    cooldown_info = user_on_cooldown(user_id)
    if cooldown_info[0]:
        minutes = int(config['spam_interval'] / 60)
        message_text = get_message(user_id, 'spam_limit_reached').format(
            config['spam_max'], minutes, cooldown_info[1], cooldown_info[2])
        message.reply_markdown(message_text)
        return

    # check if sticker is animated
    if message.sticker.is_animated:
        animated_sticker_received(update, context)
        return

    sticker_id = message.sticker.file_id

    # feedback to show bot is processing
    bot.send_chat_action(user_id, 'upload_document')

    try:
        download_path = download_file(sticker_id)

        image = Image.open(download_path)
        create_sticker_file(message, image, context)

        # delete local file
        os.remove(download_path)
    except Unauthorized:
        pass
    except TelegramError:
        message.reply_text(get_message(user_id, "send_timeout"))
    except FileNotFoundError:
        # if file does not exist ignore
        pass


@restricted
def animated_sticker_received(update: Update, context: CallbackContext):
    message = update.message
    user_id = message.from_user.id

    # feedback to show bot is processing
    bot.send_chat_action(user_id, 'upload_document')

    sticker_id = message.sticker.file_id

    # download sticker and send as document
    try:
        download_path = download_file(sticker_id)

        document = open(download_path, 'rb')
        sticker_message = message.reply_document(document=document)
        sent_message = sticker_message.reply_markdown(get_message(
            user_id, "forward_animated_sticker"),
                                                      quote=True)

        # add a keyboard with a forward button to the document
        file_id = sticker_message.sticker.file_id
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton(get_message(user_id, "forward"),
                                 switch_inline_query=file_id)
        ]])
        sent_message.edit_reply_markup(reply_markup=markup)

        # delete local file
        os.remove(download_path)
    except TelegramError:
        message.reply_text(get_message(user_id, "send_timeout"))
    except FileNotFoundError:
        # if file does not exist ignore
        pass

    # record use in spam filter
    record_use(user_id, context)

    # increase total uses count by one
    global config
    config['uses'] += 1
    global users
    users[str(user_id)]['uses'] += 1

    donate_suggest(user_id)


@restricted
@run_async
def video_received(update: Update, context: CallbackContext):
    message = update.message
    user_id = message.from_user.id

    # check spam filter
    cooldown_info = user_on_cooldown(user_id)
    if cooldown_info[0]:
        minutes = int(config['spam_interval'] / 60)
        message_text = get_message(user_id, 'spam_limit_reached').format(
            config['spam_max'], minutes, cooldown_info[1], cooldown_info[2])
        message.reply_markdown(message_text)
        return

    # feedback to show bot is processing
    bot.send_chat_action(user_id, 'upload_document')

    document = message.document
    video_id = document.file_id
    try:
        download_path = download_file(video_id)
        output_path = make_video(download_path)

        # remove local files
        os.remove(download_path)
    except TimedOut:
        message.reply_text(get_message(user_id, "send_timeout"))
        return
    except FileNotFoundError:
        # if file does not exist ignore
        return

    # send video
    document = open(output_path, 'rb')
    try:
        filename = os.path.basename(output_path)
        sent_message = message.reply_document(document=document,
                                              filename=filename,
                                              caption=get_message(
                                                  user_id,
                                                  "forward_to_stickers"),
                                              quote=True,
                                              timeout=30)
        # add a keyboard with a forward button to the document
        file_id = sent_message.document.file_id
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton(get_message(user_id, "forward"),
                                 switch_inline_query=file_id)
        ]])
        sent_message.edit_reply_markup(reply_markup=markup)
    except Unauthorized:
        pass
    except TelegramError:
        message.reply_text(get_message(user_id, "send_timeout"))

    # remove local file
    os.remove(output_path)


@restricted
@run_async
def url_received(update: Update, context: CallbackContext):
    message = update.message
    user_id = message.from_user.id
    text = message.text.split(' ')

    # check spam filter
    cooldown_info = user_on_cooldown(user_id)
    if cooldown_info[0]:
        message.reply_markdown(
            get_message(user_id,
                        'spam_limit_reached').format(cooldown_info[1],
                                                     cooldown_info[2]))
        return

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
        # check that file is not too big
        head = requests.head(url, timeout=3)
        if int(head.headers['Content-length']) > config['max_file_size']:
            # feedback to show bot is processing
            bot.send_chat_action(user_id, 'typing')

            message.reply_text(get_message(user_id, 'file_too_large'))
            return

        request = requests.get(url, timeout=3)
        request.raise_for_status()
    except InvalidURL:
        message.reply_markdown(
            get_message(message.chat_id, "invalid_url").format(url))
        return
    except HTTPError:
        message.reply_markdown(
            get_message(message.chat_id, "url_does_not_exist").format(url))
        return
    except Timeout or ConnectTimeout:
        message.reply_markdown(
            get_message(message.chat_id, "url_timeout").format(url))
        return
    except ConnectionError or RequestException or UnicodeError:
        message.reply_markdown(
            get_message(message.chat_id, "unable_to_connect").format(url))
        return
    except UnicodeError:
        message.reply_markdown(
            get_message(message.chat_id, "unable_to_connect").format(url))
        return

    # read image from url
    try:
        image = Image.open(BytesIO(request.content))
    except OSError:
        message.reply_markdown(
            get_message(message.chat_id, "url_not_img").format(url))
        return

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'upload_document')

    create_sticker_file(message, image, context)


def make_video(input_file):
    # setup the file names (separate extension from file name)
    input_file_name = input_file.split("/")[-1]
    extension = input_file_name.split(".")[-1]
    input_file_name = input_file_name.split(".")[0]
    input_file_path = "/".join(input_file.split("/")[:-1])
    tmp_file_name = f"{input_file_name}_{uuid.uuid4().hex}.{extension}"

    # get the width and height of the video
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height", "-of", "csv=p=0", input_file
    ]
    output = subprocess.check_output(cmd)
    width, height = map(int, output.decode().strip().split(","))

    if width > height:
        new_width = 512
        ratio = new_width / width
        new_height = int(height * ratio)
    else:
        new_height = 512
        ratio = new_height / height
        new_width = int(width * ratio)

    # run ffmpeg to convert the video
    # telegram requirements:
    #   - 3s long
    #   - 30 fps
    #   - webm vp9 codec
    #   - no audio
    #   - scaled to new_width x new_height
    output_file_name = f"{tmp_file_name}.webm"
    output_file_path = f"{input_file_path}/{output_file_name}"
    cmd = [
        "ffmpeg", "-ss", "00:00:00", "-i", input_file, "-t", "00:00:03",
        "-filter:v", "fps=fps=30,scale={}:{}".format(new_width, new_height),
        "-an", "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", "-strict",
        "-2", output_file_path
    ]
    try:
        subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        print(e.stderr.decode())

    # return the output file path
    return output_file_path


def create_sticker_file(message, image, context: CallbackContext):
    user_id = message.from_user.id
    user_data = context.user_data

    # set make_icon if not already set
    if 'make_icon' not in user_data:
        user_data['make_icon'] = False

    # if user is making icon
    if user_data['make_icon']:
        image.thumbnail((100, 100), Image.ANTIALIAS)
        background = Image.new('RGBA', (100, 100), (255, 255, 255, 0))
        background.paste(image, (int(
            ((100 - image.size[0]) / 2)), int(((100 - image.size[1]) / 2))))
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
    temp_path = os.path.join(temp_dir(),
                             (uuid.uuid4().hex[:6].upper() + '.png'))
    image.save(temp_path, format="PNG", optimize=True)

    # send formatted image as a document
    document = open(temp_path, 'rb')
    try:
        filename = 'icon.png' if user_data['make_icon'] else 'sticker.png'
        sent_message = message.reply_document(document=document,
                                              filename=filename,
                                              caption=get_message(
                                                  user_id,
                                                  "forward_to_stickers"),
                                              quote=True,
                                              timeout=30)
        # add a keyboard with a forward button to the document
        file_id = sent_message.document.file_id
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton(get_message(user_id, "forward"),
                                 switch_inline_query=file_id)
        ]])
        sent_message.edit_reply_markup(reply_markup=markup)
    except Unauthorized:
        pass
    except TelegramError:
        message.reply_text(get_message(user_id, "send_timeout"))

    # delete local files and close image object
    image.close()
    os.remove(temp_path)

    # remove user from make_icon if icon was created
    if user_data['make_icon']:
        user_data['make_icon'] = False

    # record use in spam filter
    record_use(user_id, context)

    # increase total uses count by one
    global config
    config['uses'] += 1
    global users
    users[str(user_id)]['uses'] += 1

    donate_suggest(user_id)


def download_file(file_id):
    try:
        # download file
        file = bot.get_file(file_id=file_id, timeout=30)
        ext = '.' + file.file_path.split('/')[-1].split('.')[1]
        download_path = os.path.join(temp_dir(), (file_id + ext))
        file.download(custom_path=download_path)

        return download_path
    except TimedOut:
        raise TimedOut


#  event handlers


@restricted
@run_async
def change_lang_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    lang_code = query.data.split(':')[-1]
    user_id = str(query.from_user.id)

    global users
    users[user_id]['lang'] = lang_code

    # replace instances of $userid with username or name if no username
    message = get_message(user_id, "lang_set").split(' ')
    for i in range(len(message)):
        word = message[i]
        if word[0] == '$':
            try:
                _id = int(''.join(c for c in word if c.isdigit()))
                user = bot.get_chat(_id)
                message[i] = '<a href="tg://user?id={}">{}{}</a>'.format(
                    _id, user.first_name,
                    ' ' + user.last_name if user.last_name else '')
            except ValueError:
                message[i] = 'UNKNOWN_USER_ID'
                continue
            except TelegramError:
                message[i] = 'INVALID_USER_ID'
                continue
    message = ' '.join(message)

    # set icon_warned to false
    users[user_id]['icon_warned'] = False

    query.edit_message_text(text=message, reply_markup=None, parse_mode='HTML')
    query.answer()


@restricted
@run_async
def share_query_received(update: Update, context: CallbackContext):
    query = update.inline_query
    user_id = query.from_user.id

    # get labels in user's language
    title = get_message(user_id, "share")
    description = get_message(user_id, "share_desc")
    thumb_url = config['share_thumb_url']
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton(text=get_message(user_id, "make_sticker_button"),
                             url="https://t.me/EzStickerBot")
    ]])
    input_message_content = InputTextMessageContent(get_message(
        user_id, "share_text"),
                                                    parse_mode='Markdown')

    # build response and answer query
    results = [
        InlineQueryResultArticle(id="share",
                                 title=title,
                                 description=description,
                                 thumb_url=thumb_url,
                                 reply_markup=markup,
                                 input_message_content=input_message_content)
    ]
    try:
        query.answer(results=results, cache_time=5, is_personal=True)
    # if user waited too long to click result BadRequest is thrown
    except BadRequest as e:
        # only ignore BadRequest errors caused by query being too old
        if e.message == "Query is too old and response timeout expired or query id is invalid":  # noqa
            return
        else:
            raise e


@restricted
@run_async
def file_id_query_received(update: Update, context: CallbackContext):
    # get query
    query = update.inline_query
    user_id = query.from_user.id
    results = None

    try:
        file = bot.get_file(query.query)

        _id = uuid.uuid4()
        title = get_message(user_id, "your_sticker")
        desc = get_message(user_id, "forward_desc")
        caption = "@EzStickerBot"
        results = [
            InlineQueryResultCachedDocument(_id,
                                            title,
                                            file.file_id,
                                            description=desc,
                                            caption=caption)
        ]

        query.answer(results=results, cache_time=5, is_personal=True)
    # if file_id wasn't found show share option
    except TelegramError:
        share_query_received(update, context)


@restricted
@run_async
def icon_cancel_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)

    # set make_icon in user_data to false
    context.user_data['make_icon'] = False

    query.edit_message_text(text=get_message(user_id, "icon_canceled"),
                            reply_markup=None)
    query.answer()


@restricted
@run_async
def inline_result_chosen(update: Update, context: CallbackContext):
    chosen_result = update.chosen_inline_result
    result_id = chosen_result.result_id

    global config
    # if was a share increase count by one
    if result_id == 'share':
        config['times_shared'] += 1


@restricted
@run_async
def invalid_command(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    message.reply_text(get_message(message.chat_id, "invalid_command"))


@restricted
@run_async
def invalid_content(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')

    message.reply_text(get_message(message.chat_id, "cant_process"))
    message.reply_markdown(get_message(message.chat_id, "send_sticker_photo"))


def do_fucking_nothing(update: Update, context: CallbackContext):
    pass


# commands


@restricted
@run_async
def broadcast_command(update: Update, context: CallbackContext):
    message = update.message
    chat_id = message.chat_id

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


@restricted
@run_async
def change_lang_command(update: Update, context: CallbackContext):
    message = update.message
    ordered_langs = [None] * len(lang)
    for lang_code in lang.keys():
        ordered_langs[int(lang[lang_code]['order'])] = lang_code
    keyboard = [[]]
    row = 0
    for lang_code in ordered_langs:
        if len(keyboard[row]) == 3:
            row += 1
            keyboard.append([])
        keyboard[row].append(
            InlineKeyboardButton(lang[lang_code]['lang_name'],
                                 callback_data="lang:{}".format(lang_code)))
    markup = InlineKeyboardMarkup(keyboard)
    message.reply_text(get_message(message.chat_id, "select_lang"),
                       reply_markup=markup)


@restricted
@run_async
def donate_command(update: Update, context: CallbackContext):
    message = update.message
    message_text = get_message(
        message.chat_id, "donate"
    ) + "\n\n*Paypal:* {}\n*CashApp:* {}\n*BTC:* `{}`\n*ETH:* `{}`".format(
        config['donate_paypal'], config['donate_cashapp'],
        config['donate_btc'], config['donate_eth'])
    message.reply_markdown(message_text, disable_web_page_preview=True)


@restricted
@run_async
def help_command(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    message.reply_text(get_message(message.chat_id, "help"))


@restricted
@run_async
def icon_command(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')

    # set make_icon to True in user_data
    context.user_data['make_icon'] = True

    # create keyboard with cancel button
    keyboard = [[
        InlineKeyboardButton(get_message(message.chat_id, "cancel"),
                             callback_data="icon_cancel")
    ]]
    markup = InlineKeyboardMarkup(keyboard)

    # if user has not been sent icon info message send it
    if not get_user_config(message.chat_id, 'icon_warned'):
        message.reply_markdown(
            get_message(message.chat_id, "icon_command_info"))

        global users
        users[str(message.chat_id)]['icon_warned'] = True

    message.reply_markdown(get_message(message.chat_id, "icon_command"),
                           reply_markup=markup)


@restricted
@run_async
def info_command(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    keyboard = [[
        InlineKeyboardButton(get_message(message.chat_id, "contact_dev"),
                             url=config['contact_dev_link']),
        InlineKeyboardButton(get_message(message.chat_id, "source"),
                             url=config['source_link'])
    ],
                [
                    InlineKeyboardButton(get_message(message.chat_id, "rate"),
                                         url=config['rate_link']),
                    InlineKeyboardButton(get_message(message.chat_id, "share"),
                                         switch_inline_query="share")
                ]]
    markup = InlineKeyboardMarkup(keyboard)
    message.reply_markdown(get_message(message.chat_id,
                                       "info").format(config['uses']),
                           reply_markup=markup)


@restricted
@run_async
def lang_stats_command(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')

    # get message header
    lang_stats_message = get_message(message.chat_id, "lang_stats")

    # count lang usage
    langs = [user['lang'] for user in users.values()]
    lang_usage = dict(Counter(langs))

    sorted_usage = [
        (code, lang_usage[code])
        for code in sorted(lang_usage, key=lang_usage.get, reverse=True)
    ]

    # create stats message entries
    message_lines = {}
    for code, count in sorted_usage:
        lang_stats_message += "\n" + u"\u200E" + "{}: {:,}".format(
            lang[code]['lang_name'], count)

    # compile stats message in order
    for index in range(0, len(lang)):
        try:
            lang_stats_message += message_lines[str(index)]
        # Skip langs with 0 users
        except KeyError:
            continue

    # send message
    message.reply_markdown(lang_stats_message)


@restricted
@run_async
def log_command(update: Update, context: CallbackContext):
    message = update.message

    # check if user is admin
    if message.from_user.id in config['admins']:
        # feedback to show bot is processing
        bot.send_chat_action(message.chat_id, 'upload_document')

        # send log file as document
        log_file_path = os.path.join(directory, 'ez-sticker-bot.log')
        with open(log_file_path, 'rb') as log_document:
            try:
                message.reply_document(log_document)
            # if log file is empty throws BadRequest exception
            except BadRequest:
                message.reply_text(get_message(message.chat_id, "empty_log"))
            log_document.close()

    else:
        # feedback to show bot is processing
        bot.send_chat_action(message.chat_id, 'typing')

        message.reply_text(get_message(message.chat_id, "no_permission"))


@restricted
@run_async
def opt_command(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')

    # get user opt_in status
    global users
    user_id = str(message.from_user.id)
    opt_in = get_user_config(user_id, "opt_in")

    command = message.text.split(' ')[0][1:].lower()
    if command == 'optin':
        if opt_in:
            message.reply_text(get_message(user_id, "already_opted_in"))
        else:
            users[user_id]['opt_in'] = True
            message.reply_text(get_message(user_id, "opted_in"))
    else:
        if not opt_in:
            message.reply_text(get_message(user_id, "already_opted_out"))
        else:
            users[user_id]['opt_in'] = False
            message.reply_text(get_message(user_id, "opted_out"))


@restricted
def restart_command(update: Update, context: CallbackContext):
    message = update.message

    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    if message.from_user.id in config['admins']:
        message.reply_text(get_message(message.chat_id, "restarting"))
        save_files()
        logger.info("Bot restarted by {} ({})".format(
            message.from_user.first_name, message.from_user.id))
        os.execl(sys.executable, sys.executable, *sys.argv)
    else:
        message.reply_text(get_message(message.chat_id, "no_permission"))


@restricted
@run_async
def start_command(update: Update, context: CallbackContext):
    message = update.message
    # feedback to show bot is processing
    bot.send_chat_action(message.chat_id, 'typing')
    message.reply_markdown(get_message(message.chat_id, "start"))


@restricted
@run_async
def stats_command(update: Update, context: CallbackContext):
    message = update.message
    user_id = message.chat_id

    # feedback to show bot is processing
    bot.send_chat_action(user_id, 'typing')

    opted_in = 0
    opted_out = 0
    for user in users.values():
        if user['opt_in']:
            opted_in += 1
        else:
            opted_out += 1

    personal_uses = get_user_config(user_id, "uses")
    stats_message = get_message(user_id, "stats").format(
        config['uses'], len(users), personal_uses, config['langs_auto_set'],
        config['times_shared'], opted_in + opted_out, opted_in, opted_out)
    message.reply_markdown(stats_message)


# spam filter


def record_use(user_id, context: CallbackContext):
    # ensure user_id is string
    user_id = str(user_id)

    # ensure user_id has list in recent_uses
    global recent_uses
    if user_id not in recent_uses:
        recent_uses[user_id] = []

    job = context.job_queue.run_once(remove_use,
                                     config['spam_interval'],
                                     context=(user_id, datetime.now()))
    recent_uses[user_id].append(job)


def remove_use(context: CallbackContext):
    job = context.job
    user_id = job.context[0]
    global recent_uses
    recent_uses[user_id].remove(job)


def user_on_cooldown(user_id):
    # ensure user_id is string
    user_id = str(user_id)

    recent_uses_count = len(
        recent_uses[user_id]) if user_id in recent_uses else 0
    on_cooldown = recent_uses_count >= config['spam_max']

    if on_cooldown:
        oldest_job_time = recent_uses[user_id][0].context[1]
        seconds_left = int(config['spam_interval'] -
                           (datetime.now() - oldest_job_time).total_seconds())
        time_left = divmod(seconds_left, 60)
    else:
        time_left = 0, 0

    # check to make sure on_cooldown is true while time_left evaluated to 0, 0
    if time_left[0] == 0 and time_left[1] == 0:
        on_cooldown = False

    return on_cooldown, time_left[0], time_left[1]


#  utils


@run_async
def broadcast_thread(context: CallbackContext):
    # check that message was included with the job obj
    if context.job.context is None:
        print("Broadcast thread created without message stored in job context")
        return

    global config
    index = 0
    for user_id in list(users):
        # check if user is opted in
        opt_in = get_user_config(user_id, "opt_in")

        # catch any errors thrown by users who have stopped bot
        try:
            if opt_in and not config['override_opt_out']:
                bot.send_message(chat_id=int(user_id),
                                 text=context.job.context,
                                 parse_mode='HTML',
                                 disable_web_page_preview=True)
                # send opt out message
                if config['send_opt_out_message']:
                    bot.send_message(chat_id=int(user_id),
                                     text=get_message(user_id, "opt_out_info"))
        except Unauthorized:
            pass
        except TelegramError as e:
            # ignore errors from bot trying to message user who has not
            # messaged them first
            if e.message != 'Chat not found':
                logger.warning(
                    "Error '{}' when broadcasting message to {}".format(
                        e.message, user_id))

        index += 1
        if index >= config['broadcast_batch_size']:
            time.sleep(config['broadcast_batch_interval'])
            index = 0


def donate_suggest(user_id):
    user_uses = users[str(user_id)]['uses']
    if user_uses % config['donate_suggest_interval'] == 0:
        bot.send_message(user_id,
                         get_message(user_id,
                                     "donate_suggest").format(user_uses),
                         parse_mode='Markdown')


def get_message(user_id, message):
    lang_pref = get_user_config(user_id, "lang")

    # if message doesn't have translation in user's language default to english
    if message not in lang[lang_pref]:
        lang_pref = 'en'

    return lang[lang_pref][message]


def get_user_config(user_id, key):
    global users
    user_id = str(user_id)

    # if user not registered register with default values
    if user_id not in users:
        users[user_id] = config['default_user'].copy()

        # attempt to automatically set language
        lang_code = bot.get_chat(user_id).get_member(
            user_id).user.language_code.lower()
        if lang_code is not None:
            for code in lang.keys():
                if lang_code.startswith(code):
                    users[user_id]['lang'] = code
                    if code != 'en':
                        config['langs_auto_set'] += 1
    # if user is registered but does not have requested key set to
    # default value from config
    elif key not in users[user_id]:
        try:
            users[user_id][key] = config['default_user'][key].copy()
        # if value isn't a type with a copy function like a string or int
        except AttributeError:
            users[user_id][key] = config['default_user'][key]

    # return value
    return users[user_id][key]


# logs bot errors thrown
def handle_error(update: Update, context: CallbackContext):
    # prevent spammy errors from logging
    if context.error in ("Forbidden: bot was blocked by the user",
                         "Timed out"):
        return
    logger.warning('Update "{}" caused error "{}"'.format(
        update, context.error))


def load_lang():
    path = os.path.join(directory, 'lang.json')
    data = json.load(codecs.open(path, 'r', 'utf-8-sig'))
    return data


def load_json(file_name):
    file_path = os.path.join(
        directory,
        file_name if file_name.endswith('.json') else file_name + '.json')
    with open(file_path) as json_file:
        data = json.load(json_file)
    json_file.close()
    return data


def save_json(json_obj, file_name):
    data = json.dumps(json_obj)
    file_path = os.path.join(
        directory,
        file_name if file_name.endswith('.json') else file_name + '.json')
    with open(file_path, "w") as json_file:
        json_file.write(
            simplejson.dumps(simplejson.loads(data), indent=4, sort_keys=True))
    json_file.close()


def load_files():
    try:
        global config
        config = load_json('config.json')
    except FileNotFoundError:
        sys.exit("config.json is missing; exiting")
    try:
        global lang
        lang = load_lang()
    except FileNotFoundError:
        sys.exit("lang.json is missing; exiting")
    try:
        global users
        users = load_json('users.json')
    except FileNotFoundError:
        # if users.json is missing create an empty file and continue
        save_json({}, 'users.json')


def save_files(context: CallbackContext = None):
    save_json(config, 'config.json')
    save_json(users, 'users.json')


def temp_dir():
    temp_path = os.path.join(directory, 'temp')
    if not os.path.exists(temp_path):
        os.mkdir(temp_path)
    return temp_path


if __name__ == '__main__':
    main()
