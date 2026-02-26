import logging

from custom_mwclient import WikiClient
from mwclient.errors import InsufficientPermission, InvalidPageTitle, ProtectedPageError
from mwclient.page import Page

from ryebot.stopwatch import Stopwatch
from ryebot.errors import ScriptRuntimeError


logger = logging.getLogger(__name__)


def get_page_and_text(site: WikiClient, pagename: str) -> 'tuple[Page, str]':
    """Safely get the `Page` object and its text for the `pagename`."""
    logstr = f'Error while reading "{pagename}":'
    errorstr = f'Reading "{pagename}" failed'
    common_body_str = "Couldn't fetch the page due to some error; check the logs for details."

    # safely fetch page object
    try:
        page: Page = site.pages[pagename]
    except InvalidPageTitle:
        logger.exception(
            logstr,
            extra = {
                "head": errorstr,
                "body": "The page title is invalid; check the logs for details."
            }
        )
        raise
    except Exception:
        logger.exception(logstr, extra={"head": errorstr, "body": common_body_str})
        raise ScriptRuntimeError(errorstr)

    # safely fetch page text
    try:
        pagetext = page.text()
    except InsufficientPermission:
        logger.exception(
            logstr,
            extra = {
                "head": errorstr,
                "body": "Permission to read the page is denied."
            }
        )
        raise
    except Exception:
        logger.exception(logstr, extra={"head": errorstr, "body": common_body_str})
        raise ScriptRuntimeError(errorstr)

    return page, pagetext


def save_page(site: WikiClient, dry_run: bool, page: Page, pagetext: str, summary: str, minor: bool = True, loglevel: int = logging.INFO):
    """Save the `Page` object with the new `pagetext` and `summary`."""
    summary_str = 'no summary' if summary is None else f'summary "{summary}"'
    if dry_run:
        chardiff_str = f"{len(pagetext) - (page.length or 0):+} diff"
        logger.log(
            loglevel,
            f'Would save page "{page.name}" ({len(pagetext)} characters, '
            f'{chardiff_str}) with {summary_str}.'
        )
    else:
        warningstr = f'Did not save the page "{page.name}"'
        stopwatch = Stopwatch()
        try:
            saveresult = site.save(page, pagetext, summary, minor)
        except ProtectedPageError as exc:
            if exc.code:
                logstr = (
                    f'Editing the page "{page.name}" is not allowed (error code: '
                    f'"{exc.code}"), skipped it.'
                )
            else:
                logstr = f'Page "{page.name}" is protected, skipped it.'
            if exc.info:
                bodystr = "Couldn't save the page due to the following reason: " + exc.info
            else:
                bodystr = "Couldn't save the page because it is protected."
            logger.warning(logstr, extra={"head": warningstr, "body": bodystr})
        except Exception:
            logger.exception("Error while saving:")
            logger.warning(
                f'Skipped page "{page.name}" due to error.',
                extra = {
                    "head": warningstr,
                    "body": (
                        f"Couldn't save the page due to some error; "
                        "check the logs for details."
                    )
                }
            )
        else:
            stopwatch.stop()
            diff_id = saveresult.get("newrevid")
            diff_link = site.fullurl(diff=diff_id) if diff_id else None
            logger.log(
                loglevel,
                f'Saved page "{page.name}" with {summary_str}. '
                f"Diff: {diff_link}. Time: {stopwatch}"
            )


def parse_wikitext(site: WikiClient, wikitext: str):
    """Return the parsing result of the `wikitext`."""
    api_result = site.api("expandtemplates", prop="wikitext", text=wikitext)
    return api_result.get("expandtemplates", {}).get("wikitext")
