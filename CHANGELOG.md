# Change Log

All notable changes to this project will be documented in this file.

* * *

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
- Add share button under /info
- Add language support for Italian 🇮🇹 and Ukrainian 🇺🇦

**Changed:**
- Change /langstats to display in descending order

**Fixed:**
- Fix alignment of RTL characters under /langstats
- Fix bug that caused bot to signal sending photo... at inappropriate times


## [v1.1](https://github.com/fxuls/ez-sticker-bot/commit/54df5c31a6ef4e7d1d33eb23829500fc77bc8491) [2018-4-19]

**Added:**
- Add /broadcast command which sends replied to message to all users
- Add /langstats command
- Add support for images with transparent backgrounds (must be sent as file)
- Add language support for Slovenian 🇸🇮 and Spanish 🇪🇸
- Add @EzStickerBot in file caption to allow users to quickly return to bot after forwarding

**Changed:**
- Make bot messages that do not have translations in user's set language default to English
- Change bot messages in all languages to reflect Telegram increasing the maximum sticker file size to 512kb
- Make the bot send the converted file in reply to the original image/sticker
- Combine /users and /uses into /stats
