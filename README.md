# Ryebot

**Ryebot** is a tool for automated [wiki](https://en.wikipedia.org/wiki/Wiki) editing via a series of scripts.
It is designed for usage on [The Official Terraria Wiki](https://terraria.wiki.gg) on wiki.gg, but it should be easy to adapt it to other wikis and wiki platforms, particularly Fandom.
This depends largely on the underlying wiki client library, [custom_mwclient](https://github.com/h9a-rD4ubXs8/custom_mwclient), a wrapper around [mwclient](https://pypi.org/project/mwclient).

Ryebot supports being executed via GitHub Actions. For the Terraria Wiki, see [qt-6/ryebot-ctrl](https://github.com/qt-6/ryebot-ctrl).

## Installation

Python 3.12 or newer is required.

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

Display a brief help text with a list of all available scripts via the following command:

```
python3 -m ryebot --help
```

### Login

Ryebot needs to login to the wiki. It requires a "bot password" for this (which can be created for any account, not just designated bot accounts). This can be created at `Special:BotPasswords` of the wiki that Ryebot will run on.

The bot password's "name" and the actual password need to be stored in environment variables named `RYEBOT_USERNAME` (name of the user account + `@` + name of the bot password) and `RYEBOT_PASSWORD` (the actual bot password). This is currently the only method of authentication.

Example: Your user account is `User:John Doe`. Head to `Special:BotPasswords` and create a bot password named `ryebot` with all the necessary rights. Copy the long alphanumeric string displayed when finishing the creation of the bot password (this is the actual bot password) and paste it in the environment variable `RYEBOT_PASSWORD`. In the environment variable `RYEBOT_USERNAME`, put `John Doe@ryebot`.
