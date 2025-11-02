import argparse
from http.client import responses
from importlib import metadata
import logging
import os
from pathlib import Path
import platform
import re
import sys
import time

from ryebot.bot import Bot
from ryebot.errors import LoginError, ScriptRuntimeError
from ryebot.login import login
from ryebot.scripts import scriptfunctions


# "root" logger for all logging in this package
ryebotLogger = logging.getLogger("ryebot")
# "child" logger, in this case named "ryebot.main", which propagates to the "ryebot" logger
logger = logging.getLogger(__name__)


def main():
    """Main entry function."""
    ryebot_version = metadata.version(__package__)
    args = _parse_commandline_args(ryebot_version)
    Bot.init_from_commandline_parameters(
        scriptname_to_run = args.script,
        dry_run = args.dryrun,
        config = args.config,
        is_on_github_actions = args.github
    )
    _setup_logging(debug_on_console=args.verbose, log_to_file=args.logfile)

    logger.info(
        f"Started ryebot v{ryebot_version} main.py for script "
        f'"{Bot.scriptname_to_run}".'
    )
    if Bot.dry_run:
        logger.info("Dry-run mode is active: No changes to any wiki pages will be made.")
    if Bot.config_from_commandline:
        logger.debug("Configuration input: " + Bot.config_from_commandline)

    if not Bot.is_on_github_actions:
        try:
            _run_script()
        except ScriptRuntimeError:
            pass
        except Exception:
            logger.exception('')
        else:
            logger.info("Successfully completed main.py.")
    else:
        # we need a bit of preparation if we're running on GitHub Actions.
        # `_run_script` is called in here, with the GitHub Actions-specific wrapping.
        _main_for_github_actions(log_debug=args.verbose)


def _main_for_github_actions(log_debug: bool = False):
    """Execute `_run_script`, wrapped in the stuff for GitHub Actions."""
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
        _run_script()
    except ScriptRuntimeError:
        write_summary()
        sys.exit(1)  # explicitly fail
    except LoginError as exc:
        logger.exception(str(exc), extra={"head": "Login failed"})
        write_summary()
        sys.exit(1)  # explicitly fail
    except Exception as exc:
        logger.exception(str(exc))
        write_summary()
        sys.exit(1)  # explicitly fail
    else:
        write_summary()
        logger.info("Successfully completed main.py.")


def _run_script():
    """Run the desired script."""
    if Bot.scriptname_to_run in scriptfunctions:
        Bot.script_output = ''
        scriptfunctions[Bot.scriptname_to_run]()
    else:
        raise RuntimeError(
            f'unknown script name "{Bot.scriptname_to_run}"; see "python3 -m '
            'ryebot --help"'
        )


def _parse_commandline_args(ryebot_version: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-V', '--version', action='version', version=ryebot_version)
    parser.add_argument('script', choices=scriptfunctions.keys())
    parser.add_argument('--dryrun', action='store_true')
    parser.add_argument('--logfile', action='store_true', help=f'write debug log in {_logdir()}')
    parser.add_argument('-g', '--github', action='store_true', help='indicate that the platform is GitHub Actions')
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('-c', '--config')
    return parser.parse_args()


def _setup_logging(debug_on_console: bool = False, log_to_file: bool = False):
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

    if log_to_file:
        log_directory = _logdir() / Bot.scriptname_to_run
        log_directory.mkdir(parents=True, exist_ok=True)
        log_filename = Bot.scriptname_to_run + '_' + time.strftime('%Y-%m-%dT%H%M%SZ', time.gmtime()) + '.log'
        # create a new handler to print to file
        print_to_file = logging.FileHandler(log_directory / log_filename)
        print_to_file.setLevel(logging.DEBUG)
        # log entry format
        formatter = logging.Formatter('[%(asctime)s] %(message)s', '%c')
        # all entry timestamps in UTC
        formatter.converter = time.gmtime
        print_to_file.setFormatter(formatter)
        # register handler to logger
        ryebotLogger.addHandler(print_to_file)
        mwclientLogger.addHandler(print_to_file)


def _logdir() -> Path:
    """Return the base directory for logfiles on the current platform."""
    logdir = {
        'Windows': Path(os.getenv('LOCALAPPDATA', '')),
        'Linux': Path.home() / '.cache',
        'Darwin': Path.home() / 'Library' / 'Logs'  # macOS
    }.get(platform.system())
    # fallback to home directory if platform is not supported or Windows env is empty
    if logdir is None or logdir == Path(''):
        logdir = Path.home()
    return logdir / __package__
