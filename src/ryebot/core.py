import logging

from custom_mwclient import WikiAuth, WikiggClient

from ryebot.bot import Bot
from ryebot.errors import WrongUserError, WrongWikiError
from ryebot.scripts.testscript import testscript


logger = logging.getLogger(__name__)


def ryebot_core():
    """Login to the wiki and run the desired script."""
    login()
    if Bot.scriptname_to_run == "testscript":
        testscript()
    else:
        raise RuntimeError(f'unknown script name "{Bot.scriptname_to_run}"')


def login():
    """Login to wiki and set the `Bot.site` attribute."""
    targetwiki = "terraria"
    logger.info("Logging in to wiki...")

    wiki_auth = WikiAuth.from_env("RYEBOT_USERNAME", "RYEBOT_PASSWORD")
    site = WikiggClient(targetwiki, credentials=wiki_auth)  # this is the actual login

    # --- validate wikiname post-login ---
    wiki_id = site.get_current_wiki_name()
    if wiki_id != targetwiki:
        raise WrongWikiError(targetwiki, wiki_id, site.host)

    # --- validate username post-login ---
    expected_user = wiki_auth.username
    if expected_user:
        # strip the botpassword identifier
        expected_user = expected_user.split('@', maxsplit=1)[0]
    wiki_user = site.username.replace(' ', '_')
    if wiki_user != expected_user:
        raise WrongUserError(expected_user, wiki_user)

    # --- validations successful ---
    logger.info(
        f'Logged in to wiki "{wiki_id}" ({site.host}) with user "{wiki_user}".'
    )

    Bot.site = site

