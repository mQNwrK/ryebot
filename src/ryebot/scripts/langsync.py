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

            try:
                targetpage = site.pages[targetpage_name]
            except Exception as exc:
                logger.exception(f'Error while reading "{targetpage_name}" on {wiki}. Skipped it.')
                continue

            pagetext = page.text()
            summary = Bot.summary(
                f"[[:en:User:Ryebot/bot/scripts/langsync|sync]] :: en "
                f"revid:{page.revision}::"
            )
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
                didntsave_text = f'Did not sync "{wiki}:{targetpage.name}"'
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
                        f'Saved page "{page.name}" with summary "{summary}". '
                        f"Diff ID: {saveresult.get('newrevid')}. Time: {stopwatch}"
                    )

    logger.info("Completed syncing to all wikis.")


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
