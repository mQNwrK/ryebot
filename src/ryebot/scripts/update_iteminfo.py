import json
import logging
import re
import time

from ryebot.bot import Bot
from ryebot.errors import ScriptRuntimeError
from ryebot.login import login
from ryebot.stopwatch import Stopwatch
from ryebot.wiki_util import get_page_and_text, parse_wikitext, save_page


logger = logging.getLogger(__name__)


# Since some point between 2023-08-21 and 2023-09-15, the Cloudflare in
# front of wiki.gg's servers issues a "challenge" (a CAPTCHA meant to
# be solved by a human) along with an "Error 429: Too Many Requests"
# after about 60 requests have been made in rapid succession.
# https://developers.cloudflare.com/firewall/cf-firewall-rules/cloudflare-challenges/#detecting-a-challenge-page-response
CLOUDFLARE_SAFETY_DELAY: float = 6  # in seconds


def script_main():
    logger.info(f"Started {Bot.scriptname_to_run}.")
    Bot.site = login()

    summary = Bot.summary("[[User:Ryebot/bot/scripts/iteminfodata|Updated]].")
    intermediate_module_name = "Module:Iteminfo/luadata"
    target_module_name = "Module:Iteminfo/data"

    lower_itemid = 0  # item ID to start at
    number_of_items_per_chunk = 100

    # terraria version and generation timestamp
    module_data_code = parse_wikitext(Bot.site, '{{#invoke:Iteminfo/datagen|genMeta}}') + '\n'

    # pure data code
    module_data_code += _make_data(lower_itemid, number_of_items_per_chunk) + '\n\n'

    module_page, existing_module_text = get_page_and_text(Bot.site, intermediate_module_name)
    head, body, foot = _get_existing_module_text_parts(module_page, existing_module_text)

    # compare the just generated pure data code with the existing pure data code
    if _no_actual_changes_intermediate(module_data_code, body):
        logger.info(
            "No changes to be made to the intermediate database.",
            extra = {
                "head": f"No changes to {module_page.name}",
                "body": "The intermediate database appears to be up-to-date."
            }
        )
    else:
        new_module_code = head + module_data_code + foot

        logger.debug(f"Sleeping to avoid Cloudflare challenge: {CLOUDFLARE_SAFETY_DELAY} sec")
        time.sleep(CLOUDFLARE_SAFETY_DELAY)

        save_page(Bot.site, Bot.dry_run, module_page, new_module_code, summary, minor=True)

    logger.debug(f"Sleeping to avoid Cloudflare challenge: {CLOUDFLARE_SAFETY_DELAY} sec")
    time.sleep(CLOUDFLARE_SAFETY_DELAY)

    module_code_with_json = parse_wikitext(Bot.site, '{{#invoke:Iteminfo/datagen|convertToJsonData}}')

    logger.debug(f"Sleeping to avoid Cloudflare challenge: {CLOUDFLARE_SAFETY_DELAY} sec")
    time.sleep(CLOUDFLARE_SAFETY_DELAY)

    target_module, existing_target_module_text = get_page_and_text(Bot.site, target_module_name)

    if _no_actual_changes(module_code_with_json, existing_target_module_text):
        logger.info(
            "No changes to be made to the final database.",
            extra = {
                "head": f"No changes to {target_module.name}",
                "body": "The final database appears to be up-to-date."
            }
        )
    else:
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
        logger.debug(f"Sleeping to avoid Cloudflare challenge: {CLOUDFLARE_SAFETY_DELAY} sec")
        time.sleep(CLOUDFLARE_SAFETY_DELAY)

        upper_itemid = min(lower_itemid + number_of_items_per_chunk - 1, max_itemid)
        module_invocation_code = f"{{{{#invoke:Iteminfo/datagen|gen|{lower_itemid}|{upper_itemid}}}}}"
        logger.info(module_invocation_code)

        stopwatch = Stopwatch()
        # create the code for this chunk from the datagen
        new_module_code_chunk = parse_wikitext(Bot.site, module_invocation_code)
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


def _no_actual_changes_intermediate(new_data_text: str, current_data_text: str):
    """Check if there is an actual difference in data of the intermediate module.

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


def _no_actual_changes(new_data_text: str, current_data_text: str):
    """Check if there is an actual difference in data of the result module.

    The keys of the JSON object most likely have a different order, so they are
    ordered first before the comparison.
    """

    # pattern for extracting the JSON data from the output of {{#invoke:Iteminfo/datagen|convertToJsonData}}
    pattern = re.compile(r'^\["(?P<key>data|nameDB)"\] = \[=====\[(?P<value>\{.*?\})\]=====\]', re.M)

    def _extract_json(luatext):
        json_lines = []
        for match in pattern.finditer(luatext):
            json_lines.append('"' + match.group('key') + '":' + match.group('value'))
        return json.loads('{' + ','.join(json_lines) + '}')

    return (
        json.dumps(_extract_json(new_data_text), sort_keys=True)
        == json.dumps(_extract_json(current_data_text), sort_keys=True)
    )


def _get_max_itemid():
    """Return the greatest item ID by expanding {{iteminfo/maxId}}."""
    logger.debug(f"Sleeping to avoid Cloudflare challenge: {CLOUDFLARE_SAFETY_DELAY} sec")
    time.sleep(CLOUDFLARE_SAFETY_DELAY)
    parsed_wikitext = parse_wikitext(Bot.site, "{{iteminfo/maxId}}")
    if parsed_wikitext:
        try:
            return int(parsed_wikitext)
        except ValueError:
            # result is not a valid int
            pass
