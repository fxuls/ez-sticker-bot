import codecs
import json
import logging
import os
import sys

from PIL import Image
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

# setup logger
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

config = None
lang = None

def start(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')
    bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "start"),
                     parse_mode='Markdown')


def help_command(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')
    bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "help"))


def send_uses_count(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')
    bot.send_message(chat_id=update.message.chat_id,
                     text=get_message(update.message.chat_id, "uses") % config['uses'], parse_mode='Markdown')


def main():
    get_config()
    get_lang()
    updater = Updater(config['token'])
    global uses
    uses = config['uses']
    dispatcher = updater.dispatcher

    # register commands
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('help', help_command))
    dispatcher.add_handler(CommandHandler('uses', send_uses_count))
    dispatcher.add_handler(CommandHandler('restart', restart_bot))
    dispatcher.add_handler(CommandHandler('info', bot_info))
    dispatcher.add_handler(CommandHandler('lang', change_lang_command))

    # register media listener
    dispatcher.add_handler(MessageHandler((Filters.photo | Filters.sticker), image_sticker_received))
    dispatcher.add_handler(MessageHandler(Filters.all, invalid_content))

    # register change language button handler
    dispatcher.add_handler(CallbackQueryHandler(change_lang, pattern="lang"))

    # register variable dump loop
    updater.job_queue.run_repeating(dump_variables, 300, 300)

    # register error handler
    dispatcher.add_error_handler(error)

    updater.start_polling()

    updater.idle()


def image_sticker_received(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='upload_photo')

    # get file id
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
    else:
        photo_id = update.message.sticker.file_id

    # download file
    file = bot.get_file(file_id=photo_id)
    temp = file.file_path.split('/')[-1].split('.')
    if len(temp) > 1:
        ext = '.' + file.file_path.split('/')[-1].split('.')[1]
    else:
        ext = '.webp'
    download_path = photo_id + ext
    file.download(custom_path=download_path)

    # process image
    image = Image.open(download_path)
    width, height = image.size
    reference_length = max(width, height)
    ratio = 512 / reference_length
    new_width = int(width * ratio)
    new_height = int(height * ratio)
    image = image.resize((new_width, new_height), Image.ANTIALIAS)
    formatted_path = photo_id + '_formatted.png'
    image.save(formatted_path, optimize=True)

    # send formatted image as a document
    document = open(formatted_path, 'rb')
    bot.send_document(chat_id=update.message.chat_id, document=document, filename='sticker.png',
                      caption=get_message(update.message.chat_id, "forward"))

    # delete local files and close image object
    image.close()
    os.remove(download_path)
    os.remove(formatted_path)

    # increase total uses count by one
    global config
    config['uses'] += 1


def invalid_content(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')
    bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "cant_process"))
    bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "send_sticker_photo"),
                     parse_mode='Markdown')


def bot_info(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')
    keyboard = [
        [InlineKeyboardButton(get_message(update.message.chat_id, "contact_dev"), url="https://t.me/BasedComrade"),
         InlineKeyboardButton(get_message(update.message.chat_id, "source"),
                              url="https://github.com/BasedComrade/ez-sticker-bot")],
        [InlineKeyboardButton(get_message(update.message.chat_id, "rate"),
                              url="https://telegram.me/storebot?start=ezstickerbot")]]
    markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "info") % config['uses'],
                     parse_mode='Markdown', reply_markup=markup)


def restart_bot(bot, update):
    if update.message.from_user.id in config['admins']:
        bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "restarting"))
        dump_variables()
        os.execl(sys.executable, sys.executable, *sys.argv)


def change_lang_command(bot, update):
    keyboard = [[InlineKeyboardButton("English", callback_data="lang:en"),
                 InlineKeyboardButton("Русский", callback_data="lang:ru")]]
    markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "select_lang"),
                     reply_markup=markup)


def change_lang(bot, update):
    query = update.callback_query
    lang_code = query.data.split(':')[-1]
    user_id = query.from_user.id
    global config
    config['lang_prefs'][str(user_id)] = lang_code
    query.edit_message_text(text=get_message(user_id, "lang_set"), reply_markup=None)
    query.answer()


def get_message(user_id, message):
    global config
    user_id = str(user_id)
    if user_id not in config['lang_prefs']:
        config['lang_prefs'][user_id] = 'en'
        lang_pref = 'en'
    else:
        lang_pref = config['lang_prefs'][user_id]
    return lang[lang_pref][message]


def get_lang():
    dir = os.path.dirname(__file__)
    path = os.path.join(dir, 'lang.json')
    data = json.load(codecs.open(path, 'r', 'utf-8-sig'))
    for lang_code in data:
        for message in data[lang_code]:
            data[lang_code][message] = data[lang_code][message].replace('\\n', '\n')
    global lang
    lang = data

def get_config():
    dir = os.path.dirname(__file__)
    path = os.path.join(dir, 'config.json')
    with open(path) as data_file:
        data = json.load(data_file)
    global config
    config = data


def dump_variables(bot=None, job=None):
    data = json.dumps(config)
    dir = os.path.dirname(__file__)
    path = os.path.join(dir, 'config.json')
    with open(path, "w") as f:
        f.write(data)


# logs bot errors thrown
def error(bot, update, error):
    logger.warning('Update "%s" caused error "%s"' % (update, error))


if __name__ == '__main__':
    main()
