from __future__ import annotations

import asyncio
import copy
import time

from voicelink.mongodb import MongoDBHandler


class _FakeMongoDatabase:
    def __getitem__(self, name: str) -> object:
        return object()


class _FakeMongoClient:
    options: dict = {}

    def __init__(self, uri: str, **kwargs) -> None:
        self.uri = uri
        self.options = kwargs
        _FakeMongoClient.options = kwargs

    async def server_info(self) -> dict:
        return {}

    def __getitem__(self, name: str) -> _FakeMongoDatabase:
        return _FakeMongoDatabase()


def test_cleanup_cache_removes_expired_settings_and_user_entries() -> None:
    original_settings = copy.deepcopy(MongoDBHandler._settings_buffer)
    original_users = copy.deepcopy(MongoDBHandler._users_buffer)
    original_last_access = copy.deepcopy(MongoDBHandler._last_access)
    try:
        expired_at = time.time() - MongoDBHandler._CACHE_TTL - 1
        MongoDBHandler._settings_buffer = {100: {"_id": 100}}
        MongoDBHandler._users_buffer = {200: {"_id": 200}}
        MongoDBHandler._last_access = {100: expired_at, 200: expired_at}

        asyncio.run(MongoDBHandler.cleanup_cache())

        assert MongoDBHandler._settings_buffer == {}
        assert MongoDBHandler._users_buffer == {}
        assert MongoDBHandler._last_access == {}
    finally:
        MongoDBHandler._settings_buffer = original_settings
        MongoDBHandler._users_buffer = original_users
        MongoDBHandler._last_access = original_last_access


def test_mongodb_pool_defaults_are_small_for_single_guild_homelab(monkeypatch) -> None:
    original_client = MongoDBHandler._client
    original_db = MongoDBHandler._db
    original_settings_db = MongoDBHandler._settings_db
    original_users_db = MongoDBHandler._users_db
    try:
        MongoDBHandler._client = None
        MongoDBHandler._db = None
        MongoDBHandler._settings_db = None
        MongoDBHandler._users_db = None
        monkeypatch.delenv("MONGODB_MAX_POOL_SIZE", raising=False)
        monkeypatch.delenv("MONGODB_MIN_POOL_SIZE", raising=False)
        monkeypatch.setattr("voicelink.mongodb.AsyncIOMotorClient", _FakeMongoClient)

        asyncio.run(MongoDBHandler.init("mongodb://mongo:27017", "vocard"))

        assert _FakeMongoClient.options["maxPoolSize"] == 10
        assert _FakeMongoClient.options["minPoolSize"] == 0
        assert _FakeMongoClient.options["serverSelectionTimeoutMS"] == 10000
        assert _FakeMongoClient.options["connectTimeoutMS"] == 10000
        assert _FakeMongoClient.options["socketTimeoutMS"] == 30000
        assert _FakeMongoClient.options["waitQueueTimeoutMS"] == 10000
    finally:
        MongoDBHandler._client = original_client
        MongoDBHandler._db = original_db
        MongoDBHandler._settings_db = original_settings_db
        MongoDBHandler._users_db = original_users_db


def test_get_settings_cache_hit_does_not_require_global_lock(monkeypatch) -> None:
    class _FailIfEnteredLock:
        async def __aenter__(self):
            raise AssertionError("cache hit should not enter the global MongoDB lock")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    original_lock = MongoDBHandler._lock
    original_buffer = copy.deepcopy(MongoDBHandler._settings_buffer)
    original_last_access = copy.deepcopy(MongoDBHandler._last_access)
    try:
        MongoDBHandler._lock = _FailIfEnteredLock()
        MongoDBHandler._settings_buffer = {321: {"_id": 321, "lang": "VN"}}
        MongoDBHandler._last_access = {}
        monkeypatch.setattr(MongoDBHandler, "_is_allowed_settings_guild", staticmethod(lambda guild_id: guild_id == 321))

        settings = asyncio.run(MongoDBHandler.get_settings(321))

        assert settings["lang"] == "VN"
        assert 321 in MongoDBHandler._last_access
    finally:
        MongoDBHandler._lock = original_lock
        MongoDBHandler._settings_buffer = original_buffer
        MongoDBHandler._last_access = original_last_access


def test_get_user_cache_hit_does_not_require_global_lock() -> None:
    class _FailIfEnteredLock:
        async def __aenter__(self):
            raise AssertionError("user cache hit should not enter the global MongoDB lock")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    original_lock = MongoDBHandler._lock
    original_buffer = copy.deepcopy(MongoDBHandler._users_buffer)
    original_last_access = copy.deepcopy(MongoDBHandler._last_access)
    try:
        MongoDBHandler._lock = _FailIfEnteredLock()
        MongoDBHandler._users_buffer = {654: {"_id": 654, "history": ["track-a"]}}
        MongoDBHandler._last_access = {}

        user = asyncio.run(MongoDBHandler.get_user(654))

        assert user["history"] == ["track-a"]
        assert 654 in MongoDBHandler._last_access
    finally:
        MongoDBHandler._lock = original_lock
        MongoDBHandler._users_buffer = original_buffer
        MongoDBHandler._last_access = original_last_access
