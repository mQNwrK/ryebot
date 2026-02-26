import logging

from ryebot.bot import Bot
from ryebot.login import login
from ryebot.script_configuration import ScriptConfiguration


logger = logging.getLogger(__name__)


DEFAULT_CONFIG = {
    "wikis": "de",
    "categories": "",
    "pages": "Module:Exclusive/data"
}


def script_main():
    logger.info(f"Started {Bot.scriptname_to_run}.")
    Bot.site = login()

    config = ScriptConfiguration("langsynccont", DEFAULT_CONFIG)
    config.set_from_wiki()

    Bot.run_sub_script("langsync", config.to_string())
