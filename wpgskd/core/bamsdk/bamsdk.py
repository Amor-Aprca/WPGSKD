import requests

from wpgskd.core.bamsdk.services.account import account
from wpgskd.core.bamsdk.services.bamIdentity import bamIdentity
from wpgskd.core.bamsdk.services.content import content
from wpgskd.core.bamsdk.services.device import device
from wpgskd.core.bamsdk.services.drm import drm
from wpgskd.core.bamsdk.services.media import media
from wpgskd.core.bamsdk.services.session import session
from wpgskd.core.bamsdk.services.token import token


class BamSdk:
    def __init__(self, endpoint, session_=None):
        self._session = session_ or requests.Session()

        self.config = self._session.get(endpoint).json()
        self.application = self.config["application"]
        self.commonHeaders = self.config["commonHeaders"]

        self.account = account(self.config["services"]["account"], self._session)
        self.bamIdentity = bamIdentity(self.config["services"]["bamIdentity"], self._session)
        self.content = content(self.config["services"]["content"], self._session)
        self.device = device(self.config["services"]["device"], self._session)
        self.drm = drm(self.config["services"]["drm"], self._session)
        self.media = media(self.config["services"]["media"], self._session)
        self.session = session(self.config["services"]["session"], self._session)
        self.token = token(self.config["services"]["token"], self._session)
