from collections.abc import MutableMapping
import copy
import logging

import mwparserfromhell

from ryebot.bot import Bot
from ryebot.errors import NonexistentScriptConfigPageError


logger = logging.getLogger(__name__)


class ScriptConfiguration(MutableMapping):
    """Configuration parameters for a script.

    >>> cfg = ScriptConfiguration("myscript", {"foo": 1, "bar": True})
    >>> cfg["foo"] += 1
    >>> cfg.update({"bar": False, "baz": 10.5})
    >>> cfg
    {"foo": 2, "bar": False, "baz": 10.5}
    >>> cfg.is_default()
    False
    >>> list(cfg.items())
    [("foo", 2), ("bar", False), ("baz", 10.5)]
    """

    def __init__(self, scriptname: str, default_config: dict = {}):
        self.name = scriptname
        self._default_config = default_config
        self._config = copy.deepcopy(self._default_config)

    def __str__(self):
        return str(self._config)

    # the collections.abc.MutableMapping subclassing allows mostly treating
    # objects of this class as dicts, e.g. update() or pop() are available.
    # some functions still need to be implemented here:
    def __getitem__(self, key):
        return self._config[key]
    def __setitem__(self, key, value):
        self._config[key] = value
    def __delitem__(self, key):
        del self._config[key]
    def __iter__(self):
        return iter(self._config)
    def __len__(self):
        return len(self._config)
    # now we can do e.g.:
    # cfg = ScriptConfiguration()
    # cfg["foo"] += len(cfg)
    # etc.


    def is_default(self):
        """Check if the current configuration is the same as the default from the initialization."""
        return self._config == self._default_config


    def set_from_wiki(self, pagename: str = ''):
        """Update the configuration from a page on the wiki.

        `pagename` will default to the standard location if omitted or blank.
        """
        if not pagename:
            pagename = f'User:Ryebot/bot/scripts/{self.name}/config'
        page = Bot.site.pages[pagename]
        if not page.exists:
            raise NonexistentScriptConfigPageError(self.name, pagename)
        pagewikitext = mwparserfromhell.parse(page.text())  # turn text into mwpfh.Wikicode

        config_from_wiki = {}
        page_template_calls = pagewikitext.filter_templates()
        if len(page_template_calls) == 0:  # no templates on the page
            return
        for p in page_template_calls[0].params:
            param_name = p.name.strip_code()
            param_value = p.value.strip_code()
            # attempt to convert to Boolean
            if param_value.lower() in ("true", "false"):
                cfg_value = param_value.lower() == "true"
            # attempt to convert to int or float
            else:
                try:
                    cfg_value = int(param_value)
                except ValueError:
                    try:
                        cfg_value = float(param_value)
                    except ValueError:
                        cfg_value = param_value
            config_from_wiki[param_name] = cfg_value
        self._config = config_from_wiki
        self._ensure_default_keys()


    def _ensure_default_keys(self):
        """Ensure that all keys from the default configuration are present.

        For the ones that aren't, add them with the default value.
        """

        for key, value in self._default_config.items():
            self._config.setdefault(key, value)
