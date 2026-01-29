import copy
import math
import logging
import time

from custom_mwclient import WikiClient
from mwclient.errors import InvalidPageTitle, ProtectedPageError, APIError
from mwclient.page import Page
from requests.exceptions import HTTPError

from ryebot.bot import Bot
from ryebot.errors import LoginError, ScriptRuntimeError
from ryebot.login import login
from ryebot.script_configuration import ScriptConfiguration
from ryebot.stopwatch import Stopwatch


logger = logging.getLogger(__name__)


DEFAULT_CONFIG = {
    "wikis": "de",
    "categories": "",
    "pages": "Module:Exclusive/data"
}


# Since some point between 2023-08-21 and 2023-09-15, the Cloudflare in
# front of wiki.gg's servers issues a "challenge" (a CAPTCHA meant to
# be solved by a human) along with an "Error 429: Too Many Requests"
# after about 60 requests have been made in rapid succession.
# https://developers.cloudflare.com/firewall/cf-firewall-rules/cloudflare-challenges/#detecting-a-challenge-page-response
CLOUDFLARE_SAFETY_DELAY: float = 15  # in seconds


def script_main():
    logger.info(f"Started {Bot.scriptname_to_run}.")
    Bot.site = login()

    config = ScriptConfiguration("langsync", DEFAULT_CONFIG)
    config.set_from_wiki()
    config.set_from_string(Bot.config_from_commandline)

    # ------------- Get wiki names from config, validate them -------------
    wikis = _validate_wikis_from_config(config["wikis"])
    if not wikis:
        logger.info("No valid wikis to sync to. Terminated with no changes.")
        return
    logger.info("Wikis to sync to: " + str(wikis))

    # ------------- Get page names from config, validate them -------------
    # get pages from category config
    pages_base = _get_pages_from_category_cfg(config["categories"])

    # get pages from page config
    pages_base |= _get_pages_from_page_cfg(config["pages"])

    pagenames_for_log = [pages_base[pageid]['title_en'] for pageid in pages_base.keys()]
    logger.info(f"Pages to sync (base): {sorted(pagenames_for_log)}")

    # handle language-specific config
    pages: dict[str, dict[str, dict]] = {}  # key: wiki language, value: page dicts
    pageorders: dict[str, list[str]] = {}  # key: wiki language, value: page IDs
    for wiki in wikis:
        pages[wiki] = copy.deepcopy(pages_base)

        # syncnot
        syncnot_from_config = list(_str_to_set(config.get(f'{wiki}:syncnot', ''), ';'))
        syncnot_pageids = set(_pagetitles_to_ids(syncnot_from_config))
        current_pageids = set(pages[wiki].keys())
        for pageid_to_remove in current_pageids & syncnot_pageids:
            del pages[wiki][pageid_to_remove]

        # syncalso
        syncalso_from_config = list(_str_to_set(config.get(f'{wiki}:syncalso', ''), ';'))
        pages[wiki] |= _get_info_for_titles(syncalso_from_config)

        # lang targetpages
        for pageid, pageinfo in pages[wiki].items():
            # default to EN if the targetpage is not set in the config
            pageinfo['title_lang'] = config.get(f'{wiki}:{pageinfo["title_en"]}', pageinfo["title_en"])

        pageorders[wiki] = sorted(pages[wiki].keys(), key=lambda pageid: pages[wiki][pageid]['title_en'])
        pagenames_for_log = [pages[wiki][pageid]['title_en'] for pageid in pageorders[wiki]]
        logger.info(f"Pages to sync ({wiki}) ({len(pages[wiki])}): {pagenames_for_log}")

    if sum([len(wiki) for wiki in pages.values()]) == 0:
        logger.info(
            "Didn't retrieve any information about pages to sync. Terminated "
            "with no changes."
        )
        return

    # ------------- Save pages on langwikis -------------
    saveresults: dict[str, list[tuple[str, dict, Stopwatch]]] = {}
    for wiki in wikis:
        logger.info('+' * 40 + ' ' + wiki.upper())
        try:
            site = login("terraria/" + wiki)
        except LoginError:
            logger.exception(
                f"Skipped {wiki.upper()} because logging in to it failed:",
                extra = {
                    "head": f"Couldn't sync any pages to {wiki.upper()}!",
                    "body": f"Logging in to {wiki.upper()} failed."
                }
            )
            continue
        Bot.other_sites[wiki] = site

        titles_lang = [p['title_lang'] for p in pages[wiki].values()]
        normalized_titles = _normalize_page_titles(titles_lang, site)

        # fetch the texts of the pages on this wiki
        langpages_info = _get_info_for_titles(titles_lang, site)
        for pageid, pagedata in pages[wiki].items():
            normalized_title = normalized_titles[pagedata['title_lang']]
            pagedata['title_lang_normalized'] = normalized_title.get('title', pagedata['title_lang'])
            langpage_info = langpages_info.get(normalized_title.get('id'))
            if langpage_info:
                pagedata['text_lang'] = langpage_info['text']
            pagedata['needs_sync'] = pagedata['text'] != pagedata.get('text_lang')

        total = len(pages[wiki])
        w = math.ceil(math.log10(total))  # greatest number of digits, for formatting

        for i, pageid in enumerate(pageorders[wiki]):
            page = pages[wiki][pageid]
            sourcepage_name = page['title_en']
            targetpage_name = page['title_lang_normalized']
            targetpage_for_log = sourcepage_name
            if targetpage_name != sourcepage_name:
                targetpage_for_log += f" -> {targetpage_name}"
            logger.info(f"{i+1: {w}}/{total}: {targetpage_for_log}")

            if not pages[wiki][pageid]['needs_sync']:
                continue

            scriptlink = '[[:en:User:Ryebot/bot/scripts/langsync|sync]]'
            summary = Bot.summary(f"{scriptlink} :: en revid:{page['revid']}::")

            # fetch the page from the target wiki
            try:
                targetpage = site.pages[targetpage_name]
            except Exception:
                logger.exception(f'Error while reading "{targetpage_name}" on {wiki}:')
                logger.warning(
                    "Skipped page due to error.",
                    extra = {
                        "head": f'Did not sync "{wiki}:{targetpage_name}"',
                        "body": (
                            f"Couldn't read the page on {wiki} due to some error; "
                            "check the logs for details."
                        )
                    }
                )
                continue
            logger.debug(f"Sleeping to avoid Cloudflare challenge: {CLOUDFLARE_SAFETY_DELAY} sec")
            time.sleep(CLOUDFLARE_SAFETY_DELAY)
            didntsave_text = f'Did not sync "{wiki}:{targetpage.name}"'

            pagetext = page['text']

            if Bot.dry_run:
                chardiff = len(pagetext) - (targetpage.length or 0)
                chardiff_str = '+' if chardiff > 0 else ''
                chardiff_str += f"{chardiff} diff"
                logger.info(
                    f'Would save page "{targetpage.name}" on {wiki} '
                    f"({len(pagetext)} characters, {chardiff_str}) with "
                    f'summary "{summary}".'
                )
            else:
                stopwatch = Stopwatch()
                saveresult = None
                try:
                    saveresult = site.save(targetpage, pagetext, summary=summary, minor=True)
                except ProtectedPageError:
                    logger.warning(
                        "Page is protected, skipped it.",
                        extra = {
                            "head": didntsave_text,
                            "body": "Couldn't save the page because it is protected."
                        }
                    )
                except APIError as error:
                    logger.exception("Error while saving:")
                    if (
                        not targetpage.exists
                        and targetpage.contentmodel == "Scribunto"
                        and page["contentmodel"] == "wikitext"
                        and error.code == "scribunto-lua-error-location"
                    ):
                        # targetpage is a non-existent "Module:" page but the
                        # content is wikitext (most likely: documentation page
                        # of a module), which throws a Lua error.
                        # retry the page creation with forcing the contentmodel
                        # to wikitext.
                        logger.info(
                            'Re-trying to create this "Module:" page by forcing '
                            'the content model to "wikitext".'
                        )

                        # restart the save timer
                        stopwatch.stop()
                        stopwatch.start()
                        try:
                            saveresult = site.save(targetpage, pagetext, summary=summary, minor=True, contentmodel="wikitext")
                        except Exception:
                            logger.exception("Error while saving:")
                            logger.warning(
                                "Skipped page due to error.",
                                extra = {
                                    "head": didntsave_text,
                                    "body": (
                                        "Couldn't save the page due to some error; "
                                        "check the logs for details."
                                    )
                                }
                            )
                        else:
                            logger.warning(
                                (
                                    f'Created "{wiki}:{targetpage.name}" with a '
                                    'forced contentmodel of "wikitext".'
                                ),
                                extra = {
                                    "head": f'Possibly created "{wiki}:{targetpage.name}" incorrectly',
                                    "body": (
                                        "Creating the page normally caused a Lua "
                                        "error, so it was created with a forced "
                                        'content model of "wikitext". This might '
                                        'be wrong as the page is in the "Module:" '
                                        "namespace. Please check it manually to "
                                        "ensure everything is in order."
                                    )
                                }
                            )
                    else:
                        logger.warning(
                            "Skipped page due to error.",
                            extra = {
                                "head": didntsave_text,
                                "body": (
                                    "Couldn't save the page due to some error; "
                                    "check the logs for details."
                                )
                            }
                        )
                except Exception:
                    logger.exception("Error while saving:")
                    logger.warning(
                        "Skipped page due to error.",
                        extra = {
                            "head": didntsave_text,
                            "body": (
                                "Couldn't save the page due to some error; "
                                "check the logs for details."
                            )
                        }
                    )
                if saveresult is not None:
                    stopwatch.stop()
                    logger.info(
                        f'Saved page "{targetpage.name}" with summary "{summary}". '
                        f"Diff ID: {saveresult.get('newrevid')}. Time: {stopwatch}"
                    )
                    saveresult_tuple = (sourcepage_name, saveresult, stopwatch)
                    saveresults.setdefault(wiki, []).append(saveresult_tuple)

    logger.info("Completed syncing to all wikis.")
    Bot.script_output = format_saveresults(saveresults)


