from custom_mwclient import WikiClient


class _Bot(type):
    """Metaclass for providing read-only class properties to `Bot`."""

    @property  # read-only attribute
    def scriptname_to_run(cls):
        return cls._scriptname_to_run

    @property  # read-only attribute
    def dry_run(cls):
        return cls._dry_run

    @property  # read-only attribute
    def is_on_github_actions(cls):
        return cls._is_on_github_actions


class Bot(metaclass=_Bot):
    """Provides module-wide variables and functions."""

    _scriptname_to_run: str = ''
    _dry_run: bool = False
    _is_on_github_actions: bool = False
    site: WikiClient = None
    other_sites: dict[str, WikiClient] = {}
    common_summary_suffix: str = ''
    script_output: str = ''

    def init_from_commandline_parameters(scriptname_to_run: str, dry_run: bool, is_on_github_actions: bool):
        Bot._scriptname_to_run = scriptname_to_run
        Bot._dry_run = dry_run
        Bot._is_on_github_actions = is_on_github_actions

    def summary(summary_core_text: str = ''):
        """Append the common suffix, truncating the core text if necessary."""
        hard_limit = 500
        coretext_limit = hard_limit - len(Bot.common_summary_suffix)
        if coretext_limit >= 4:
            # if the common suffix leaves fewer than 4 characters, then don't do
            # anything and just let MediaWiki truncate the summary
            # (the suffix will be cut, but the user could've anticipated this
            # if they put such a long suffix)
            if len(summary_core_text) > coretext_limit:
                summary_core_text = summary_core_text[:coretext_limit - 3] + "..."
        suffix = Bot.common_summary_suffix
        if summary_core_text == '':
            suffix = suffix.lstrip()  # prevent leading spaces from the suffix
        return summary_core_text + suffix
