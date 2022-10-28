# Ryebot

**Ryebot** is a tool for automated [wiki](https://en.wikipedia.org/wiki/Wiki) editing via a series of scripts.
It is designed for usage on [The Official Terraria Wiki](https://terraria.wiki.gg) on wiki.gg, but it should be easy to adapt it to other wikis and wiki platforms, particularly Fandom.
This depends largely on the underlying wiki client library, [custom_mwclient](https://github.com/h9a-rD4ubXs8/custom_mwclient), a wrapper around [mwclient](https://pypi.org/project/mwclient).

Ryebot supports being executed via GitHub Actions. For the Terraria Wiki, see [qt-6/ryebot-ctrl](https://github.com/qt-6/ryebot-ctrl).

## Installation

Python 3.9 or newer is required.

```
pip install git+https://github.com/mQNwrK/ryebot.git@main
```

## Usage

```
python3 -m ryebot [-v] [-g] [--dryrun] SCRIPT
```

| Option | Details |
| --- | --- |
| `-v`<br/>`--verbose` | Display more informative logging messages, useful for debugging. |
| `-g`<br/>`--github` | Indicate that Ryebot is executed on GitHub Actions. This adjusts the logging output to GitHub's format, displays a summary file for the workflow run, and appends the workflow run ID to all edit summaries. |
| `--dryrun` | Do not perform any page edits. No wiki content will be altered. |

The mandatory argument `SCRIPT` is the name of one of the [available scripts](src/ryebot/scripts) that is to be executed by Ryebot.

Ryebot needs to login to the wiki. The credentials for this login are currently by default loaded from environment variables which are to be named `RYEBOT_USERNAME` (user name of the bot account + `@` + name of the bot password) and `RYEBOT_PASSWORD` (bot password).
