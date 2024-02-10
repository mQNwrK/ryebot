import base64
import bz2
from datetime import datetime, timezone
import json
import logging
from typing import Iterable, Literal

from mwclient.errors import ProtectedPageError
import mwparserfromhell

from ryebot.bot import Bot
from ryebot.errors import ScriptRuntimeError
from ryebot.login import login
from ryebot.script_configuration import ScriptConfiguration
from ryebot.stopwatch import Stopwatch


logger = logging.getLogger(__name__)


DEFAULT_CONFIG = {
    "wiki_page": "User:Rye Greenwood/util/Wiki extension updates"
}


def script_main():
    logger.info("Started extensionupdates.")
    Bot.site = login()
    summary = Bot.summary("[[User:Ryebot/bot/scripts/extensionupdates|Updated]].")

    config = ScriptConfiguration("extensionupdates")
    config.update_from_wiki()

    extensions_today = _get_extensions_today()
    if not extensions_today:
        logger.warning(
            "Couldn't fetch extension information.",
            extra = {
                "head": "Extension information unavailable",
                "body": (
                    "No information about installed extensions can be obtained "
                    "from the wiki at the moment."
                )
            }
        )
        return

    page, pagetext = _read_page_safely(config["wiki_page"])
    wikitext = mwparserfromhell.parse(pagetext)

    extensions_cached = _build_cached_extensions(wikitext)
    change_today = _compare(extensions_cached, extensions_today)
    change_today.timestamp = datetime.now(tz=timezone.utc)
    logger.debug(str(change_today))

    if change_today.is_noop():
        logger.info(
            "No changes to be made.",
            extra = {
                "head": "No changes",
                "body": "The page appears to be up-to-date."
            }
        )
        return

    text_to_add = _make_text_for_change(change_today)
    _insert_into_wikitext(wikitext, text_to_add)
    pagetext = str(wikitext)
    logger.debug(pagetext)
    _save_page(page, pagetext, summary)


def _get_extensions_today() -> list[dict[str, str]]:
    """Fetch the current extension data from the wiki."""
    api_parameters = {
        'meta': 'siteinfo',
        'siprop': 'extensions'
    }
    api_result = Bot.site.api('query', **api_parameters).get('query', {})
    return api_result.get('extensions', [])


def _build_cached_extensions(wikitext: mwparserfromhell.wikicode.Wikicode) -> list:
    """Assemble the cached list of extensions (from "yesterday").

    The `wikitext` contains a timeline of extension changes. Apply them in order
    to arrive at the most recently stored set of extensions (from the last
    script execution, i.e. yesterday).

    The timeline is stored as HTML comments which contain `Change` instances,
    converted to their JSON representation, compressed, and base64-encoded.
    The comments start with `!<~>` to make them somewhat unique and avoid any
    potential clashes with other comments in the intro text of the page.
    """

    extensions = []
    # `reversed` to start at the bottom
    for comment in reversed(wikitext.filter_comments(matches=r'^<!--!<~>')):
        changestring = comment.contents[4:]  # strip leading '!<~>'
        changestring = changestring.replace('\n', '')  # the long string might be split into multiple lines
        change = Change.from_compressed_str(changestring)
        try:
            extensions = change.apply(extensions)
        except Exception:
            logger.exception(
                "Syntax error in a change string:",
                extra = {
                    "head": "Error during page parsing",
                    "body": (
                        "The page has unexpected contents; please make sure it "
                        "has not been altered manually."
                    )
                }
            )
            raise ScriptRuntimeError
    return extensions