def format_saveresults(saveresults: dict[str, list[tuple[str, dict, Stopwatch]]]):
    table_total = (
        "| Wiki | Pages<br/>synced | Pages<br/>changed |\n"
        "| --- | ---: | ---: |\n"
    )
    if len(saveresults) == 0:
        return table_total

    details_tables = []
    for wiki, pagesaves in saveresults.items():
        pages_synced = len(pagesaves)
        pages_changed = 0
        details_table = (
            f"<details><summary><b>{wiki.upper()}</b></summary>\n\n"
            "| English page | Language wiki page | Diff | Time |\n"
            "| --- | --- | --- | --- |"
        )
        for en_pagename, saveresult, stopwatch in pagesaves:
            nochange = 'newrevid' not in saveresult
            details_table += (
                f"\n| [{en_pagename}]({Bot.site.fullurl(title=en_pagename)}) "
                f"| [{saveresult['title']}]"
                f"({Bot.other_sites[wiki].fullurl(curid=saveresult['pageid'])}) "
            )
            if nochange:
                details_table += "| [null edit] "
            else:
                pages_changed += 1
                details_table += (
                    f"| [{saveresult['newrevid']}]"
                    f"({Bot.other_sites[wiki].fullurl(diff=saveresult['newrevid'])}) "
                )
            details_table += f"| {stopwatch} |"
        details_table += "\n</details>"
        details_tables.append(details_table)
        table_total += (
            f"| [`{wiki.upper()}`]"
            f"({Bot.other_sites[wiki].fullurl(title='Special:Contribs/Ryebot')})"
            f"| {pages_synced} | {pages_changed} |\n"
        )
    return (
        "### Total\n"
        + table_total
        + "\n### Details\n"
        + '\n'.join(details_tables)
    )


