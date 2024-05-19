import html
import logging
import re

from ryebot.bot import Bot
from ryebot.errors import ScriptRuntimeError
from ryebot.login import login
from ryebot.stopwatch import Stopwatch


logger = logging.getLogger(__name__)


def script_main():
    logger.info("Started excludata.")
    Bot.site = login()

    summary = Bot.summary("[[User:Ryebot/bot/scripts/excludatac|Updated]].")
    data_template_name = "Template:Exclusive/luadata"
    target_module_name = "Module:Exclusive/data"

    _purge_data_template(data_template_name)
    template_output = _read_data_template(data_template_name)

    # validate template output
    _error_if_is_too_small(data_template_name, template_output, 800)

    # get Page object for the target module
    module_page = _get_target_module_page(target_module_name)

    if _no_actual_changes(template_output, module_page, True):
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
            diff_id = saveresult.get('newrevid')
            diff_link = Bot.site.fullurl(diff=diff_id) if diff_id else None
            logger.info(
                (
                    f'Saved page "{module_page.name}" with summary "{summary}". '
                    f"Diff: {diff_link if diff_link else 'None'}. Time: {stopwatch}"
                ),
                extra = {"head": "Updated successfully"}
            )


def _purge_data_template(data_template_name: str):
    """Purge the source template so that it contains the most recent data."""
    try:
        Bot.site.api("purge", titles=data_template_name)
    except Exception:
        logger.exception(f'Error while purging "{data_template_name}":')
        logger.warning(
            "Proceeding with an outdated version of it.",
            extra = {
                "head": f'Using an outdated version of "{data_template_name}"',
                "body": (
                    "Couldn't purge the template due to some error; check the "
                    "logs for details."
                )
            }
        )
    else:
        logger.info(f'Purged "{data_template_name}".')


def _read_data_template(data_template_name: str):
    """Return the parsed output of the template, trimmed and stripped of unwanted HTML tags."""
    try:
        api_result = Bot.site.api("parse", page=data_template_name, prop="text")
        t_out = api_result['parse']['text']['*']  # template output text
    except Exception:
        errorstr = f'Unable to read "{data_template_name}"'
        logger.exception(
            f'Error while parsing "{data_template_name}":',
            extra = {
                "head": errorstr,
                "body": (
                    "Couldn't parse the template due to some error; check "
                    "the logs for details."
                )
            }
        )
        raise ScriptRuntimeError(errorstr)
    else:
        logger.info(f'Read "{data_template_name}".')

    # replace HTML tags
    t_out = re.sub(r"<br ?\/>", '\n', t_out)  # <br /> tags
    t_out = html.unescape(t_out)  # character references, e.g. "&#32;" or "&gt;"
    t_out = t_out.replace("<p>--", "--")
    t_out = t_out.replace("</p><p>", '')
    t_out = t_out.replace("\n</p>\n", "\n\n")

    # trim to the relevant content
    content_startstring = re.search(r'\n<div class="terraria" style="white-space: pre">', t_out)
    content_endstring = re.search(r"\n}\n\n</div>", t_out)
    if not content_startstring or not content_endstring:
        log_start = (
            "content_startstring: "
            + (content_startstring.span() if content_startstring else 'None')
        )
        log_end = (
            "content_endstring: "
            + (content_endstring.span() if content_endstring else 'None')
        )
        logger.debug(log_start)
        logger.debug(log_end)
        errorstr = (
            f'Error while trimming "{data_template_name}": Couldn\'t find '
            'a suitable start and/or end for the relevant content!'
        )
        logger.error(
            errorstr,
            extra = {
                "head": f'Unable to trim output of "{data_template_name}"',
                "body": (
                    "The format of the template output is unexpected. There "
                    "has probably been a change in the source (check "
                    f"{Bot.site.fullurl(title=data_template_name, action='history')}"
                    ") and this script will likely need to be updated."
                )
            }
        )
        raise ScriptRuntimeError(errorstr)
    t_out = t_out[content_startstring.end():content_endstring.start() + 2]  # actual trimming
    logger.debug(t_out)
    return t_out


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


def _get_target_module_page(module_name):
    """Safely get the `mwparserfromhell.Page` object for the module."""
    try:
        return Bot.site.pages[module_name]
    except Exception:
        errorstr = f'Reading "{module_name}" failed'
        logger.exception(
            f'Error while reading "{module_name}":',
            extra = {
                "head": errorstr,
                "body": (
                    "Couldn't fetch the page due to some error; check the logs "
                    "for details."
                )
            }
        )
        raise ScriptRuntimeError(errorstr)


def _no_actual_changes(new_data_text: str, data_page, safe_mode: bool = False):
    """Check if there is an actual difference in data between new and old.

    It is possible that the `new_data_text` merely has a new order of lines,
    or perhaps additional or removed blank lines. In this case, the actual
    data of the database does not change, so the save can be skipped.

    If an error occurs during the check, e.g. because fetching the current data
    text fails, then it is assumed that changes *did* occur. If `safe_mode` is
    `True`, then the opposite happens: It is assumed that no changes occured.
    `safe_mode` ensures that this function only returns `True` if the check was
    error-free.
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
        # cannot perform check, so assume that there *are* changes (unless `safe_mode`
        # is True: in that case assume that there are no changes)
        return safe_mode

    # we don't want to compare every single line but only the relevant data lines,
    # because e.g. the timestamp will always be different
    linepattern = re.compile(r"(?m)^({})$".format(
        r'\[".+?"\] = \d+,'  # pattern for matching a database entry line
        r"|--\u2002*\d+: [\w\d]+"  # pattern for matching a legend line
    ))

    current_data_lines = [match.group() for match in re.finditer(linepattern, current_data_text)]
    new_data_lines = [match.group() for match in re.finditer(linepattern, new_data_text)]

    logger.debug("current_data_lines:")
    _ = [logger.debug(l) for l in current_data_lines]
    logger.debug("new_data_lines:")
    _ = [logger.debug(l) for l in new_data_lines]

    return sorted(current_data_lines) == sorted(new_data_lines)