class Change():
    """Represents a change in the wiki's list of extensions, like a newly added extension."""

    def __init__(self,
        extensions_removed: Iterable[str] = [],
        extensions_added: dict[str, dict[str, str]] = {},  # name and attributes
        extensions_updated: dict[str, dict[Literal['rem', 'add', 'upd'], Iterable]] = {},
        timestamp: datetime = None
    ):
        self.extensions_removed = extensions_removed
        self.extensions_added = extensions_added
        self.extensions_updated = extensions_updated
        self.timestamp = timestamp

    def to_dict(self):
        """Convert to a dict that is fit for pretty-printing, JSON serialization, etc."""
        return {
            'rem': self.extensions_removed,
            'add': self.extensions_added,
            'upd': self.extensions_updated,
            'ts': int(self.timestamp.timestamp()) if self.timestamp else None
        }

    @classmethod
    def from_dict(cls, jsondict: dict):
        """Create new object from a dict (reverse of `Change().to_dict()`)."""
        timestamp = jsondict.get('ts')
        if timestamp:
            timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return cls(
            jsondict.get('rem', []),
            jsondict.get('add', {}),
            jsondict.get('upd', {}),
            timestamp
        )

    def __str__(self):
        """Convert to a compact JSON string."""
        return json.dumps(self.to_dict(), separators=(',', ':'))

    def to_compressed_str(self):
        """Convert to JSON, compress, and encode with base64."""
        return base64.b64encode(bz2.compress(str.encode(str(self)))).decode()

    @classmethod
    def fromstr(cls, changestring: str):
        """Create new object from a JSON string."""
        jsonchange = json.loads(changestring)
        if type(jsonchange) != dict:
            raise ValueError('changestring is not a valid JSON object')
        return cls.from_dict(jsonchange)

    @classmethod
    def from_compressed_str(cls, compressed_changestring: str):
        """Create new object from a compressed JSON string (reverse of `Change().to_compressed_str()`)."""
        return cls.fromstr(bz2.decompress(base64.b64decode(compressed_changestring)).decode())

    def is_noop(self):
        """`True` if nothing actually changed in this change."""
        return (0 ==
            len(self.extensions_removed) +
            len(self.extensions_added) +
            len(self.extensions_updated)
        )

    def apply(self, extensions: list[dict[str, str]]) -> list[dict[str, str]]:
        """Apply this change to the list of `extensions` and return a new list."""
        result = []
        for extension in extensions:
            if extension['name'] in self.extensions_removed:
                continue
            to_add = extension.copy()
            if extension['name'] in self.extensions_updated:
                update = self.extensions_updated[extension['name']]
                for attributename, attributevalue in update['rem']:
                    if attributename in to_add:
                        del to_add[attributename]
                for attributename, attributevalue in update['add']:
                    to_add[attributename] = attributevalue
                for attributename, _, attributevalue in update['upd']:
                    to_add[attributename] = attributevalue
            result.append(to_add)
        result.extend(self.extensions_added.values())
        return result


def _compare(old_extensions: list[dict[str, str]], new_extensions: list[dict[str, str]]):
    """Compare the two lists of extensions and return a `Change` with the differences."""
    result = Change()

    if old_extensions == new_extensions:  # no differences
        return result

    # the input parameters are lists of dicts with extension attributes, convert
    # those to dicts with extension names as keys for easier handling
    old_exts = { extension['name']: extension for extension in old_extensions }
    new_exts = { extension['name']: extension for extension in new_extensions }

    extension_names_removed = old_exts.keys() - new_exts.keys()
    extension_names_added = new_exts.keys() - old_exts.keys()
    extension_names_updated = new_exts.keys() & old_exts.keys()

    # extensions that were removed
    result.extensions_removed = list(extension_names_removed)

    # extenions that were added
    # convert extension names to { 'name1': {data}, 'name2': {data} }
    result.extensions_added = {
        extname: new_exts[extname]
        for extname in extension_names_added
    }

    # extensions where an attribute has changed
    result.extensions_updated = {}
    for extname in extension_names_updated:
        ext_new = new_exts[extname]
        ext_old = old_exts[extname]
        if ext_new != ext_old:
            result.extensions_updated[extname] = {
                'rem': [  # attributes removed
                    (attributename, ext_old[attributename])
                    for attributename in ext_old.keys() - ext_new.keys()
                ],
                'add': [  # attributes added
                    (attributename, ext_new[attributename])
                    for attributename in ext_new.keys() - ext_old.keys()
                ],
                'upd': [  # attributes changed
                    (attributename, ext_old[attributename], ext_new[attributename])
                    for attributename in ext_new.keys() & ext_old.keys()
                    if ext_new[attributename] != ext_old[attributename]
                ]
            }

    return result


