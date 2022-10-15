import logging

from ryebot.bot import Bot
from ryebot.login import login
from ryebot.scripts.testscript import testscript


logger = logging.getLogger(__name__)


def ryebot_core():
    """Login to the wiki and run the desired script."""
    Bot.site = login()
    if Bot.scriptname_to_run == "testscript":
        testscript()
    else:
        raise RuntimeError(f'unknown script name "{Bot.scriptname_to_run}"')
