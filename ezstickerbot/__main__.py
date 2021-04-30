from ezstickerbot.files import langs, config


def main():
    print(langs.get("en", "start"))
    print(config.get('uses'))


if __name__ == '__main__':
    main()
