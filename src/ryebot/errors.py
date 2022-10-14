class WrongUserError(Exception):
    def __init__(self, expected_user: str, actual_user: str):
        self.expected_user = expected_user
        self.actual_user = actual_user

    def __str__(self):
        return (
            f'Target user was "{self.expected_user}", current user is '
            f'"{self.actual_user}"!'
        )


class WrongWikiError(Exception):
    def __init__(self, expected_wiki: str, actual_wiki: str, fullurl: str):
        self.expected_wiki = expected_wiki
        self.actual_wiki = actual_wiki
        self.fullurl = fullurl

    def __str__(self):
        return (
            f'Target wiki was "{self.expected_wiki}", current wiki is '
            f'"{self.actual_wiki}" ({self.fullurl})!'
        )
