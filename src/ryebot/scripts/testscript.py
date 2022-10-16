import logging
import random
import time

from ryebot.bot import Bot
from ryebot.script_configuration import ScriptConfiguration
from ryebot.stopwatch import Stopwatch


logger = logging.getLogger(__name__)


DEFAULT_CONFIG = {
    "period": 7,
    "limit": 100,
    "target_page": "User:Rye Greenwood/Sandbox25"
}


def script_main():
    logger.info("Started testscript.")
    config = ScriptConfiguration("testscript", DEFAULT_CONFIG)
    logger.info(config)
    logger.info(config.is_default())
    config.update_from_wiki()
    logger.info(config)
    logger.info(config.is_default())

    summary = Bot.summary('')
    i = -1
    while i < config["limit"] - 1:
        i += 1

        # prepare the new page text
        page = Bot.site.pages[config["target_page"]]  # page is now an mwclient.Page object
        new_random_number = random.randint(0, 1)
        text = page.text() + ' ' + str(new_random_number)
        logger.info(f'Loop iteration #{i}. Adding number: {new_random_number}')

        # save the new page text
        if Bot.dry_run:
            logger.info(
                f'Would save page "{page.name}" ({len(text)} characters) with '
                f'summary "{summary}".'
            )
        else:
            stopwatch = Stopwatch()
            saveresult = Bot.site.save(page, text, summary=summary, minor=True)
            stopwatch.stop()
            logger.info(
                f'Saved page "{page.name}" with summary "{summary}". '
                f"Diff ID: {saveresult.get('newrevid')}. Time: {stopwatch}"
            )

        # sleep until next loop iteration
        logger.info(f"Sleeping for {config['period']} seconds...")
        time.sleep(config["period"])
        logger.info("Woke up.")