def _make_text_for_change(change: Change):
    """Assemble the wikitext description for the `change`."""
    lines = []

    if change.timestamp is None:
        timestamp = "Unknown date"
    else:
        timestamp = change.timestamp.strftime("%B %d, %Y")
    lines.append(f"== {timestamp} ==")

    changestring = f"<!--!<~>{change.to_compressed_str()}"
    # split the potentially very long string into separate lines of 76 characters each
    lines.append('\n'.join(_chunks(changestring, 76)) + "-->")

    if change.extensions_added:
        lines.append(f"* New: {', '.join(change.extensions_added.keys())}")
    if change.extensions_removed:
        lines.append(f"* Removed: {', '.join(change.extensions_removed)}")
    if change.extensions_updated:
        lines.append("* Changed:")
        for extname, upd in change.extensions_updated.items():
            lines.extend(
                f'** {extname} <code>{attributename}</code>: "{attributevalue_old}" → "{attributevalue_new}"'
                for attributename, attributevalue_old, attributevalue_new in upd['upd']
            )
            lines.extend(
                f'** {extname} <code>{attributename}</code> added'
                for attributename, attributevalue in upd['add']
            )
            lines.extend(
                f'** {extname} <code>{attributename}</code> removed (was "{attributevalue}")'
                for attributename, attributevalue in upd['rem']
            )
    return '\n'.join(lines) +'\n\n'


def _insert_into_wikitext(wikitext, text_to_add):
    """Add the `text_to_add` before the first heading in the existing `wikitext`."""
    headings = wikitext.filter_headings()
    if headings:
        wikitext.insert_before(headings[0], text_to_add, recursive=False)
    else:
        # there are no headings in the wikitext, so just add the text to the end
        wikitext.append(text_to_add)


def _read_page_safely(pagename: str):
    """Safely get the `Page` object and its text for the `pagename`."""
    try:
        page = Bot.site.pages[pagename]
        pagetext = page.text()
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
    return page, pagetext


def _save_page(page, pagetext: str, summary: str):
    """Save the `Page` object with the new `pagetext` and `summary`."""
    if Bot.dry_run:
        chardiff = len(pagetext) - (page.length or 0)
        chardiff_str = '+' if chardiff > 0 else ''
        chardiff_str += f"{chardiff} diff"
        logger.info(
            f'Would save page "{page.name}" ({len(pagetext)} characters, '
            f'{chardiff_str}) with summary "{summary}".'
        )
    else:
        stopwatch = Stopwatch()
        try:
            saveresult = Bot.site.save(page, pagetext, summary=summary, minor=True)
        except ProtectedPageError:
            logger.warning(
                "Page is protected, skipped it.",
                extra = {
                    "head": f'Did not save the page',
                    "body": "Couldn't save the page because it is protected."
                }
            )
        except Exception:
            logger.exception("Error while saving:")
            logger.warning(
                "Skipped page due to error.",
                extra = {
                    "head": f'Did not save the page',
                    "body": (
                        "Couldn't save the page due to some error; "
                        "check the logs for details."
                    )
                }
            )
        else:
            stopwatch.stop()
            diff_id = saveresult.get("newrevid")
            diff_link = Bot.site.fullurl(diff=diff_id) if diff_id else None
            logger.info(
                f'Saved page "{page.name}" with summary "{summary}". '
                f"Diff: {diff_link if diff_link else 'None'}. Time: {stopwatch}"
            )


def _chunks(sequence, n):
    """Yield successive `n`-sized chunks from `sequence`."""
    for i in range(0, len(sequence), n):
        yield sequence[i:i + n]
