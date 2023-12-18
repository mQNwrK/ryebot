import argparse
from http.client import responses
from importlib import metadata
import logging
import os
import re
import sys

from ryebot.bot import Bot
from ryebot.core import ryebot_core
from ryebot.errors import ScriptRuntimeError, WrongUserError, WrongWikiError
from ryebot.scripts import scriptfunctions


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
    ryebot_version = metadata.version(__package__)
    logger.info(
        f"Started ryebot v{ryebot_version} main.py for script "
        f'"{Bot.scriptname_to_run}".'
    )
    if Bot.dry_run:
        logger.info("Dry-run mode is active: No changes to any wiki pages will be made.")

    # `ryebot_core` is the function where the actual actions are executed
    if not Bot.is_on_github_actions:
        try:
            ryebot_core()
        except ScriptRuntimeError:
            pass
        except Exception:
            logger.exception('')
        else:
            logger.info("Successfully completed main.py.")
    else:
        # we need a bit of preparation if we're running on GitHub Actions ("GH").
        # `ryebot_core` is called in here, with the GH-specific wrapping.
        main_for_github_actions(log_debug=args.verbose)


def main_for_github_actions(log_debug: bool = False):
    """Run `ryebot_core`, wrapped in the stuff for GitHub Actions."""
    workflow_summary_filename = os.getenv("GITHUB_STEP_SUMMARY")
    workflow_run_id = os.getenv("GITHUB_RUN_ID")

    def write_summary():
        if Bot.script_output and workflow_summary_filename:
            with open(workflow_summary_filename, 'a') as f:
                f.write(Bot.script_output)

    class CustomFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord):
            head = getattr(record, "head", None)
            body = getattr(record, "body", None)
            if head is None:
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
            return "::{}{}::{}".format(
                outputtype,
                '' if head is None else f" title={head}",
                body or record.msg or ''
            )

    for handler in reversed(ryebotLogger.handlers):
        ryebotLogger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG if log_debug else logging.INFO)
    handler.setFormatter(CustomFormatter())
    ryebotLogger.addHandler(handler)

    # when the wiki returns a 5xx error (e.g. 504 Gateway Error), then the
    # mwclient.client.Site.raw_call function logs a warning with the entire
    # HTML source of the error page. That clogs up the log very much, so we
    # trim these specific messages here
    pattern = re.compile(r"Received (?P<statuscode>5\d\d) response: ")
    # http.client.responses only contains the IANA codes;
    # the following are Cloudflare-specific;
    # source: https://en.wikipedia.org/wiki/List_of_HTTP_status_codes#Cloudflare
    statuscode_texts = responses | {
        520: "Web Server Returned an Unknown Error",
        521: "Web Server Is Down",
        522: "Connection Timed Out",
        523: "Origin Is Unreachable",
        524: "A Timeout Occurred",
        525: "SSL Handshake Failed",
        526: "Invalid SSL Certificate",
        527: "Railgun Error"
    }
    def trim_5xx_errormsg(record: logging.LogRecord):
        if record.msg.endswith(". Retrying in a moment."):
            match = pattern.match(record.msg)
            if match:
                statuscode = int(match["statuscode"])
                statuscodetext = ' ' + statuscode_texts.get(statuscode, '')
                record.msg = (
                    f"Wiki returned error {statuscode}{statuscodetext.rstrip()}!"
                    " Retrying in a moment."
                )
        return True
    logging.getLogger("mwclient.client").addFilter(trim_5xx_errormsg)

    Bot.common_summary_suffix = f"  »ID:{workflow_run_id}«"

    try:
        ryebot_core()
    except (WrongUserError, WrongWikiError) as e:
        with open(workflow_summary_filename, 'a') as f:
            f.write(f"### Login failed!\n")
            f.write(str(e))
        logger.exception('')
        sys.exit(1)  # explicitly fail
    except ScriptRuntimeError:
        write_summary()
        sys.exit(1)  # explicitly fail
    except Exception as exc:
        logger.exception(str(exc))
        write_summary()
        sys.exit(1)  # explicitly fail
    else:
        write_summary()
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

    # enable warnings from the mwclient library
    mwclientLogger = logging.getLogger("mwclient")
    mwclientLogger.setLevel(logging.WARNING)
    mwclientLogger.addHandler(print_to_console)
