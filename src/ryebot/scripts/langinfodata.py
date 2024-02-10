import logging
import re

import mwparserfromhell
import requests

from ryebot.bot import Bot
from ryebot.errors import ScriptRuntimeError
from ryebot.login import login
from ryebot.stopwatch import Stopwatch


logger = logging.getLogger(__name__)


def script_main():
    logger.info("Started langinfodata.")
    Bot.site = login()

    summary = Bot.summary("[[User:Ryebot/bot/scripts/langinfodatac|Updated]].")
    data_template_name = "Template:Language info/datagen"
    target_module_name = "Module:Language info/data"

    # most recent langinfodata
    template_output = _read_data_template(data_template_name)

    # validate template output
    _error_if_is_too_small(data_template_name, template_output, 800)

    # get Page object for the existing langinfodata module
    module_page = _get_page_safely(target_module_name)

    if _no_actual_changes(template_output, module_page):
        logger.info(
            "No changes to be made.",
            extra = {
                "head": "No changes",
                "body": "The database appears to be up-to-date."
            }
        )
        return

    if Bot.dry_run:
        logger.info(f'Would save page "{module_page.name}" with summary "{summary}".')
    else:
        stopwatch = Stopwatch()
        try:
            saveresult = Bot.site.save(module_page, template_output, summary=summary, minor=True)
        except Exception:
            logger.exception(
                "Error while saving:",
                extra = {
                    "head": f'Didn\'t save the update of "{module_page.name}"',
                    "body": (
                        "Couldn't save the page due to some error; check the "
                        "logs for details."
                    )
                }
            )
        else:
            stopwatch.stop()
            diff_id = saveresult.get("newrevid")
            diff_link = Bot.site.fullurl(diff=diff_id) if diff_id else None
            logger.info(
                (
                    f'Saved page "{module_page.name}" with summary "{summary}". '
                    f"Diff: {diff_link if diff_link else 'None'}. Time: {stopwatch}"
                ),
                extra = {"head": "Updated successfully"}
            )


def _read_data_template(data_template_name: str):
    """Return the parsed output of the template."""
    pagetext = _get_page_safely(data_template_name).text()
    interwikis = _get_interwikis()

    # read the contents of all <onlyinclude> tags and concat them,
    # proceed with this wikicode
    wikicode = mwparserfromhell.parse(''.join([
        str(t.contents) for t in mwparserfromhell.parse(pagetext).ifilter_tags(
            matches=lambda t: str(t.tag) == "onlyinclude"
        )
    ]))

    # expand all the templates in the wikicode in separate API calls (because
    # the {{language info/luadata}} expansions are really large and expanding
    # them all at once usually causes an error).
    # skip #time parser functions for now, those should be expanded at the
    # very end (so that the times are up-to-date)
    for t in wikicode.ifilter_templates(
        recursive=False,  # recursive=True causes some issues for whatever reason, not needed anyways
        matches=lambda t: not str(t.name).startswith('#time:')
    ):
        api_result = None
        # check if the template has an interwiki prefix (e.g. "{{de:Language info/luadata}}")
        if ':' in t.name:
            # split into e.g. "de", "Language info/luadata"
            possible_iwprefix, real_template_name = t.name.split(':', 1)
            if possible_iwprefix in interwikis:
                # template does have an interwiki prefix, so expand the template on that wiki
                t.name = real_template_name  # update template name
                url = interwikis[possible_iwprefix].replace("wiki/$1", '') + "api.php"
                response = requests.get(url, params={
                    "action": "expandtemplates",
                    "text": str(t),
                    "prop": "wikitext",
                    "title": f"Template:{t.name}",
                    "format": "json",
                })
                response.raise_for_status()
                api_result = response.json()
                logger.info(f'Expanded "Template:{t.name}" on {possible_iwprefix}.')
        if api_result is None:
            # template is a normal, on-wiki template, so simply expand it here
            api_result = Bot.site.api(
                "expandtemplates",
                text=str(t),
                prop="wikitext",
                title=data_template_name
            )
        expanded_template = api_result.get("expandtemplates", {}).get("wikitext")
        if expanded_template is not None:
            # replace the template call in the wikicode with the expanded template
            wikicode.replace(t, expanded_template)

    # now expand all #time parser functions
    for t in wikicode.ifilter_templates(matches=lambda t: str(t.name).startswith("#time:")):
        api_result = Bot.site.api("expandtemplates", prop="wikitext", text=str(t))
        expanded_template = api_result.get("expandtemplates", {}).get("wikitext")
        if expanded_template is not None:
            # replace the template call in the wikicode with the expanded template
            wikicode.replace(t, expanded_template)

    # strip all <nowiki> tags
    for t in wikicode.ifilter_tags(matches=lambda t: str(t.tag) == "nowiki"):
        wikicode.replace(t, t.contents)

    return str(wikicode)


