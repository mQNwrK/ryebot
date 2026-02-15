import logging
import time

from ryebot.bot import Bot
from ryebot.errors import ScriptRuntimeError
from ryebot.login import login
from ryebot.stopwatch import Stopwatch
from ryebot.wiki_util import parse_wikitext, read_page, save_page


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

    summary = Bot.summary("[[User:Ryebot/bot/scripts/npcinfodata|Updated]].")
    target_module_name = "Module:Npcinfo/data"

    number_of_npcs_per_chunk = 100

    # terraria version and generation timestamp
    module_data_code = parse_wikitext(Bot.site, '{{#invoke:Npcinfo/datagen|genMeta}}') + '\n'

    logger.debug(f"Sleeping to avoid Cloudflare challenge: {CLOUDFLARE_SAFETY_DELAY} sec")
    time.sleep(CLOUDFLARE_SAFETY_DELAY)

    # pure data code
    module_data_code += _make_data(number_of_npcs_per_chunk) + '\n\n'

    module_page, existing_module_text = read_page(Bot.site, target_module_name)
    head, body, foot = _get_existing_module_text_parts(module_page, existing_module_text)

    # compare the just generated pure data code with the existing pure data code
    if _no_actual_changes(module_data_code, body):
        logger.info(
            "No changes to be made.",
            extra = {"head": "No changes", "body": "The database appears to be up-to-date."}
        )
        return

    new_module_code = head + module_data_code + foot

    logger.debug(f"Sleeping to avoid Cloudflare challenge: {CLOUDFLARE_SAFETY_DELAY} sec")
    time.sleep(CLOUDFLARE_SAFETY_DELAY)

    save_page(Bot.site, Bot.dry_run, module_page, new_module_code, summary, minor=True)


def _make_data(number_of_npcs_per_chunk: int):
    """Run the datagen function for all NPCs and return the result as a string."""
    min_npcid = _get_min_npcid()
    if not min_npcid:
        errorstr = "Couldn't determine the lowest NPC ID."
        logger.error(
            errorstr,
            extra = {"head": errorstr, "body": 'Expanding "{{npcinfo/minId}}" failed.'}
        )
        raise ScriptRuntimeError(errorstr)

    max_npcid = _get_max_npcid()
    if not max_npcid:
        errorstr = "Couldn't determine the greatest NPC ID."
        logger.error(
            errorstr,
            extra = {"head": errorstr, "body": 'Expanding "{{npcinfo/maxId}}" failed.'}
        )
        raise ScriptRuntimeError(errorstr)

    logger.info(
        f"Generating module code for NPCs {min_npcid} through {max_npcid}, "
        f"in chunks of {number_of_npcs_per_chunk}."
    )

    module_code_chunks = []
    lower_npcid = min_npcid
    while lower_npcid <= max_npcid:
        upper_npcid = min(lower_npcid + number_of_npcs_per_chunk - 1, max_npcid)
        module_invocation_code = f"{{{{#invoke:Npcinfo/datagen|gen|{lower_npcid}|{upper_npcid}}}}}"
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
        lower_npcid += number_of_npcs_per_chunk

        logger.debug(f"Sleeping to avoid Cloudflare challenge: {CLOUDFLARE_SAFETY_DELAY} sec")
        time.sleep(CLOUDFLARE_SAFETY_DELAY)

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


def _get_max_npcid():
    """Return the greatest NPC ID by expanding {{npcinfo/maxId}}."""
    parsed_wikitext = parse_wikitext(Bot.site, "{{npcinfo/maxId}}")
    if parsed_wikitext:
        try:
            return int(parsed_wikitext)
        except ValueError:
            # result is not a valid int
            pass


def _get_min_npcid():
    """Return the greatest NPC ID by expanding {{npcinfo/minId}}."""
    parsed_wikitext = parse_wikitext(Bot.site, "{{npcinfo/minId}}")
    if parsed_wikitext:
        try:
            return int(parsed_wikitext)
        except ValueError:
            # result is not a valid int
            pass
