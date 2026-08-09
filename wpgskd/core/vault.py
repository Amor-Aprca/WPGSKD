import logging
import sqlite3
import os
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

import requests

from wpgskd.core.atomic_sql import AtomicSQL

log = logging.getLogger("Vault")


class InsertResult(Enum):
    FAILURE = 0
    SUCCESS = 1
    ALREADY_EXISTS = 2


class BaseVault(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def get_key(self, table: str, kid: str, title_id: str = "") -> Optional[str]:
        pass

    @abstractmethod
    def insert_key(self, table: str, kid: str, key: str, title: str = "", commit: bool = True) -> InsertResult:
        pass

    def create_table(self, table: str):
        pass

    def commit(self):
        pass


class LocalVault(BaseVault):
    def __init__(self, name: str, path: str, **kwargs):
        super().__init__(name)
        from wpgskd.config import directories 
        db_path = path.format(data_dir=directories.data)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        self.con = sqlite3.connect(db_path)
        self.adb = AtomicSQL()
        self.ticket = self.adb.load(self.con)

    def table_exists(self, table: str) -> bool:
        r = self.adb.safe_execute(self.ticket, lambda db, cursor: cursor.execute(
            "SELECT count(name) FROM sqlite_master WHERE type='table' AND name=?", [table]
        )).fetchone()
        return r[0] == 1

    def create_table(self, table: str):
        if not self.table_exists(table):
            self.adb.safe_execute(self.ticket, lambda db, cursor: cursor.execute(
                f"""CREATE TABLE `{table}` (
                    "id" INTEGER NOT NULL UNIQUE,
                    "kid" TEXT NOT NULL COLLATE NOCASE,
                    "key_" TEXT NOT NULL COLLATE NOCASE,
                    "title" TEXT,
                    PRIMARY KEY("id" AUTOINCREMENT),
                    UNIQUE("kid", "key_")
                );"""
            ))
            self.adb.commit(self.ticket)

    def get_key(self, table: str, kid: str, title_id: str = "") -> Optional[str]:
        if not self.table_exists(table):
            return None
        r = self.adb.safe_execute(self.ticket, lambda db, cursor: cursor.execute(
            f"SELECT `key_` FROM `{table}` WHERE `kid`=?", [kid]
        )).fetchone()
        return r[0] if r else None

    def insert_key(self, table: str, kid: str, key: str, title: str = "", commit: bool = True) -> InsertResult:
        self.create_table(table)
        exists = self.adb.safe_execute(self.ticket, lambda db, cursor: cursor.execute(
            f"SELECT `id` FROM `{table}` WHERE `kid`=? AND `key_`=?", [kid, key]
        )).fetchone()
        if exists:
            return InsertResult.ALREADY_EXISTS
        
        self.adb.safe_execute(self.ticket, lambda db, cursor: cursor.execute(
            f"INSERT INTO `{table}` (kid, key_, title) VALUES (?, ?, ?)", (kid, key, title)
        ))
        if commit:
            self.adb.commit(self.ticket)
        return InsertResult.SUCCESS

    def commit(self):
        self.adb.commit(self.ticket)

class HTTPAPIVault(BaseVault):
    def __init__(self, name: str, host: str, password: str, **kwargs):
        super().__init__(name)
        self.url = host if host.endswith('/') else host + '/'
        self.password = password

    def get_key(self, table: str, kid: str, title_id: str = "") -> Optional[str]:
        payload = {
            "method": "GetKey", 
            "params": {"kid": kid, "service": table, "title": title_id}, 
            "token": self.password
        }
        try:
            res = requests.post(self.url, json=payload).json()
            keys = res.get("keys", [])
            if keys:
                return keys[0].get("key")
        except Exception as e:
            log.error(f"HTTPAPI Vault get failed: {e}")
        return None

    def insert_key(self, table: str, kid: str, key: str, title: str = "", commit: bool = True) -> InsertResult:
        payload = {
            "method": "InsertKey", 
            "params": {"kid": kid, "key": key, "service": table, "title": title}, 
            "token": self.password
        }
        try:
            res = requests.post(self.url, json=payload).json()
            if res.get("inserted"):
                return InsertResult.SUCCESS
            return InsertResult.ALREADY_EXISTS
        except Exception as e:
            log.error(f"HTTPAPI Vault insert failed: {e}")
            return InsertResult.FAILURE


class HTTPVault(BaseVault):
    def __init__(self, name: str, host: str, username: str = "", password: str = "",
                 method: str = "GET", **kwargs):
        super().__init__(name)
        self.url = host if host.endswith('/') else host + '/'
        self.username = username or ""
        self.password = password or ""
        self.method = (method or "GET").upper()
        if self.method not in ("GET", "POST"):
            log.warning(f"HTTPVault '{name}': unsupported method '{method}', using GET")
            self.method = "GET"
        # Basic Auth fallback for servers (like drm-solver) that gate on it
        self._auth = (self.username, self.password) if (self.username or self.password) else None

    @staticmethod
    def _extract_key(data) -> Optional[str]:
        """Normalise the various {"keys":[...]} payload shapes into a hex key."""
        if not isinstance(data, dict):
            return None
        keys = data.get("keys", [])
        if not keys or not isinstance(keys, list):
            return None
        first = keys[0]
        if isinstance(first, dict):
            # {"key": "..."} / {"key_": "..."} / {"kid": "...", "key": "..."}
            return first.get("key") or first.get("key_")
        if isinstance(first, str):
            # "kid:key" or bare hex key
            return first.split(":")[-1] if ":" in first else first
        return None

    def get_key(self, table: str, kid: str, title_id: str = "") -> Optional[str]:
        params = {
            "service": table,
            "kid": kid,
            "username": self.username,
            "password": self.password,
        }
        log.debug(f"Querying {self.name}: {table}/{kid[:8]}... ({self.method})")
        try:
            if self.method == "POST":
                res = requests.post(self.url, json=params, auth=self._auth, timeout=15)
            else:
                res = requests.get(self.url, params=params, auth=self._auth, timeout=15)

            if not res.ok:
                log.error(f"HTTPVault '{self.name}' HTTP {res.status_code}: {res.reason}")
                return None

            key = self._extract_key(res.json())
            if key:
                log.debug(f"KEY found in {self.name}")
            return key
        except Exception as e:
            log.error(f"HTTPVault '{self.name}' get failed: {e}")
            return None

    def insert_key(self, table: str, kid: str, key: str, title: str = "", commit: bool = True) -> InsertResult:
        params = {
            "service": table,
            "kid": kid,
            "key": key,
            "title": title,
            "username": self.username,
            "password": self.password,
        }
        try:
            if self.method == "POST":
                res = requests.post(self.url, json=params, auth=self._auth, timeout=15)
            else:
                res = requests.get(self.url, params=params, auth=self._auth, timeout=15)

            if not res.ok:
                log.error(f"HTTPVault '{self.name}' insert HTTP {res.status_code}: {res.reason}")
                return InsertResult.FAILURE

            data = res.json() if res.text else {}
            if data.get("status_code") == 200 or res.status_code == 200:
                if data.get("inserted"):
                    log.debug(f"Cached key {kid[:8]}... to {self.name}")
                    return InsertResult.SUCCESS
                return InsertResult.ALREADY_EXISTS
            return InsertResult.FAILURE
        except Exception as e:
            log.error(f"HTTPVault '{self.name}' insert failed: {e}")
            return InsertResult.FAILURE
