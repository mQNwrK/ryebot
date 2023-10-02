import logging
from pathlib import Path
import re
import subprocess

from ryebot.bot import Bot
from ryebot.errors import ScriptRuntimeError
from ryebot.stopwatch import Stopwatch


logger = logging.getLogger(__name__)


SCSS_DIR = Path('csscompile/scss')  # input from wiki
CSS_DIR = Path('csscompile/css')  # intermediate
OUTPUT_DIR = Path('csscompile/output')  # output for wiki
SASS_PROGRAM = 'dart-sass/sass'  # path to Sass binary


def script_main():
    logger.info('Started csscompile.')
    _pull()
    _compile()
    _postprocess()
    _push()


def _pull():
    """Download all SCSS pages from the wiki to the local filesystem."""

    api_parameters = {
        'generator': 'allpages',
        'gapprefix': 'Common.css/src/',
        'gapnamespace': 8,  # 'MediaWiki:'
        'gaplimit': 'max',
        'prop': 'revisions',
        'rvslots': 'main',
        'rvprop': 'contentmodel|content'
    }

    logger.info('Fetching SCSS pages from the wiki.')

    pagelist = {}
    while True:
        api_result = Bot.site.api('query', **api_parameters)
        api_result_pagelist: dict = api_result.get('query', {}).get('pages', {})
        # merge the data for each page with the existing data
        # (this is necessary because it seems we don't receive every attribute
        # in one query; e.g. in some queries we only get the page's contentmodel
        # but not its content)
        for pageid, pagedata in api_result_pagelist.items():
            pagelist.setdefault(pageid, {})  # ensure the key for this page exists
            pagelist[pageid] |= pagedata  # merge

        if api_result.get('continue') is None:
            break
        # add the 'apcontinue' and 'continue' keys to the query for the next batch
        api_parameters |= api_result.get('continue')

    logger.info(f'Fetched {len(pagelist)} SCSS pages from the wiki.')

    # turn the {'pageid': <pagedata>} dict into a [<pagedata>] list because
    # that's the only thing we care about.
    # in the same step, also remove all pages that don't have the 'css' contentmodel
    pagelist = [
        pagedata for pagedata in pagelist.values()
        if pagedata['revisions'][0]['slots']['main']['contentmodel'] == 'css'
    ]

    # write all the page texts to files
    for page in pagelist:
        pagename: str = page['title'].replace(' ', '_')
        pagetext = page['revisions'][0]['slots']['main']['*']
        filepath = SCSS_DIR / pagename.removeprefix('MediaWiki:Common.css/src/')
        filepath.parents[0].mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w+', encoding='utf-8') as f:
            f.write(pagetext)
            logger.debug(f'Wrote {f.tell() / 1024:.2f} KiB to {f.name}.')

    logger.info(f'Wrote {len(pagelist)} SCSS pages.')


def _compile():
    """Compile the local SCSS files to CSS."""
    CSS_DIR.mkdir(parents=True)

    # there's also a Python library for Sass compilation, `libsass`, but it seems
    # to break on `@include lib.pseudo-block;` (specifically the period after
    # `lib`), so we have to resort to invoking the external program
    try:
        subprocess.run(
            args = [SASS_PROGRAM, '--no-charset', '--no-source-map', f'{SCSS_DIR}:{CSS_DIR}'],
            encoding = 'utf-8',
            capture_output = True,
            check = True
        )
    except subprocess.CalledProcessError as exception:
        errorstr = f'Error during SCSS compilation. Exit code: {exception.returncode}'
        logger.error(
            errorstr + f' Error output: {exception.stderr}',
            extra = {
                'head': 'Compilation failed',
                'body': (
                    "The SCSS files from the wiki couldn't be compiled to CSS. "
                    'Check the logs for details.'
                )
            }
        )
        raise ScriptRuntimeError(errorstr)

    logger.info('Compiled the SCSS files to CSS.')


