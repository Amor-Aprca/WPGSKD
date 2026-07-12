import logging
import sqlite3
import os
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

import requests

from wpgskd.utils.AtomicSQL import AtomicSQL

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