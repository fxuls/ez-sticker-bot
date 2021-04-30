import codecs
import json
import os
import simplejson

ROOT_DIR = os.path.abspath(os.curdir)
LANG_PATH = "lang.json"
CONFIG_PATH = "config.json"

# returns json data from file at file_path
def load_json(file_path):
    path = os.path.join(ROOT_DIR, file_path)
    with codecs.open(path, 'r', 'utf-8-sig')as json_file:
        json_data = json.load(json_file)
    json_file.close()
    return json_data


# saves json_data to file at file_path
def save_json(json_data, file_path):
    data = json.dumps(json_data)
    file_path = os.path.join(ROOT_DIR, file_path)
    with open(file_path, "w") as json_file:
        json_file.write(simplejson.dumps(simplejson.loads(data), indent=4, sort_keys=True))
    json_file.close()


config_data = load_json(CONFIG_PATH)
lang_data = load_json(LANG_PATH)


# save all files to disk
def save():
    save_json(config_data, CONFIG_PATH)