def _validate_wikis_from_config(wikis_from_config: str) -> list[str]:
    logger.debug("Raw wikis string in config: " + wikis_from_config)
    wikis_from_config = _str_to_set(wikis_from_config)
    logger.debug(f"Wikis from config parsed as list: {sorted(wikis_from_config)}")
    # get dynamic if list if possible, this hardcoded list is the fallback
    valid_wikis = {"de", "fr", "hu", "ko", "ru", "pl", "pt", "uk", "zh"}
    is_hardcoded = False
    try:
        api_result = Bot.site.get('expandtemplates', text='{{langList|offWiki}}', prop='wikitext')
        valid_wikis = api_result['expandtemplates']['wikitext']
    except Exception:
        is_hardcoded = True
        logger.exception("Fetching the off-wiki list failed:")
        logger.info("Using the potentially outdated hardcoded list.")
    else:
        valid_wikis = _str_to_set(valid_wikis)
    logger.debug("Valid wikis: " + str(sorted(valid_wikis)))
    if not wikis_from_config <= valid_wikis:
        dismissed = str(sorted(wikis_from_config - valid_wikis))
        logger.debug(f"The following wikis from the config are dismissed: {dismissed}")
        if is_hardcoded:
            logger.warning(
                f"Using the hardcoded list and dismissed {len(dismissed)} wikis.",
                extra = {
                    "head": "One or more wikis might be ignored unexpectedly",
                    "body": (
                        "The following wiki(s) from the config are ignored: "
                        f"{dismissed}. They might be incorrectly regarded as "
                        "invalid, because the most recent off-wiki list couldn't "
                        "be downloaded."
                    )
                })
    return sorted(valid_wikis & wikis_from_config)


