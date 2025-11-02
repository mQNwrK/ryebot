import logging
import time
from typing import NamedTuple
from urllib.parse import urlparse

import mwparserfromhell
import requests
from semantic_version import Version as SemVer

from ryebot.bot import Bot
from ryebot.errors import ScriptRuntimeError
from ryebot.login import login
from ryebot.script_configuration import ScriptConfiguration
from ryebot.stopwatch import Stopwatch


logger = logging.getLogger(__name__)

SUMMARY_TIMEFORMAT = "%a, %d %b %Y %H:%M:%S (UTC)"  # timeformat in our edit summaries


class MapviewerInfo(NamedTuple):
    """Information about a map viewer, parsed from its URL response."""

    name: str
    """Name of the map viewer"""
    new_version_raw: "str|None"
    """Most recent version, as a string like in the source"""
    new_version: SemVer
    """Most recent version converted to a SemVer object for comparing"""
    # semver normalizes e.g. "1.16" to "1.16.0", but we want to preserve the
    # original string format as it is given in the source, so we store both
    url: "str|None"
    """Link to source of the new version"""
    date: "str|None"
    """Date and time of the update to the new version"""


def script_main():
    logger.info("Started update_mapviewer_versions.")
    Bot.site = login()

    config = ScriptConfiguration("mapviewerversions")
    config.set_from_wiki()

    template_name = config["template"]
    page, wikitext = _read_page_safely(config["wiki_page"])

    mapviewers_from_config = filter(
        lambda c: c[0] not in ("template", "wiki_page"),  # reserved parameters
        config.items()  # [ ("param_key", "param_value"), ... ]
    )
    # iterate over the map viewers defined in the config and update each one;
    # the `wikitext` object is passed around between them so that subsequent
    # map viewers don't override each other
    for name, url in mapviewers_from_config:
        logger.info(f"== {name} ==")

        mapviewer_info = _get_latest_mapviewer_info_from_url(name, url)
        if mapviewer_info is None:  # couldn't fetch/parse the most recent version
            continue

        pagetext_preupdate = str(wikitext)
        wikitext = _update_mapviewer_version_in_wikitext(wikitext, template_name, mapviewer_info)
        pagetext_postupdate = str(wikitext)
        if pagetext_preupdate != pagetext_postupdate:  # don't save if there's no change
            _save_page(page, str(wikitext), _assemble_summary(mapviewer_info), mapviewer_info)


def _read_page_safely(pagename: str):
    """Safely get the `Page` object and its `Wikicode` for the `pagename`."""
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
    return page, mwparserfromhell.parse(pagetext)


def _get_latest_mapviewer_info_from_url(mapviewer_name: str, url: str):
    """Make a request to the map viewer's `url` and call the respective parser function.

    Return a `MapviewerInfo` if this succeeds and `None` if something fails.
    """

    response = requests.get(url)
    if response.ok:
        urlparsed = urlparse(url)
        if urlparsed.hostname == "api.github.com":
            return _parse_response_github(response, mapviewer_name)
        # there's only the GitHub parser function at the moment; more to be added as follows:
        # elif urlparsed.hostname == "foo.bar.com":  # or other condition
        #     return _parse_response_foobar(response, mapviewer_name)
        else:
            warnstr = (
                "Skipped the map viewer because there's no function for "
                f'parsing the data from its URL "{url}".'
            )
    else:
        warnstr = (
            f'Skipped the map viewer because requesting its URL "{url}" '
            f"returned {response.status_code} {response.reason}."
        )

    logger.warning(warnstr, extra = {"head": f'Did not check "{mapviewer_name}"'})
    return None


def _parse_response_github(response: requests.Response, mapviewer_name: str):
    """Parse the response of a GitHub API call for a repository's release."""
    repo_info = response.json()
    tag_name: str|None = repo_info.get('tag_name')
    html_url: str|None = repo_info.get('html_url')
    published_at: str|None = repo_info.get('published_at')

    if tag_name:
        tag_name = tag_name.strip()
        # remove leading 'v' if present
        tag_name = tag_name.removeprefix('v').removeprefix('V')
    # convert to semver Version
    try:
        tag_name_as_version_object = SemVer.coerce(tag_name or '')
    except ValueError:
        logger.exception(f'Couldn\'t parse the version string from GitHub ("{tag_name}"):')
        logger.warning(
            "Skipped this map viewer.",
            extra = {
                "head": f'Did not check "{mapviewer_name}"',
                "body": (
                    "Skipped it because version parsing was unsuccessful; "
                    "check the logs for details."
                )
            }
        )
        return None

    # convert the "published_at" timestamp to another format
    if published_at:
        github_timeformat = "%Y-%m-%dT%H:%M:%SZ"  # timeformat of GitHub API results
        try:
            published_at_as_struct = time.strptime(published_at, github_timeformat)
            published_at = time.strftime(SUMMARY_TIMEFORMAT, published_at_as_struct)
        except ValueError:  # parsing failed, leave it at the original format
            pass

    return MapviewerInfo(
        mapviewer_name,
        tag_name,
        tag_name_as_version_object,
        html_url,
        published_at
    )


