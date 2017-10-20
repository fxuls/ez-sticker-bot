import json
import logging
import os
import sys

from PIL import Image
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters

# setup logger
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

config = None

def start(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')
    start_message = "Hello! I'm *EZ Sticker Bot*. I can help you make stickers! Type /help to " \
                    "get started or /info to get information about me."
    bot.send_message(chat_id=update.message.chat_id, text=start_message, parse_mode='Markdown')


def help_command(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')
    help_message = "To add a sticker to a pack with @Stickers, your file must be saved in png format, have at least " \
                   "one dimension of 512px, and be less than 350Kb.\n\nYou can send me any photo or sticker, and I " \
                   "will format it to meet all three requirements and send it back to you as a file ready to be added to your " \
                   "pack!"
    bot.send_message(chat_id=update.message.chat_id, text=help_message)


def send_uses_count(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')
    bot.send_message(chat_id=update.message.chat_id,
                     text="I've created *%d* stickers for people so far!" % config['uses'], parse_mode='Markdown')


def main():
    get_config()
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

    # register media listener
    dispatcher.add_handler(MessageHandler((Filters.photo | Filters.sticker), image_sticker_received))
    dispatcher.add_handler(MessageHandler(Filters.all, invalid_content))

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
                      caption='Forward this to @Stickers')

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
    bot.send_message(chat_id=update.message.chat_id, text="I can't process that content.")
    bot.send_message(chat_id=update.message.chat_id, text="Send me a *photo* or *sticker*.", parse_mode='Markdown')


def bot_info(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')
    text = "*EZ Sticker Bot* is a bot that I develop and host with no expectation of ever gaining anything from it " \
           "other than the satisfaction of helping fellow Telegram users.\n\nSharing this bot in your groups/channels " \
           "would help people make their own great sticker packs for us all to use!\n\nI've created *%d* stickers for people so far!" % \
           config['uses']
    keyboard = [[InlineKeyboardButton("Contact dev", url="https://t.me/BasedComrade"),
                 InlineKeyboardButton("Source", url="https://github.com/BasedComrade/ez-sticker-bot")],
                [InlineKeyboardButton("Rate ⭐⭐⭐⭐⭐", url="https://telegram.me/storebot?start=ezstickerbot")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(chat_id=update.message.chat_id, text=text, parse_mode='Markdown', reply_markup=reply_markup)

def restart_bot(bot, update):
    if update.message.from_user.id in config['admins']:
        bot.send_message(chat_id=update.message.chat_id, text="Restarting bot...")
        dump_variables()
        os.execl(sys.executable, sys.executable, *sys.argv)


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
