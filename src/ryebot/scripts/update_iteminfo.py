import logging
import time

from ryebot.bot import Bot
from ryebot.errors import ScriptRuntimeError
from ryebot.login import login
from ryebot.stopwatch import Stopwatch
from ryebot.wiki_util import parse_wikitext, read_page, save_page


logger = logging.getLogger(__name__)


def script_main():
    logger.info("Started update_iteminfo.")
    Bot.site = login()

    summary = Bot.summary("[[User:Ryebot/bot/scripts/iteminfodata|Updated]].")
    intermediate_module_name = "Module:Iteminfo/luadata"
    target_module_name = "Module:Iteminfo/data"

    lower_itemid = 0  # item ID to start at
    number_of_items_per_chunk = 100

    # terraria version and generation timestamp
    module_data_code = parse_wikitext('{{#invoke:Iteminfo/datagen|genMeta}}') + '\n'

    # pure data code
    module_data_code += _make_data(lower_itemid, number_of_items_per_chunk) + '\n\n'

    module_page, existing_module_text = read_page(Bot.site, intermediate_module_name)
    head, body, foot = _get_existing_module_text_parts(module_page, existing_module_text)

    # compare the just generated pure data code with the existing pure data code
    if _no_actual_changes(module_data_code, body):
        logger.info(
            "No changes to be made.",
            extra = {"head": "No changes", "body": "The database appears to be up-to-date."}
        )
        return

    new_module_code = head + module_data_code + foot

    save_page(Bot.site, Bot.dry_run, module_page, new_module_code, summary, minor=True)

    module_code_with_json = parse_wikitext('{{#invoke:Iteminfo/datagen|convertToJsonData}}')

    target_module, _ = read_page(Bot.site, target_module_name)
    save_page(Bot.site, Bot.dry_run, target_module, module_code_with_json, summary, minor=True)


def _make_data(lower_itemid: int, number_of_items_per_chunk: int):
    """Run the datagen function for all items and return the result as a string."""
    max_itemid = _get_max_itemid()
    if not max_itemid:
        errorstr = "Couldn't determine the greatest item ID."
        logger.error(
            errorstr,
            extra = {"head": errorstr, "body": 'Expanding "{{iteminfo/maxId}}" failed.'}
        )
        raise ScriptRuntimeError(errorstr)

    logger.info(
        f"Generating module code for items {lower_itemid} through {max_itemid}, "
        f"in chunks of {number_of_items_per_chunk}."
    )

    module_code_chunks = []
    while lower_itemid <= max_itemid:
        upper_itemid = min(lower_itemid + number_of_items_per_chunk - 1, max_itemid)
        module_invocation_code = f"{{{{#invoke:Iteminfo/datagen|gen|{lower_itemid}|{upper_itemid}}}}}"
        logger.info(module_invocation_code)

        stopwatch = Stopwatch()
        # create the code for this chunk from the datagen
        new_module_code_chunk = parse_wikitext(module_invocation_code)
        if new_module_code_chunk:
            stopwatch.stop()
            logger.info(f"    parsed in {stopwatch}")
            module_code_chunks.append(new_module_code_chunk)
        else:
            errorstr = f'Couldn\'t parse "{module_invocation_code}".'
            logger.error(
                errorstr,
                extra = {
                    "head": "Parsing a chunk failed",
                    "body": f'The chunk "{module_invocation_code}" returned no output.'
                }
            )
            raise ScriptRuntimeError(errorstr)

        # for the next chunk
        lower_itemid += number_of_items_per_chunk

    return ''.join(module_code_chunks)


def _get_existing_module_text_parts(module_page, module_text: str):
    """Return the "head", "body", and "foot" of the existing module.

    The module has some other text before and after the data code that needs to
    be left unchanged. This function splits the existing module code into the part
    before the data ("head"; the separator is `start_line`) and the part after
    the data ("foot"; the separator is `end_line`).
    """

    start_line = "---------------------------------------- DATA START\n"
    end_line = "---------------------------------------- DATA END\n"

    module_text_lines = module_text.splitlines(keepends=True)

    try:
        start_line_index = module_text_lines.index(start_line)
    except ValueError:
        errorstr = f'Start line {start_line!r} not found in {module_page.name}'
        logger.error(
            errorstr,
            extra = {
                "head": f"{module_page.name} has an unexpected format",
                "body": f"Couldn't find the following line in the module text: {start_line!r}"
            }
        )
        raise ScriptRuntimeError(errorstr)

    # .index() likely goes through the lines from the start, which would take
    # a long time here. we know that the `end_line` is near the end, so we start
    # from there and go backwards. this should save some time.
    end_line_index = len(module_text_lines)
    for line in module_text_lines[::-1]:
        end_line_index -= 1
        if line == end_line:
            break
    else:
        errorstr = f"End line {end_line!r} not found in {module_page.name}"
        logger.error(
            errorstr,
            extra = {
                "head": f"{module_page.name} has an unexpected format",
                "body": f"Couldn't find the following line in the module text: {end_line!r}"
            }
        )
        raise ScriptRuntimeError(errorstr)

    return (
        ''.join(module_text_lines[:start_line_index + 1]),  # head
        ''.join(module_text_lines[start_line_index + 1:end_line_index]),  # body
        ''.join(module_text_lines[end_line_index:])  # foot
    )


def _no_actual_changes(new_data_text: str, current_data_text: str):
    """Check if there is an actual difference in data between current and new.

    It is possible that the `new_data_text` merely has whitespace changes,
    or perhaps additional or removed blank lines. In this case, the actual
    data of the database does not change, so the save can be skipped.
    """

    # strip whitespace from all lines and remove empty lines
    new_data_lines = [l.strip() for l in new_data_text.splitlines() if l != '']
    current_data_lines = [l.strip() for l in current_data_text.splitlines() if l != '']

    # ignore the "_generated" line because it contains a timestamp and therefore will always change
    return (
        [line for line in new_data_lines if not line.startswith("['_generated']")]
        == [line for line in current_data_lines if not line.startswith("['_generated']")]
    )


def _get_max_itemid():
    """Return the greatest item ID by expanding {{iteminfo/maxId}}."""
    parsed_wikitext = parse_wikitext("{{iteminfo/maxId}}")
    if parsed_wikitext:
        try:
            return int(parsed_wikitext)
        except ValueError:
            # result is not a valid int
            pass