def _update_mapviewer_version_in_wikitext(
    wikitext: mwparserfromhell.wikicode.Wikicode,
    template_name: str,
    mapviewer_info: MapviewerInfo
):
    """Modify the map viewer version in the `wikitext` and return it."""
    # extract the {{software infobox}} template for this map viewer
    mapviewer_template_object: mwparserfromhell.nodes.Template = None
    for template in wikitext.ifilter_templates():
        if (
            template.name.matches(template_name)
            and template.has('name')
            and template.get('name').value.matches(mapviewer_info.name)
            and template.has('version')
        ):
            mapviewer_template_object = template
            break
    else:
        logger.warning(
            "Skipped this map viewer due to missing suitable template transclusion.",
            extra = {
                "head": f'Did not check "{mapviewer_info.name}"',
                "body": (
                    "Skipped it because no suitable transclusion of "
                    f"{{{{{template_name}}}}} could be found on the page."
                )
            }
        )
        return wikitext

    logger.info(f"Parameter currently: {mapviewer_template_object.get('version')}")

    # parse the current parameter value as a SemanticVersion object
    template_value_string = str(mapviewer_template_object.get("version").value).strip()
    try:
        current_version = SemVer.coerce(template_value_string)
    except ValueError:
        logger.exception(f"Couldn't parse this version string:")
        logger.warning(
            "Skipped this map viewer.",
            extra = {
                "head": f'Did not check "{mapviewer_info.name}"',
                "body": (
                    "Skipped it because version parsing was unsuccessful; "
                    "check the logs for details."
                )
            }
        )
        return wikitext

    logger.info(f"Current version: {current_version}")
    logger.info(f"New version: {mapviewer_info.new_version}")

    if mapviewer_info.new_version <= current_version:
        logger.info(
            (
                "Skipped the map viewer because the new version "
                f"{mapviewer_info.new_version} is not greater than the current "
                f"version {current_version}."
            ),
            extra = {"head": f'"{mapviewer_info.name}" version is up to date'}
        )
    else:
        # update the parameter
        mapviewer_template_object.add("version", mapviewer_info.new_version_raw)
        logger.info(f"Parameter after replacement: {mapviewer_template_object.get('version')}")
    return wikitext


def _save_page(page, wikitext: str, summary: str, mapviewer_info: MapviewerInfo):
    if Bot.dry_run:
        logger.info(f'Would save page "{page.name}" with summary "{summary}".')
        return

    stopwatch = Stopwatch()
    try:
        saveresult = Bot.site.save(page, wikitext, summary=summary, minor=True)
    except Exception:
        logger.exception(
            "Error while saving:",
            extra = {
                "head": f'Didn\'t save the update of "{mapviewer_info.name}"',
                "body": (
                    f'Couldn\'t save the page "{page.name}" due to some error; '
                    "check the logs for details."
                )
            }
        )
    else:
        stopwatch.stop()
        diff_id = saveresult.get("newrevid")
        diff_link = Bot.site.fullurl(diff=diff_id) if diff_id else None
        logger.info(
            (
                f'Saved page "{page.name}" with summary "{summary}". '
                f"Diff: {diff_link if diff_link else 'None'}. Time: {stopwatch}"
            ),
            extra = {
                "head": f'Updated "{mapviewer_info.name}" to {mapviewer_info.new_version_raw}'
            }
        )


def _assemble_summary(mapviewer_info: MapviewerInfo):
    """Create the edit summary; only include date and url if they are available."""
    summary = (
        "[[User:Ryebot/bot/scripts/mapviewerversions|Updated]] version of "
        f"{mapviewer_info.name} to {mapviewer_info.new_version_raw}"
    )
    if mapviewer_info.date is not None:
        summary += f" (most recent version as of {mapviewer_info.date}"
        if mapviewer_info.url is not None:
            summary += f", see {mapviewer_info.url})"
        else:
            summary += ')'
    elif mapviewer_info.url is not None:
        summary += f" (see {mapviewer_info.url})"
    return Bot.summary(summary + '.')
