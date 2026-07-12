import hashlib
import re
from typing import Optional

import requests
import validators

class Credential:
    """Username (or Email) and Password Credential."""

    def __init__(self, username: str, password: str, extra: Optional[str] = None):
        self.username = username
        self.password = password
        self.extra = extra
        self.sha1 = hashlib.sha1(self.dumps().encode()).hexdigest()

    def __bool__(self):
        return bool(self.username) and bool(self.password)

    def __str__(self):
        return self.dumps()

    def __repr__(self):
        return "{name}({items})".format(
            name=self.__class__.__name__,
            items=", ".join([f"{k}={repr(v)}" for k, v in self.__dict__.items()])
        )

    def dumps(self) -> str:
        """Return credential data as a string."""
        return f"{self.username}:{self.password}" + (f":{self.extra}" if self.extra else "")

    def dump(self, path: str):
        """Write credential data to a file."""
        with open(path, "w", encoding="utf-8") as fd:
            fd.write(self.dumps())

    @classmethod
    def loads(cls, text: str) -> 'Credential':
        """
        Load credential from a text string.
        Format: {username}:{password}[:{extra}]
        """
        text = "".join([x.strip() for x in text.splitlines(keepends=False)]).strip()
        credential = re.fullmatch(r"^([^:]+?):([^:]+?)(?::(.+))?$", text)
        if credential:
            return cls(*credential.groups())
        raise ValueError("No credentials found in text string. Expecting the format `username:password`")

    @classmethod
    def load(cls, uri: str, session: Optional[requests.Session] = None) -> 'Credential':
        """
        Load Credential from a remote URL string or a local file path.
        """
        if validators.url(uri):
            return cls.loads((session or requests).get(uri).text)
        else:
            with open(uri, encoding="utf-8") as fd:
                return cls.loads(fd.read())