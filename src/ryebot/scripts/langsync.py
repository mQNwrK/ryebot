import math
import logging

from mwclient.errors import InvalidPageTitle, ProtectedPageError
from mwclient.page import Page

from ryebot.bot import Bot
from ryebot.login import login
from ryebot.script_configuration import ScriptConfiguration
from ryebot.stopwatch import Stopwatch


logger = logging.getLogger(__name__)


DEFAULT_CONFIG = {
    "wikis": "de",
    "categories": "",
    "pages": "Module:Exclusive/data"
}


def script_main():
    logger.info("Started langsync.")
    config = ScriptConfiguration("langsync", DEFAULT_CONFIG)
    config.update_from_wiki()

    # ------------- Get wiki names from config, validate them -------------
    wikis = _validate_wikis_from_config(config["wikis"])
    if not wikis:
        logger.info("No valid wikis. Terminated with no changes.")
        return
    logger.info("Wikis to sync to: " + str(wikis))

    # ------------- Get page names from config, validate them -------------
    # get pages from category config
    pages_base = _get_pages_from_category_cfg(config["categories"])

    # get pages from page config
    pages_base += list(_get_pages_from_page_cfg(config["pages"]))

    logger.info(f"Pages to sync (base): {sorted(p.name for p in pages_base)}")

    # handle language-specific cfg
    pages: dict[str, list[Page]] = {}
    targetpages: dict[str, dict[str, str]] = {}
    for wiki in wikis:
        pages[wiki] = pages_base.copy()

        # syncnot
        syncnot_from_config = list(str_to_set(config.get(f'{wiki}:syncnot', ''), ';'))
        for pagename in syncnot_from_config:
            try:
                syncnot_page = Bot.site.pages[pagename]
            except InvalidPageTitle:
                continue
            for page in pages[wiki]:
                if page.name == syncnot_page.name:
                    pages[wiki].remove(page)
                    break

        # syncalso
        syncalso_from_config = list(str_to_set(config.get(f'{wiki}:syncalso', ''), ';'))
        for pagename in syncalso_from_config:
            page = _get_one_page(pagename)
            if page and page.name not in [p.name for p in pages[wiki]]:
                pages[wiki].append(page)

        # lang targetpages
        targetpages[wiki] = dict([
            (p.name, config.get(f'{wiki}:{p.name}', p.name))  # default to EN name if config not set
            for p in pages[wiki]
        ])

        pages[wiki] = sorted(pages[wiki], key=lambda p: p.name)
        logger.info(
            f"Pages to sync ({wiki}) ({len(pages[wiki])}): "
            f"{[p.name for p in pages[wiki]]}"
        )

    if not pages:
        logger.info(
            "Didn't retrieve any information about pages to sync. Terminated "
            "with no changes."
        )
        return

    # ------------- Save pages on langwikis -------------
    saveresults: dict[str, list[tuple[str, dict, Stopwatch]]] = {}
    for wiki in wikis:
        logger.info('+' * 40 + ' ' + wiki.upper())
        site = login(wiki)
        Bot.other_sites[wiki] = site
        pages_to_sync = pages[wiki]
        total = len(pages_to_sync)
        w = math.ceil(math.log10(total))  # greatest number of digits, for formatting

        for i, page in enumerate(pages_to_sync):
            targetpage_name = targetpages[wiki][page.name]
            targetpage_log = page.name
            if targetpage_name != page.name:
                targetpage_log += f" -> {targetpage_name}"
            logger.info(f"{i+1: {w}}/{total}: {targetpage_log}")

            summary = Bot.summary(
                f"[[:en:User:Ryebot/bot/scripts/langsync|sync]] :: en "
                f"revid:{page.revision}::"
            )

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
            didntsave_text = f'Did not sync "{wiki}:{targetpage.name}"'

            # read the English page text
            try:
                pagetext = page.text()
            except Exception:
                logger.exception(f'Error while reading text of "{page.name}" from EN:')
                logger.warning(
                    "Skipped page due to error.",
                    extra = {
                        "head": didntsave_text,
                        "body": (
                            f"Couldn't read the text of \"en:{page.name}\" "
                            "due to some error; check the logs for details."
                        )
                    }
                )
                continue

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
                    stopwatch.stop()
                    logger.info(
                        f'Saved page "{targetpage.name}" with summary "{summary}". '
                        f"Diff ID: {saveresult.get('newrevid')}. Time: {stopwatch}"
                    )
                    saveresults.setdefault(wiki, []).append((page.name, saveresult, stopwatch))

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
    wikis_from_config = str_to_set(wikis_from_config)
    logger.debug(f"Wikis from config parsed as list: {sorted(wikis_from_config)}")
    # get dynamic if list if possible, this hardcoded list is the fallback
    valid_wikis = {"de", "fr", "hu", "ko", "ru", "pl", "pt", "uk", "zh"}
    is_hardcoded = False
    try:
        valid_wikis = Bot.site.expandtemplates('{{langList|offWiki}}')
    except Exception:
        is_hardcoded = True
        logger.exception("Fetching the off-wiki list failed:")
        logger.info("Using the potentially outdated hardcoded list.")
    else:
        valid_wikis = str_to_set(valid_wikis)
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
    """Return `Page` objects for the pages in all categories defined in config."""
    logger.debug("Raw categories string in config: " + categories_from_config)
    categories_from_config = str_to_set(categories_from_config, ';')
    logger.debug(f"Categories from config parsed as list: {sorted(categories_from_config)}")

    if len(categories_from_config) == 0:
        return []

    all_category_members = []
    logger.debug(f"Fetching members of the following categories: {categories_from_config}...")
    for categoryname in categories_from_config:
        try:
            category = Bot.site.categories[categoryname]
        except InvalidPageTitle:
            logger.info(f'Skipped invalid category title "{categoryname}".')
            continue
        category_members = list(category.members())
        logger.debug(
            f"Members of {category.name} ({len(category_members)}): "
            + str([p.name for p in category.members()])
        )
        all_category_members.extend(category_members)
    return all_category_members


def _get_one_page(pagetitle: str):
    """Return a `Page` object, doing logging if impossible."""
    try:
        page = Bot.site.pages[pagetitle]
    except InvalidPageTitle:
        logger.info(f'Skipped invalid page title "{pagetitle}".')
        return
    else:
        if page.exists:
            return page
        else:
            logger.info(f'Skipped non-existent page "{pagetitle}".')


def _get_pages_from_page_cfg(pages_from_config: str):
    """Return `Page` objects for all pages defined in config, skipping non-existent ones."""
    logger.debug("Raw pages string in config: " + pages_from_config)
    pages_from_config = str_to_set(pages_from_config, ';')
    logger.debug(f"Pages from config parsed as list: {sorted(pages_from_config)}")

    if len(pages_from_config) == 0:
        return []

    logger.debug(f"Fetching {len(pages_from_config)} pages from config...")
    for pagename in pages_from_config:
        page = _get_one_page(pagename)
        if page:
            yield page


def str_to_set(input_str: str, delimiter: str = ','):
    """Split the `input_str` into unique values, discarding empty ones."""
    return set([s.strip() for s in input_str.split(delimiter)]) - {''}