def _postprocess():
    """Perform the custom post-processing of the compiled CSS files.

    Build the Common.css and Theme-*.css files from the CSS files.
    """

    OUTPUT_DIR.mkdir(parents=True)

    common_css_text = ''
    with open(CSS_DIR / 'Common.css') as f:
        common_css_text = f.read()

    common_css_text = _directive_import(common_css_text)
    common_css_text = _directive_comment(common_css_text)
    themes_rules, common_css_text = _directive_theme(common_css_text)

    with open(OUTPUT_DIR / 'Common.css', mode='w+', encoding='utf-8') as f:
        f.write(common_css_text)
        logger.debug(f'Wrote {f.tell() / 1024:.2f} KiB to {f.name}.')
    logger.info('Created Common.css.')

    for themename, themerules in themes_rules.items():
        headerline = f'/* theme: {themename} */\n'
        with open(OUTPUT_DIR / f'Theme-{themename}.css', mode='w+', encoding='utf-8') as f:
            f.write(headerline + themerules)
            logger.debug(f'Wrote {f.tell() / 1024:.2f} KiB to {f.name}.')
    logger.info(f'Created {len(themes_rules)} theme CSS files.')


def _directive_import(text: str):
    """Replace: `/* @import filename */` --> `(contents of the file)`"""
    pattern = r'^(?P<indent>[ \t]*)/\*\s*@import +(?P<filename>.+?)\s*\*/'

    def _replacement(match: re.Match):
        # read and close the file first, then perform the recursive replacement
        with open(CSS_DIR / match.group('filename')) as f:
            text = f.read()
        # inherit the indentation of @import
        text = re.sub('^', match.group('indent'), text, flags=re.M)
        return _directive_import(text)

    return re.sub(pattern, _replacement, text, flags=re.M|re.I)


def _directive_comment(text: str):
    """Replace: `/*<< comment */` --> `/* comment */`"""
    pattern = r' +/\*<<(.+?)\*/'
    replacement = r' /*\1*/'
    return re.sub(pattern, replacement, text, flags=re.S)


def _directive_theme(text: str):
    """Move `@theme name { ... }` to separate file for theme `name`"""
    pattern = r'^@theme +(?P<themename>.+?)\s*\{\n(?P<themerules>.+?\n)\}\n'

    themes_rules = {}  # keys are theme names; values are theme rules

    def _replacement(match: re.Match):
        themename, themerules = match.groups()
        themerules = re.sub(r'^  ', '', themerules, flags=re.M)
        themes_rules.setdefault(themename, '')  # ensure the key for this theme exists
        themes_rules[themename] += themerules
        return ''

    return themes_rules, re.sub(pattern, _replacement, text, flags=re.S|re.M|re.I)


def _push():
    summary = Bot.summary('[[User:Ryebot/bot/scripts/csscompile|Updated]].')
    output_files = sorted(list(OUTPUT_DIR.iterdir()))
    for file in output_files:
		# strip the first path part ('csscompile/output/')
        pagename = file.resolve().relative_to(OUTPUT_DIR.resolve())
        # replace it with 'MediaWiki:'
        pagename = 'MediaWiki:' + pagename.as_posix()
        with open(file) as f:
            new_pagetext = f.read()

        page = Bot.site.pages[pagename]
        if Bot.dry_run:
            logtext = (
                f'Would {"save" if page.exists else "create"} page "{page.name}"'
                f' with summary "{summary}" and length {len(new_pagetext):,}'
            )
            if page.exists:
                logtext += f' ({len(new_pagetext) - (page.length or 0):+,})'
            logger.info(logtext + '.')
        else:
            stopwatch = Stopwatch()
            try:
                saveresult = Bot.site.save(page, new_pagetext, summary)
            except Exception:
                logger.exception(
                    'Error while saving:',
                    extra = {
                        'head': f'Didn\'t save the update of "{page.name}"',
                        'body': (
                            "Couldn't save the page due to some error; check the "
                            'logs for details.'
                        )
                    }
                )
            else:
                stopwatch.stop()
                diff_id = saveresult.get('newrevid')
                diff_link = Bot.site.fullurl(diff=diff_id) if diff_id else None
                logger.info(
                    (
                        f'Saved page "{page.name}" with summary "{summary}". Diff: '
                        f"{diff_link if diff_link else 'None'}. Time: {stopwatch}"
                    ),
                    extra = {'head': 'Updated successfully'}
                )