def _get_pages_from_category_cfg(categories_from_config: str):
    """Return data for all pages in all of the categories defined in config."""
    logger.debug("Raw categories string in config: " + categories_from_config)
    categories_from_config = _str_to_set(categories_from_config, ';')
    logger.debug(
        f"Categories from config parsed as list: ({len(categories_from_config)}) "
        f"{sorted(categories_from_config)}"
    )
    return _get_info_for_categorymembers(categories_from_config)


def _get_info_for_categorymembers(categorynames: 'list[str]'):
    """Return page content and revision ID for each member of each category.

    Return a dict where the key is the page's ID and the value is another dict
    with the page name (normalized), current text content, and current revision ID.
    Ignore non-existent pages and invalid titles.

    >>> _get_info_for_titles(['Category:Terraria Wiki'])
    {
        '1': {
            'title_en': 'Main Page',
            'text': 'Lorem ipsum',
            'revid': '987654',
            'contentmodel': 'wikitext'
        }
    }
    """

    raw_pageinfo = {}

    for categoryname in categorynames:

        api_parameters = {
            'generator': 'categorymembers',
            'gcmtitle': categoryname,
            'gcmtype': 'page',  # do not include files nor subcategories
            'gcmlimit': 'max',
            'prop': 'revisions',
            'rvslots': 'main',
            'rvprop': 'ids|content|contentmodel'
        }

        while True:
            api_result = Bot.site.api('query', **api_parameters)
            api_result_pagelist: dict = api_result.get('query', {}).get('pages', {})
            # merge the data for each page with the existing data
            # (this is necessary because it seems we don't receive every attribute
            # in one query; e.g. in some queries we only get the page's revison ID
            # but not its content)
            for pageid, pagedata in api_result_pagelist.items():
                raw_pageinfo.setdefault(pageid, {})  # ensure the key for this page exists
                raw_pageinfo[pageid].update(pagedata)  # merge

            if api_result.get('continue') is None:
                # no need to continue, we're done with this batch
                break
            # add the 'rvcontinue' and 'continue' keys to the query for the next batch
            api_parameters.update(api_result.get('continue'))

    page_texts_and_ids = {}
    for pagedata in raw_pageinfo.values():
        page_texts_and_ids[str(pagedata['pageid'])] = {
            'title_en': pagedata['title'],
            'text': pagedata['revisions'][0]['slots']['main']['*'],
            'revid': pagedata['revisions'][0]['revid'],
            'contentmodel': pagedata['revisions'][0]['slots']['main']['contentmodel']
        }

    return page_texts_and_ids


def _get_pages_from_page_cfg(pages_from_config: str):
    """Return page info for all pages defined in config, skipping non-existent ones."""
    logger.debug("Raw pages string in config: " + pages_from_config)
    pages_from_config = _str_to_set(pages_from_config, ';')
    logger.debug(
        f"Pages from config parsed as list: ({len(pages_from_config)}) "
        f"{sorted(pages_from_config)}"
    )
    return _get_info_for_titles(list(pages_from_config))


