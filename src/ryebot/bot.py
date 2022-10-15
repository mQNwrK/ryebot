class Bot():
    """Provides module-wide variables and functions."""
    is_on_github_actions = False
    scriptname_to_run = ''
    dry_run = False
    site = None
    other_sites = {}
    common_summary_suffix = ''

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
        return summary_core_text + Bot.common_summary_suffix
