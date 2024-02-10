import copy
from importlib import metadata
import logging
from pprint import pformat

from custom_mwclient import WikiAuth, WikiggClient

from ryebot.errors import LoginError


logger = logging.getLogger(__name__)

USER_AGENT = (
    f'ryebot/{metadata.version(__package__)} (https://github.com/mQNwrK/ryebot; '
    'https://terraria.wiki.gg/wiki/User_talk:Ryebot)'
)


def login(targetwiki: str = 'terraria/en'):
    """Login to the `targetwiki` and return the `WikiggClient` object."""
    wiki_auth = WikiAuth.from_env('RYEBOT_USERNAME', 'RYEBOT_PASSWORD')

    kwargs = {
        'wikiname': targetwiki,
        'credentials': wiki_auth,
        'clients_useragent': USER_AGENT
    }
    if '/' in targetwiki:
        kwargs['wikiname'], kwargs['lang'] = targetwiki.split('/', maxsplit=1)

    # --- perform actual login ---
    try:
        site = WikiggClient(**kwargs)
    except Exception as exc:
        raise LoginError(targetwiki, str(exc)) from exc

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

    # --- validate that the user is not blocked ---
    if site.blocked:
        raise LoginError(
            targetwiki,
            'user "{}" is blocked (by: {}; reason: "{}")'.format(wiki_user, *site.blocked)
        )

    # --- validations successful ---
    logger.info(f'Logged in to wiki "{wikiname}" ({site.host}) with user "{wiki_user}".')

    site_for_log = copy.deepcopy(site)
    site_for_log.credentials = '***REDACTED***'
    logger.debug(pformat(vars(site_for_log)))

    return site
