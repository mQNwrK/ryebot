import datetime
import logging
import time
from typing import Iterable, Literal

from ryebot.bot import Bot
from ryebot.login import login
from ryebot.wiki_util import get_page, save_page


logger = logging.getLogger(__name__)


# Since some point between 2023-08-21 and 2023-09-15, the Cloudflare in
# front of wiki.gg's servers issues a "challenge" (a CAPTCHA meant to
# be solved by a human) along with an "Error 429: Too Many Requests"
# after about 60 requests have been made in rapid succession.
# https://developers.cloudflare.com/firewall/cf-firewall-rules/cloudflare-challenges/#detecting-a-challenge-page-response
CLOUDFLARE_SAFETY_DELAY: float = 8  # in seconds


def script_main():
    logger.info(f'Started {Bot.scriptname_to_run}.')
    Bot.site = login()

    summary = Bot.summary('[[User:Ryebot/bot/scripts/capsredirects|Updated]].')
    output_page_name = 'User:Rye Greenwood/util/Capitalization redirects'

    redirects_info = _get_all_redirects()
    for redirect_page_id, target_title in _get_redirect_target_lookup().items():
        if redirect_page_id in redirects_info:
            redirects_info[redirect_page_id]['target'] = target_title
        else:
            logger.debug(
                f'Redirect page ID {redirect_page_id} not found in list from '
                '"allredirects".'
            )
    filtered_redirects = _filter_capitalization_redirects(redirects_info)
    output = _make_output(filtered_redirects, len(redirects_info))

    output_page = get_page(Bot.site, output_page_name)
    save_page(Bot.site, Bot.dry_run, output_page, output, summary, minor=True)


def _get_all_redirects():
    """Return a dict with each redirect page ID and its page title."""
    redirects_info: dict[int, dict[Literal['title'], str]] = {}

    api_parameters = {
        'generator': 'allredirects',
        'garnamespace': '0',
        'garlimit': 'max',
        'prop': 'info',
    }

    logger.info(f'Fetching redirects...')

    while True:
        api_result = Bot.site.api('query', **api_parameters)
        api_result_pagelist: dict = api_result.get('query', {}).get('pages', {})
        for page in api_result_pagelist.values():
            if page['ns'] == 0:
                redirects_info[page['pageid']] = dict(title=page['title'])
        if api_result.get('continue') is None:
            # no need to continue, we're done with this batch
            break
        # add the 'garcontinue' and 'continue' keys to the query for the next batch
        api_parameters.update(api_result.get('continue'))
        logger.info(
            f'{len(redirects_info)} fetched so far. Continuing with '
            f'"{api_parameters.get('garcontinue', '').split('|')[0]}"...'
        )
        time.sleep(CLOUDFLARE_SAFETY_DELAY)

    logger.info(f'Fetched all {len(redirects_info)} redirects.')

    return redirects_info


def _get_redirect_target_lookup():
    """Return a dict with each redirect page ID and its target page title."""
    redirect_target_lookup: dict[int, str] = {}

    api_parameters = {
        'list': 'allredirects',
        'arnamespace': '0',
        'arlimit': 'max',
        'arprop': 'ids|title',
    }

    logger.info('Fetching the targets of all redirects...')

    while True:
        api_result = Bot.site.api('query', **api_parameters)
        api_result_pagelist: dict = api_result.get('query', {}).get('allredirects', [])
        for target in api_result_pagelist:
            redirect_target_lookup[target['fromid']] = target['title']
        if api_result.get('continue') is None:
            # no need to continue, we're done with this batch
            break
        # add the 'arcontinue' and 'continue' keys to the query for the next batch
        api_parameters.update(api_result.get('continue'))
        logger.info(
            f'{len(redirect_target_lookup)} fetched so far. Continuing with '
            f'"{api_parameters.get('arcontinue', '').split('|')[0]}"...'
        )
        time.sleep(CLOUDFLARE_SAFETY_DELAY)

    logger.info(f'Fetched the targets of {len(redirect_target_lookup)} redirects.')

    return redirect_target_lookup


def _filter_capitalization_redirects(redirects_info: dict[int, dict[Literal['title', 'target'], str]]):
    for target_and_title in redirects_info.values():
        if target_and_title['target'].lower() == target_and_title['title'].lower():
            yield target_and_title


def _make_output(pagelist: Iterable[dict[Literal['title', 'target'], str]], total_redirect_count: int):
    tablerows = []
    for target_and_title in pagelist:
        tablerows.append((
            '<tr>'
                '<td>'
                    '{0[title]} '
                    '{{{{dotlist|inline=y|class=small|paren=y'
                        '|[[Special:PageHistory/{0[title]}|hist]]'
                        '|[[Special:WhatLinksHere/{0[title]}|links]]'
                    '}}}}'
                '</td>'
                '<td>→</td>'
                '<td>[[{0[target]}]]</td>'
            '</tr>'
        ).format(target_and_title))
    tablerows.sort()

    now = datetime.datetime.now(datetime.UTC).strftime('%d %B %Y, %H:%M:%S') + ' (UTC)'
    output = (
        f'The following {len(tablerows)} redirects (out of '
        f'{total_redirect_count} total) in mainspace are capitalization '
        'variants of their respective target page. The data was generated on '
        f'{now}.\n\n'
    )
    output += (
        '<table class="terraria sortable">\n'
            '<tr>'
                '<th>Redirect</th>'
                '<th class="unsortable"></th>'
                '<th>Target</th>'
            '</tr>\n'
            f'{'\n'.join(tablerows)}'
        '\n</table>'
    )
    return output




"""
def _get_all_redirects():

    redirects_info = {}

    api_parameters = {
        'generator': 'allredirects',
        'garnamespace': '0',
        'garlimit': 'max',
        'prop': 'info|linkshere',
        'lhnamespace': '*',
        'lhlimit': '100',
    }

    logger.info(f'Fetching redirects...')

    while True:
        api_result = Bot.site.api('query', **api_parameters)
        linkshere_limit: int = api_result.get('limits', {}).get('linkshere', -1)
        api_result_pagelist: dict = api_result.get('query', {}).get('pages', {})
        for page in api_result_pagelist.values():
            linkshere = len(page['linkshere'])
            if linkshere == linkshere_limit:
                linkshere = f'≥ {linkshere}'
            else:
                linkshere = str(linkshere)
            redirects_info[page['pageid']] = {
                'title': page['title'],
                'linkshere': linkshere,
            }

        if api_result.get('continue') is None:
            # no need to continue, we're done with this batch
            break
        # add the 'arcontinue' and 'continue' keys to the query for the next batch
        api_parameters.update(api_result.get('continue'))
        time.sleep(CLOUDFLARE_SAFETY_DELAY)

    return redirects_info
"""

if __name__ == "__main__":
    script_main()
