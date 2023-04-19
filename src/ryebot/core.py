import logging

from ryebot.bot import Bot
from ryebot.login import login
from ryebot.scripts import scriptfunctions


logger = logging.getLogger(__name__)


def ryebot_core():
    """Login to the wiki and run the desired script."""
    Bot.site = login()
    if Bot.scriptname_to_run in scriptfunctions:
        Bot.script_output = ''
        scriptfunctions[Bot.scriptname_to_run]()
    else:
        raise RuntimeError(
            f'unknown script name "{Bot.scriptname_to_run}"; see "python3 -m '
            'ryebot --help"'
        )
