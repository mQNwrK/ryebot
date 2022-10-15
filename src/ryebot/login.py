import logging

from custom_mwclient import WikiAuth, WikiggClient

from ryebot.errors import WrongUserError, WrongWikiError


logger = logging.getLogger(__name__)


def login(lang: str = "en"):
    """Login to wiki and return the `WikiClient` object."""
    targetwiki = "terraria" + (f"/{lang}" if lang != "en" else '')
    logger.info(f'Logging in to wiki "{targetwiki}"...')

    wiki_auth = WikiAuth.from_env("RYEBOT_USERNAME", "RYEBOT_PASSWORD")
    site = WikiggClient("terraria", lang=lang, credentials=wiki_auth)  # this is the actual login

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
    return site