def _get_interwikis():
    """Return all interwiki links to off-wiki sites, along with their URLs."""
    api_result = Bot.site.api("query", meta="siteinfo", siprop="interwikimap")
    iwmap = api_result.get("query", {}).get("interwikimap")
    if iwmap is not None:
        return dict(map(
            # discard all interwikis that don't have a "trans" key and extract
            # the "prefix" and "url" from the other ones, so that we get a list like
            # ["de", "fr", "tmods"] (also discard "en" since it's not a real interwiki)
            lambda i: (i["prefix"], i["url"]),
            filter(lambda i: "trans" in i and i["prefix"] != "en", iwmap)
        ))


def _error_if_is_too_small(template_name: str, template_output: str, minimum_chars: int):
    """Raise an error if the template output is too small (less than `minimum_chars` characters).

    The database is very large, so if the template output is very small, then
    it's likely that an error occurred.
    """

    if len(template_output) >= minimum_chars:
        return  # is not too small, all is well
    errorstr = (
        f'Output length of "{template_name}" is <{minimum_chars}, most likely '
        "erroneously."
    )
    logger.error(
        errorstr,
        extra = {
            "head": "Content of the data template is unexpectedly small",
            "body": (
                f'The output of "{template_name}" is only {len(template_output)} '
                f"characters long, which is less than the threshold of "
                f"{minimum_chars} characters. It is very likely that an error "
                "occurred."
            )
        }
    )
    raise ScriptRuntimeError(errorstr)


def _get_page_safely(pagename: str):
    """Safely get the `mwparserfromhell.Page` object for the `pagename`."""
    try:
        return Bot.site.pages[pagename]
    except Exception:
        errorstr = f'Reading "{pagename}" failed'
        logger.exception(
            f'Error while reading "{pagename}":',
            extra = {
                "head": errorstr,
                "body": (
                    "Couldn't fetch the page due to some error; check the logs "
                    "for details."
                )
            }
        )
        raise ScriptRuntimeError(errorstr)


def _no_actual_changes(new_data_text: str, data_page):
    """Check if there is an actual difference in data between new and old.

    It is possible that the `new_data_text` merely has a new order of lines,
    or perhaps additional or removed blank lines. In this case, the actual
    data of the database does not change, so the save can be skipped.
    """

    try:
        current_data_text = data_page.text()
    except Exception:
        logger.exception(f'Error while reading "{data_page}":')
        logger.warning(
            "Skipped pre-save check for changes.",
            extra = {
                "head": "Skipped intelligent checking for trivial changes",
                "body": (
                    "Couldn't check if there are actual changes to be made in "
                    f'the database module because reading "{data_page.name}" '
                    "failed due to some error (check the logs for details). "
                    "Will now forcibly save the module, even if it's just for "
                    "a change in line order."
                )
            }
        )
        return False  # cannot perform check, so assume that there *are* changes

    # we don't want to compare every single line but only the relevant data lines,
    # because e.g. the timestamp will always be different
    linepattern = re.compile(r"(?m)^({})$".format(
        r'info\[".+?"\]\[".+?"\] ?= ?".+"'  # pattern for matching a database entry line
    ))

    current_data_lines = [match.group() for match in re.finditer(linepattern, current_data_text)]
    new_data_lines = [match.group() for match in re.finditer(linepattern, new_data_text)]

    logger.debug("current_data_lines:")
    _ = [logger.debug(l) for l in current_data_lines]
    logger.debug("new_data_lines:")
    _ = [logger.debug(l) for l in new_data_lines]

    return sorted(current_data_lines) == sorted(new_data_lines)
