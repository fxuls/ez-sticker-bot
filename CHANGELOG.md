# Change Log

All notable changes to this project will be documented in this file.

* * *

## [v3.0](https://github.com/fxuls/ez-sticker-bot/releases/tag/v3.0) [2020-6-5]

**Added:**
- Add language support for Turkish 🇹🇷
- Add language support for Chinese Mandarin Traditional 🇹🇼
- Add language support for Chinese Mandarin Simplified 🇨🇳
- Add spam limit feature
- Add `/donate` command
- Add periodic suggestion to donate after using bot
- Add support for getting animated stickers as .TGS files
- Add a persistent log file and `/log` command (admin only) to access it
- Add `requirements.txt` file
- Add functions for loading and saving json files

**Changed:**
- Update bot to work with python-telegram-bot API 12.7 and Telegram Bot API 4.8
- Move all persistent user data from config['users'] to users.json
- Create temp directory to store temporarily downloaded files when manipulating photos
- Change bot to send `uploading document` message when uploading stickers
- Rename variables to be more semantically correct

**Fixed:**
- Fix mistakes in translations in multiple languages
- Add better exception handling in multiple instances
- Fixed bug that would not convert stickers sent to the bot to png
- Make broadcast thread skip users who have blocked the bot
- Fix automatic language detection to work with language codes of any length

**Removed:**
- Remove unnecessary sleeps when creating stickers to improve speed
- Remove unnecessary checks for escaped new line characters when loading lang.json

## [v2.3](https://github.com/fxuls/ez-sticker-bot/releases/tag/v2.3) [2019-6-6]

**Added:**
- Add language support for Polish 🇵🇱
- Add language support for Dutch 🇳🇱
- Add creating pack icons with `/icon`
- Add personal uses and times shared to `/stats`

**Changed:**
- Combine all stats to single `/stats` command
- Change most functions to run in parallel to speed up response times
- Reformat entire file to be more logically organized
- Move links to config file

**Fixed:**
- Remove unused strings

## [v2.2](https://github.com/fxuls/ez-sticker-bot/releases/tag/v2.2) [2018-12-19]

**Added:**
- Add language support for Arabic 🇸🇦

**Changed:**
- Changed most functions to run async so the bot can process multiple requests at the same time

## [v2.1](https://github.com/fxuls/ez-sticker-bot/releases/tag/v2.1) [2018-12-3]

**Added:**
- Add language support for Indonesian 🇮🇩

**Fixed:**
- Add missing strings for Persian

## [v2.0](https://github.com/fxuls/ez-sticker-bot/releases/tag/v2.0) [2018-11-24]

**Added:**
- Add automatic language detection when a user first starts the bot
- Add tracking for how many times language was automatically set to something other than English for a new user
- Add ability to opt in/out of receiving messages sent with `/broadcast`
- Add a forward button to the stickers sent back by bot which allows users to forward the files via inline
- Add the ability to send images to be converted via URL
- Add `/allstats` command to display additional stats about users and usage
- Add language support for Português 🇧🇷
- Add list of dependencies in README.md

**Changed:**
- Increase number of buttons per row in language keyboard from 2 to 3
- Add country flag after names of languages
- Improve organization of source code
- Restructure config file so it can store more individual user settings than just language

**Fixed:**
- Added all missing strings for all languages so messages should never be missing and default to English
- Fix missing punctuation and markdown in translations
- Improve quality of Spanish translation

**Removed:**
- Remove Chinese simplified translation as Telegram is blocked and unpopular in China where simplified is most used

## [v1.3.2](https://github.com/fxuls/ez-sticker-bot/releases/tag/v1.3.2) [2018-10-2]

**Added:**
- Add missing Slovenian, German, and Italian strings

**Changed:**
- Change bot.send_message to message.reply_text and message.reply_markdown for better readability
- Change translation credits to use full names as links instead of usernames
- Change slovenian translation credit string to credit user who translated missing strings
- Change german translation credit string to credit user who translated missing strings

**Removed:**
- Remove error handling when converting .webp files that have no transparent background to png. The error that caused this was fixed in the image processing library's quarterly update yesterday
- Remove unnecessary specification of positional arguments
- Remove deleted account from spanish translation credit string

## [v1.3.1](https://github.com/fxuls/ez-sticker-bot/releases/tag/v1.3.1) [2018-9-7]

**Changed:**
- Rename dump_variables() to save_config() because there are no other data files besides config.json
- Rename some variables in load_config() and save_config() to make more sense with what they're used for

**Fixed:**
- Fix a bug that caused the converted file to sometimes have a side length of 511 instead of 512 due to a floating point rounding error

**Removed:**
- Remove the do_fucking_nothing() function which was only there for testing purposes and should have never made it to release
- Remove an unnecessary variable in load_config()


## [v1.3](https://github.com/fxuls/ez-sticker-bot/releases/tag/v1.3) [2018-8-29]

**Added:**
- Add userid tokens in translation credit messages
- Add README.md, LICENSE.md, and CHANGELOG.md

**Changed:**
- Make translator credit messages always have current username or name if no username
- Close config file immediately after working with it to prevent file from being wiped if server restarts or bot is stopped

**Fixed:**
- Many spelling/formatting mistakes in lang file (ie. grammar, extra spaces, random punctuation)


## [v1.2.1](https://github.com/fxuls/ez-sticker-bot/commit/f36d10cceb8e54287da7b247db24997ac2249543) [2018-8-8]

**Changed:**
- Make large numbers automatically formatted with commas
- Change all string formatting to use .format() instead of %
- Update lang file to work with .format()


## [v1.2](https://github.com/fxuls/ez-sticker-bot/commit/5536afe1d79c816b6105d0f28f03a00ac63f138d) [2018-5-21]

**Added:**
- Add share button under `/info`
- Add language support for Italian 🇮🇹 and Ukrainian 🇺🇦

**Changed:**
- Change `/langstats` to display in descending order

**Fixed:**
- Fix alignment of RTL characters under `/langstats`
- Fix bug that caused bot to signal sending photo... at inappropriate times


## [v1.1](https://github.com/fxuls/ez-sticker-bot/commit/54df5c31a6ef4e7d1d33eb23829500fc77bc8491) [2018-4-19]

**Added:**
- Add `/broadcast` command which sends replied to message to all users
- Add `/langstats` command
- Add support for images with transparent backgrounds (must be sent as file)
- Add language support for Slovenian 🇸🇮 and Spanish 🇪🇸
- Add @EzStickerBot in file caption to allow users to quickly return to bot after forwarding

**Changed:**
- Make bot messages that do not have translations in user's set language default to English
- Change bot messages in all languages to reflect Telegram increasing the maximum sticker file size to 512kb
- Make the bot send the converted file in reply to the original image/sticker
- Combine `/users` and `/uses` into `/stats`
