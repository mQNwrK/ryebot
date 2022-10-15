import argparse
from importlib import metadata
import logging
import os
import sys

from ryebot.bot import Bot
from ryebot.core import ryebot_core
from ryebot.scripts import scriptfunctions
from ryebot.errors import WrongUserError, WrongWikiError


# "root" logger for all logging in this package
ryebotLogger = logging.getLogger("ryebot")
# "child" logger, in this case named "ryebot.main", which propagates to the "ryebot" logger
logger = logging.getLogger(__name__)


def main():
    """Main entry function."""
    args = parse_commandline_args()
    Bot.scriptname_to_run = args.script
    Bot.dry_run = args.dryrun
    Bot.is_on_github_actions = args.github
    setup_logging(debug_on_console=args.verbose)
    logger.info(
        f"Started ryebot v{metadata.version(__package__)} main.py for "
        f'script "{Bot.scriptname_to_run}".'
    )
    if Bot.dry_run:
        logger.info("Dry-run mode is active: No changes to any wiki pages will be made.")

    # `ryebot_core` is the function where the actual actions are executed
    if not Bot.is_on_github_actions:
        try:
            ryebot_core()
        except Exception:
            logger.exception('')
        else:
            logger.info("Successfully completed main.py.")
    else:
        # we need a bit of preparation if we're running on GitHub Actions ("GH").
        # `ryebot_core` is called in here, with the GH-specific wrapping.
        main_for_github_actions()


def main_for_github_actions():
    """Run `ryebot_core`, wrapped in the stuff for GitHub Actions."""
    workflow_summary_filename = os.getenv("GITHUB_STEP_SUMMARY")
    workflow_run_id = os.getenv("GITHUB_RUN_ID")

    class CustomFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord):
            head = getattr(record, "head", None)
            body = getattr(record, "body", None)
            if not head and not body:
                return super().format(record)
            outputtype = "notice"
            if record.levelno == logging.DEBUG:
                outputtype = "debug"
            elif record.levelno == logging.WARNING:
                outputtype = "warning"
            elif record.levelno in (logging.ERROR, logging.CRITICAL):
                outputtype = "error"
                if record.exc_info:
                    # print the traceback and the exception name and details
                    logger.exception(record.msg)
            return (
                f"::{outputtype}" + ('' if head is None else f" title={head}")
                + "::" + (body or record.msg)
            )

    for handler in reversed(ryebotLogger.handlers):
        ryebotLogger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(CustomFormatter())
    ryebotLogger.addHandler(handler)

    Bot.common_summary_suffix = f"  »ID:{workflow_run_id}«"

    try:
        ryebot_core()
    except (WrongUserError, WrongWikiError) as e:
        with open(workflow_summary_filename, 'a') as f:
            f.write(f"### Login failed!\n")
            f.write(str(e))
        logger.exception('')
        sys.exit(1)  # explicitly fail
    else:
        with open(workflow_summary_filename, 'a') as f:
            f.write("### All good.\n")
        logger.info("Successfully completed main.py.")


def parse_commandline_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('script', choices=scriptfunctions.keys())
    parser.add_argument('--dryrun', action='store_true')
    parser.add_argument('-g', '--github', action='store_true')
    parser.add_argument('-v', '--verbose', action='store_true')
    return parser.parse_args()


def setup_logging(debug_on_console: bool = False):
    ryebotLogger.setLevel(logging.DEBUG)

    # create a new handler to print to console
    print_to_console = logging.StreamHandler()
    print_to_console.setLevel(logging.DEBUG if debug_on_console else logging.INFO)

    # register handler to logger
    ryebotLogger.addHandler(print_to_console)
