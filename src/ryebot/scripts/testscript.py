import logging
import random
import time

from ryebot.bot import Bot


logger = logging.getLogger(__name__)


def script_main():
    logger.info("Started testscript.")
    limit = 10
    period = 7
    target_page = 'User:Rye Greenwood/Sandbox25'
    summary = Bot.summary('')
    i = -1
    while i < limit - 1:
        i += 1

        # prepare the new page text
        page = Bot.site.pages[target_page]  # page is now an mwclient.Page object
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
            Bot.site.save(page, text, summary=summary, minor=True)
            logger.info(f'Saved page "{page.name}" with summary "{summary}".')

        # sleep until next loop iteration
        logger.info(f"Sleeping for {period} seconds...")
        time.sleep(period)
        logger.info("Woke up.")