def _get_info_for_titles(pagetitles: 'list[str]', site: WikiClient | None = None):
    """Return page content and revision ID for each page in the `pagetitles`.

    Return a dict where the key is the page's ID and the value is another dict
    with the page name (normalized), current text content, and current revision ID.
    Ignore non-existent pages and invalid titles.

    >>> _get_info_for_titles(['project:foo'])
    {
        '123': {
            'title_en': 'Terraria Wiki:Foo',
            'text': 'Lorem ipsum',
            'revid': '987654',
            'contentmodel': 'wikitext'
        }
    }
    """

    if site is None:
        site = Bot.site


    raw_pageinfo = {}

    for titles_slice in chunked(pagetitles):

        api_parameters = {
            'titles': '|'.join(titles_slice),
            'prop': 'revisions',
            'rvslots': 'main',
            'rvprop': 'ids|content|contentmodel'
        }

        while True:
            api_result = site.api('query', **api_parameters)
            api_result_pagelist: dict = api_result.get('query', {}).get('pages', {})
            # merge the data for each page with the existing data.
            # this is necessary because it seems we don't receive every attribute
            # in one query; e.g. in some queries we only get the page's revison ID
            # but not its content.
            # when that is the case, the following warning is emitted: "This
            # result was truncated because it would otherwise be larger than the
            # limit of 8,388,608 bytes.")
            for pageid, pagedata in api_result_pagelist.items():
                raw_pageinfo.setdefault(pageid, {})  # ensure the key for this page exists
                raw_pageinfo[pageid].update(pagedata)  # merge

            if api_result.get('continue') is None:
                # no need to continue, we're done with this batch
                break
            # add the 'rvcontinue' and 'continue' keys to the query for the next batch
            api_parameters.update(api_result.get('continue'))

    page_texts_and_ids = {}
    for pageid, pagedata in raw_pageinfo.items():
        if int(pageid) > 0:
            page_texts_and_ids[str(pagedata['pageid'])] = {
                'title_en': pagedata['title'],
                'text': pagedata['revisions'][0]['slots']['main']['*'],
                'revid': pagedata['revisions'][0]['revid'],
                'contentmodel': pagedata['revisions'][0]['slots']['main']['contentmodel']
            }

    return page_texts_and_ids


def _pagetitles_to_ids(titles: 'list[str]'):
    """Return the page IDs of the `titles` and disregard missing pages and invalid titles."""
    for titles_slice in chunked(titles):
        api_result = Bot.site.post('query', titles='|'.join(titles_slice))
        api_result_pagelist: dict = api_result['query']['pages']
        for pageid in api_result_pagelist.keys():
            if int(pageid) > 0:
                yield pageid


def _normalize_page_titles(titles: 'list[str]', site: WikiClient = None):
    """Normalize all the `titles`.

    Return a dict where each `title` has a dict with page ID and normalized title.
    Missing pages and invalid titles will have an empty dict.

    >>> _normalize_page_titles(['Template:Yes', 'nonexistentpage'], <DEwiki>)
    {
        'Template:Yes': {
            'id': 12345,
            'title': 'Vorlage:Yes'
        },
        'nonexistentpage': {}
    }
    """

    site = site or Bot.site

    pagetitles_to_ids = dict.fromkeys(titles, {})
    for titles_slice in chunked(titles):
        api_result = site.post('query', titles='|'.join(titles_slice))
        # convert the "normalized" list from the API response.
        # original format: [ {'from': 'foo', 'to': 'Foo' } ]
        # target format: {'Foo': 'foo'}
        normalized = api_result['query'].get('normalized', [])
        normalized = dict([reversed(norm.values()) for norm in normalized])
        api_result_pagelist: dict = api_result['query']['pages']
        for pageid, pagedata in api_result_pagelist.items():
            if int(pageid) > 0:
                pagetitle = pagedata['title']
                original_title = normalized.get(pagetitle, pagetitle)
                pagetitles_to_ids[original_title] = {
                    'id': pageid,
                    'title': pagetitle
                }
    return pagetitles_to_ids


def chunked(list_to_chunk, limit_low: int = 50, limit_high = 500):
    """Split the list into equal-sized chunks (sub-lists).

    The size of the chunks (`limit_low` or `limit_high`) depends on the
    `apihighlimits` user right of the current user. The chunks are returned as a
    generator.
    """

    limit = limit_high if 'apihighlimits' in Bot.site.rights else limit_low
    for slicestart in range(0, len(list_to_chunk), limit):
        yield list_to_chunk[slicestart:slicestart+limit]


def _str_to_set(input_str: str, delimiter: str = ','):
    """Turn the `input_str` into a set.

    Split the string (on `delimiter`) into unique values and strip leading and
    leading whitespace from each one. Discard empty values.
    """

    return set([s.strip() for s in input_str.split(delimiter)]) - {''}
