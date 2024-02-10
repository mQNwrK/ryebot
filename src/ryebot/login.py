from importlib import metadata
import logging

from custom_mwclient import WikiAuth, WikiggClient

from ryebot.errors import LoginError


logger = logging.getLogger(__name__)

USER_AGENT = (
    f'ryebot/{metadata.version(__package__)} (https://github.com/mQNwrK/ryebot; '
    'https://terraria.wiki.gg/wiki/User_talk:Ryebot)'
)


def login(lang: str = "en"):
    """Login to wiki and return the `WikiggClient` object."""
    targetwiki = "terraria" + (f"/{lang}" if lang != "en" else '')
    wiki_auth = WikiAuth.from_env('RYEBOT_USERNAME', 'RYEBOT_PASSWORD')
    # --- perform actual login ---
    site = WikiggClient("terraria", lang=lang, credentials=wiki_auth, clients_useragent=USER_AGENT)  # this is the actual login

    # --- validate wikiname post-login ---
    wikiname = site.get_current_wiki_name()
    if wikiname != targetwiki:
        raise LoginError(targetwiki, f'actual wiki is "{wikiname}" ({site.host})')

    # --- validate username post-login ---
    expected_user = wiki_auth.username
    if expected_user:
        # strip the botpassword identifier
        expected_user = expected_user.split('@', maxsplit=1)[0]
    wiki_user = site.username.replace(' ', '_')
    if wiki_user != expected_user:
        raise LoginError(
            targetwiki,
            f'logged in as "{wiki_user}" but expected "{expected_user}"'
        )

    # --- validations successful ---
    logger.info(f'Logged in to wiki "{wikiname}" ({site.host}) with user "{wiki_user}".')
    return site
