"""
Iris Chat Memory - 画像存储组件

使用 AstrBot KV 存储 API 实现画像数据持久化。
支持群聊隔离和人格隔离。
"""

import asyncio
import functools
import hashlib
import inspect
import json
import threading
import time
import weakref
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Set

from iris_memory.config import get_config
from iris_memory.core import Component, get_logger
from iris_memory.core.storage import KVStorage

from .models import (
    GroupProfile,
    UserProfile,
    dict_to_group_profile,
    dict_to_user_profile,
    profile_to_dict,
)
from .response_preferences import (
    APPROVAL_TTL_SECONDS,
    APPROVED,
    FAMILIAR,
    MEMORY_RETRIEVAL_ON,
    MEMORY_RETRIEVAL_PARAMETER,
    PENDING,
    RELATIONSHIP_FAMILIARITY_PARAMETER,
    RESPONSE_EXPANSION_PARAMETER,
    RESPONSE_LENGTH_PARAMETER,
    RESPONSE_PREFERENCE_KV_KEY,
    RESPONSE_PREFERENCE_SCHEMA_VERSION,
    REVOKED,
    SHORT,
    SUPERSEDED,
    SUSPENDED,
    PreferenceOperationResult,
    ResponsePreferenceIntegrityError,
    ResponsePreferenceRecord,
    ResponsePreferenceScope,
    ResponsePreferenceSource,
    candidate_id_for,
    event_contains_indirect_content,
    explicit_relationship_familiarity_value,
    explicit_response_preference_value,
    normalize_response_preference_value,
    scope_from_event,
    source_from_event,
    source_from_p2b_behavior_candidate,
    source_from_response_length_feedback_aggregate,
)

if TYPE_CHECKING:
    pass

logger = get_logger("profile")
_MISSING = object()


class ResponsePreferenceCommittedUnverifiedError(ResponsePreferenceIntegrityError):
    """CAS committed, but the required post-commit readback was unavailable."""


@dataclass(frozen=True)
class ResponsePreferenceRevocationPlan:
    """One verified, read-only plan for a single historical revocation."""

    candidate_id: str
    scope: ResponsePreferenceScope
    source: ResponsePreferenceSource
    record_sha256: str
    namespace_payload_sha256: str


@dataclass(frozen=True)
class ResponsePreferenceRepairResult:
    """Return the result of one bounded repair operation."""

    success: bool
    code: str
    plan: ResponsePreferenceRevocationPlan | None = None
    after_payload_sha256: str | None = None
    backup_dir: Path | None = None


def _response_preference_payload_hash(payload: object) -> str:
    """Return a stable hash for a decoded response-preference payload."""

    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _decode_response_preference_payload(raw: object) -> list[ResponsePreferenceRecord]:
    """Strictly decode the sole response-preference KV namespace."""

    if not isinstance(raw, dict) or set(raw) != {"schema_version", "records"}:
        raise ResponsePreferenceIntegrityError("invalid response preference store")
    if raw["schema_version"] != RESPONSE_PREFERENCE_SCHEMA_VERSION:
        raise ResponsePreferenceIntegrityError("unknown response preference schema")
    if type(raw["records"]) is not list:
        raise ResponsePreferenceIntegrityError("response preference records must be a list")
    return [ResponsePreferenceRecord.from_dict(item) for item in raw["records"]]


# The response-preference payload is one plugin-wide JSON value.  Every
# ProfileStorage instance in the AstrBot process must therefore share the same
# read-modify-write lock.  An instance-local lock can lose an independently
# created candidate when two component wrappers point at the same KV owner.
# SharedPreferences itself is bound to one running event loop, so a per-loop
# lock preserves that boundary and also keeps isolated test loops independent.
_RESPONSE_PREFERENCE_LOCKS: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, asyncio.Lock
] = weakref.WeakKeyDictionary()
_RESPONSE_PREFERENCE_LOCKS_GUARD = threading.Lock()


def _response_preference_process_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    with _RESPONSE_PREFERENCE_LOCKS_GUARD:
        lock = _RESPONSE_PREFERENCE_LOCKS.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            _RESPONSE_PREFERENCE_LOCKS[loop] = lock
        return lock

GROUP_PROFILE_WRITABLE_FIELDS: Set[str] = {
    "group_name",
    "interests",
    "atmosphere_tags",
    "long_term_tags",
    "blacklist_topics",
    "custom_fields",
}

USER_PROFILE_WRITABLE_FIELDS: Set[str] = {
    "user_name",
    "historical_names",
    "personality_tags",
    "interests",
    "occupation",
    "language_style",
    "communication_style",
    "emotional_baseline",
    "favorability",
    "bot_relationship",
    "important_dates",
    "taboo_topics",
    "important_events",
    "custom_fields",
}


def profile_lock(kind: str):
    """装饰器：为画像 read-modify-write 操作按命名空间串行化加锁。

    kind="user" 时按 (persona, group, user) 维度加锁，kind="group" 时按
    (persona, group) 维度加锁，确保同一画像的并发「读→改→写」不会交错、
    丢失彼此的更新。通过签名绑定提取参数，被装饰方法体无需任何改动。
    """

    def decorator(func):
        sig = inspect.signature(func)

        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            bound = sig.bind(self, *args, **kwargs)
            bound.apply_defaults()
            persona_id = bound.arguments.get("persona_id", "default")
            if kind == "user":
                user_id = bound.arguments.get("user_id")
                group_id = bound.arguments.get("group_id", "default")
                async with self._storage.lock_user(user_id, group_id, persona_id):
                    return await func(self, *args, **kwargs)
            else:
                group_id = bound.arguments.get("group_id")
                async with self._storage.lock_group(group_id, persona_id):
                    return await func(self, *args, **kwargs)

        return wrapper

    return decorator


class ProfileStorage(Component):
    """画像存储组件

    使用 AstrBot KV 存储 API，支持群聊隔离和人格隔离。

    存储键格式：
        - 群聊画像：group_profile:{persona_id}:{group_id}
        - 用户画像：user_profile:{persona_id}:{group_id}:{user_id}

    Attributes:
        _storage: KV 存储适配器
        _is_available: 组件是否可用
    """

    def __init__(self, storage: KVStorage):
        """初始化画像存储组件

        Args:
            storage: KV 存储适配器（实现 KVStorage 协议的对象）
        """
        super().__init__()
        self._storage = storage
        # RMW 串行化锁：按画像命名空间（persona/group/user）分配，避免并发丢失更新
        self._locks: dict = {}
        self._locks_guard = asyncio.Lock()
        # 索引列表（user_index/group_index）读-改-写的全局锁
        self._index_lock = asyncio.Lock()
        # Response-preference RMW uses the process-wide per-loop lock above;
        # the payload has one KV owner even when more than one wrapper exists.

    @property
    def name(self) -> str:
        """组件名称"""
        return "profile"

    async def initialize(self) -> None:
        """初始化画像存储"""
        config = get_config()

        if not config.get("profile.enable"):
            self._is_available = False
            logger.info("画像系统未启用")
            return

        self._is_available = True
        logger.info("画像存储组件初始化完成")

    async def shutdown(self) -> None:
        """关闭存储"""
        self._reset_state()
        logger.info("画像存储组件已关闭")

    async def get_group_profile(
        self, group_id: str, persona_id: str = "default"
    ) -> Optional[GroupProfile]:
        """获取群聊画像

        Args:
            group_id: 群聊ID
            persona_id: 人格ID（默认为 "default"）

        Returns:
            群聊画像对象，不存在则返回 None
        """
        if not self._is_available:
            return None

        persona_id = self._effective_persona(persona_id)
        key = f"group_profile:{persona_id}:{group_id}"

        try:
            data = await self._storage.get_kv_data(key, None)

            if data:
                profile = dict_to_group_profile(data)
                logger.debug(f"获取群聊画像成功: {key}")
                return profile

            logger.debug(f"群聊画像不存在: {key}")
            return None

        except Exception as e:
            logger.error(f"获取群聊画像失败: {key}, 错误: {e}")
            return None

    async def save_group_profile(
        self,
        profile: GroupProfile,
        increment_version: bool = True,
        persona_id: str = "default",
    ) -> None:
        if not self._is_available:
            return

        if increment_version:
            profile.version += 1

        persona_id = self._effective_persona(persona_id)
        key = f"group_profile:{persona_id}:{profile.group_id}"

        try:
            data = profile_to_dict(profile)
            await self._storage.put_kv_data(key, data)
            await self._add_to_group_index(profile.group_id, persona_id)
            await self._add_to_persona_index(persona_id)
            logger.debug(f"保存群聊画像成功: {key}, version={profile.version}")

        except Exception as e:
            logger.error(f"保存群聊画像失败: {key}, 错误: {e}")

    async def get_user_profile(
        self, user_id: str, group_id: str = "default", persona_id: str = "default"
    ) -> Optional[UserProfile]:
        """获取用户画像

        Args:
            user_id: 用户ID
            group_id: 群聊ID（全局模式传 "default"）
            persona_id: 人格ID（默认为 "default"）

        Returns:
            用户画像对象，不存在则返回 None
        """
        if not self._is_available:
            return None

        persona_id = self._effective_persona(persona_id)
        key = f"user_profile:{persona_id}:{group_id}:{user_id}"

        try:
            data = await self._storage.get_kv_data(key, None)

            if data:
                profile = dict_to_user_profile(data)
                logger.debug(f"获取用户画像成功: {key}")
                return profile

            logger.debug(f"用户画像不存在: {key}")
            return None

        except Exception as e:
            logger.error(f"获取用户画像失败: {key}, 错误: {e}")
            return None

    async def save_user_profile(
        self,
        profile: UserProfile,
        group_id: str = "default",
        increment_version: bool = True,
        persona_id: str = "default",
    ) -> None:
        if not self._is_available:
            return

        if increment_version:
            profile.version += 1

        persona_id = self._effective_persona(persona_id)
        key = f"user_profile:{persona_id}:{group_id}:{profile.user_id}"

        try:
            data = profile_to_dict(profile)
            await self._storage.put_kv_data(key, data)
            await self._add_to_user_index(profile.user_id, group_id, persona_id)
            await self._add_to_persona_index(persona_id)
            logger.debug(f"保存用户画像成功: {key}, version={profile.version}")

        except Exception as e:
            logger.error(f"保存用户画像失败: {key}, 错误: {e}")

    def _effective_persona(self, persona_id: str) -> str:
        """规范化 persona_id

        隔离未启用时强制返回 "default"（即便调用方传入了具体 persona，
        也不应产生非 default 的存储键）。隔离启用时返回传入值，空值兜底 "default"。
        """
        if not persona_id:
            return "default"
        try:
            if not get_config().get("isolation_config.enable_persona_isolation"):
                return "default"
        except RuntimeError:
            return "default"
        return persona_id

    async def _get_lock(self, key: str) -> asyncio.Lock:
        """获取（或创建）指定命名空间的 RMW 锁。"""
        async with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    @asynccontextmanager
    async def lock_group(self, group_id: str, persona_id: str = "default"):
        """群聊画像 RMW 串行化锁。同一 (persona, group) 的读-改-写不会被并发交错。"""
        persona_id = self._effective_persona(persona_id)
        lock = await self._get_lock(f"group:{persona_id}:{group_id}")
        async with lock:
            yield

    @asynccontextmanager
    async def lock_user(
        self, user_id: str, group_id: str = "default", persona_id: str = "default"
    ):
        """用户画像 RMW 串行化锁。同一 (persona, group, user) 的读-改-写不会被并发交错。"""
        persona_id = self._effective_persona(persona_id)
        lock = await self._get_lock(f"user:{persona_id}:{group_id}:{user_id}")
        async with lock:
            yield

    async def update_group_profile(
        self, group_id: str, updates: dict, persona_id: str = "default"
    ) -> bool:
        """更新群聊画像

        Args:
            group_id: 群聊ID
            updates: 更新字段字典
            persona_id: 人格ID

        Returns:
            是否更新成功
        """
        try:
            # 读-改-写必须持锁，否则与消息驱动 update_from_analysis 并发时
            # 互相覆盖（lost update）。Web 路由 /profile/*/update 直接调此方法，
            # 此前未加锁，而管理器同类更新都持命名空间锁。
            async with self.lock_group(group_id, persona_id):
                profile = await self.get_group_profile(group_id, persona_id)

                if not profile:
                    profile = GroupProfile(group_id=group_id)

                for key, value in updates.items():
                    if key in GROUP_PROFILE_WRITABLE_FIELDS:
                        setattr(profile, key, value)

                await self.save_group_profile(profile, persona_id=persona_id)

            logger.info(f"更新群聊画像成功: {group_id}")
            return True

        except Exception as e:
            logger.error(f"更新群聊画像失败: {e}", exc_info=True)
            return False

    async def update_user_profile(
        self, user_id: str, group_id: str, updates: dict, persona_id: str = "default"
    ) -> bool:
        """更新用户画像

        Args:
            user_id: 用户ID
            group_id: 群聊ID
            updates: 更新字段字典
            persona_id: 人格ID

        Returns:
            是否更新成功
        """
        try:
            # 读-改-写必须持锁，否则与消息驱动 update_from_analysis 并发时
            # 互相覆盖（lost update）。Web 路由 /profile/*/update 直接调此方法，
            # 此前未加锁，而管理器同类更新都持命名空间锁。
            async with self.lock_user(user_id, group_id, persona_id):
                profile = await self.get_user_profile(user_id, group_id, persona_id)

                if not profile:
                    profile = UserProfile(user_id=user_id)

                for key, value in updates.items():
                    if key in USER_PROFILE_WRITABLE_FIELDS:
                        setattr(profile, key, value)

                await self.save_user_profile(
                    profile, group_id=group_id, persona_id=persona_id
                )

            logger.info(f"更新用户画像成功: {user_id}@{group_id}")
            return True

        except Exception as e:
            logger.error(f"更新用户画像失败: {e}", exc_info=True)
            return False

    async def list_groups(self, persona_id: str = "default") -> list:
        persona_id = self._effective_persona(persona_id)
        index_key = f"group_index:{persona_id}"

        try:
            group_ids = await self._storage.get_kv_data(index_key, [])

            if not group_ids:
                return []

            tasks = [
                self.get_group_profile(group_id, persona_id) for group_id in group_ids
            ]
            profiles = await asyncio.gather(*tasks, return_exceptions=True)

            groups = []
            for group_id, profile in zip(group_ids, profiles):
                if isinstance(profile, Exception):
                    logger.warning(f"获取群聊画像失败: {group_id}, 错误: {profile}")
                    continue
                if profile and isinstance(profile, GroupProfile):
                    groups.append(
                        {
                            "group_id": group_id,
                            "group_name": profile.group_name or group_id,
                        }
                    )

            return groups

        except Exception as e:
            logger.error(f"获取群聊列表失败: {e}", exc_info=True)
            return []

    async def list_users(
        self, group_id: str = "default", persona_id: str = "default"
    ) -> list:
        persona_id = self._effective_persona(persona_id)
        index_key = f"user_index:{persona_id}:{group_id}"

        try:
            user_ids = await self._storage.get_kv_data(index_key, [])

            if not user_ids:
                return []

            tasks = [
                self.get_user_profile(user_id, group_id, persona_id)
                for user_id in user_ids
            ]
            profiles = await asyncio.gather(*tasks, return_exceptions=True)

            users = []
            for user_id, profile in zip(user_ids, profiles):
                if isinstance(profile, Exception):
                    logger.warning(f"获取用户画像失败: {user_id}, 错误: {profile}")
                    continue
                if profile and isinstance(profile, UserProfile):
                    users.append(
                        {
                            "user_id": user_id,
                            "nickname": profile.user_name or user_id,
                            "group_id": group_id,
                        }
                    )

            return users

        except Exception as e:
            logger.error(f"获取用户列表失败: {e}", exc_info=True)
            return []

    async def list_all_users(self, persona_id: str = "default") -> list:
        """列出所有群聊下的用户画像

        遍历 user_group_index 获取有用户画像的 group_id 列表，
        再逐个群聊拉取用户列表。用于 Web UI 无指定群聊时展示全部用户。

        Args:
            persona_id: 人格ID

        Returns:
            用户列表，每项包含 user_id / nickname / group_id
        """
        persona_id = self._effective_persona(persona_id)
        ug_index_key = f"user_group_index:{persona_id}"

        try:
            group_ids = await self._storage.get_kv_data(ug_index_key, [])
            if not group_ids:
                return []

            all_users = []
            for gid in group_ids:
                users = await self.list_users(gid, persona_id)
                all_users.extend(users)

            return all_users

        except Exception as e:
            logger.error(f"获取全部用户列表失败: {e}", exc_info=True)
            return []

    async def _add_to_group_index(self, group_id: str, persona_id: str) -> None:
        index_key = f"group_index:{persona_id}"
        try:
            async with self._index_lock:
                group_ids = await self._storage.get_kv_data(index_key, [])
                if group_id not in group_ids:
                    group_ids.append(group_id)
                    await self._storage.put_kv_data(index_key, group_ids)
        except Exception as e:
            logger.error(f"更新群聊索引失败: {e}")

    async def _add_to_user_index(
        self, user_id: str, group_id: str, persona_id: str
    ) -> None:
        index_key = f"user_index:{persona_id}:{group_id}"
        try:
            async with self._index_lock:
                user_ids = await self._storage.get_kv_data(index_key, [])
                if user_id not in user_ids:
                    user_ids.append(user_id)
                    await self._storage.put_kv_data(index_key, user_ids)
                # 同时维护 user_group_index：记录有用户画像的 group_id，
                # 供 delete_all_user_profiles / list_all_users 遍历。
                # group_index 只记录群聊画像的 group_id，当隔离关闭时
                # 用户画像存于 "default" 而 group_index 不含 "default"，
                # 导致按 group_index 遍历会漏删用户画像。
                ug_index_key = f"user_group_index:{persona_id}"
                group_ids = await self._storage.get_kv_data(ug_index_key, [])
                if group_id not in group_ids:
                    group_ids.append(group_id)
                    await self._storage.put_kv_data(ug_index_key, group_ids)
        except Exception as e:
            logger.error(f"更新用户索引失败: {e}")

    async def _add_to_persona_index(self, persona_id: str) -> None:
        """记录出现过的 persona_id，供 delete_all 遍历所有命名空间。"""
        index_key = "persona_index"
        try:
            async with self._index_lock:
                personas = await self._storage.get_kv_data(index_key, [])
                if persona_id not in personas:
                    personas.append(persona_id)
                    await self._storage.put_kv_data(index_key, personas)
        except Exception as e:
            logger.error(f"更新 persona 索引失败: {e}")

    async def _get_known_personas(self) -> list:
        """获取所有已知 persona_id（始终包含 default 兜底）。"""
        personas = await self._storage.get_kv_data("persona_index", [])
        if "default" not in personas:
            personas = ["default", *personas]
        return personas

    async def delete_user_profile(
        self, user_id: str, group_id: str = "default", persona_id: str = "default"
    ) -> bool:
        """删除用户画像

        Args:
            user_id: 用户ID
            group_id: 群聊ID
            persona_id: 人格ID

        Returns:
            是否删除成功
        """
        if not self._is_available:
            return False

        persona_id = self._effective_persona(persona_id)
        key = f"user_profile:{persona_id}:{group_id}:{user_id}"

        try:
            await self._storage.delete_kv_data(key)
            logger.info(f"已删除用户画像: {key}")
            return True

        except Exception as e:
            logger.error(f"删除用户画像失败: {key}, 错误: {e}")
            return False

    async def delete_group_profile(
        self, group_id: str, persona_id: str = "default"
    ) -> bool:
        """删除群聊画像

        Args:
            group_id: 群聊ID
            persona_id: 人格ID

        Returns:
            是否删除成功
        """
        if not self._is_available:
            return False

        persona_id = self._effective_persona(persona_id)
        key = f"group_profile:{persona_id}:{group_id}"

        try:
            await self._storage.delete_kv_data(key)
            logger.info(f"已删除群聊画像: {key}")
            return True

        except Exception as e:
            logger.error(f"删除群聊画像失败: {key}, 错误: {e}")
            return False

    async def delete_all_user_profiles_in_group(self, group_id: str) -> int:
        """删除群聊内所有用户画像

        通过 persona_index / user_index 遍历，无需 KV 列表功能。

        Args:
            group_id: 群聊ID

        Returns:
            删除的画像数量
        """
        if not self._is_available:
            return 0

        deleted = 0
        try:
            for persona_id in await self._get_known_personas():
                user_ids = await self._storage.get_kv_data(
                    f"user_index:{persona_id}:{group_id}", []
                )
                for user_id in user_ids:
                    await self._storage.delete_kv_data(
                        f"user_profile:{persona_id}:{group_id}:{user_id}"
                    )
                    deleted += 1
                if user_ids:
                    await self._storage.delete_kv_data(
                        f"user_index:{persona_id}:{group_id}"
                    )
        except Exception as e:
            logger.error(f"删除群聊内用户画像失败: {e}", exc_info=True)

        logger.info(f"已删除群聊 {group_id} 内 {deleted} 个用户画像")
        return deleted

    async def delete_all_user_profiles(self) -> int:
        """删除所有用户画像

        通过 persona_index / user_group_index / user_index 遍历，无需 KV 列表功能。
        使用 user_group_index（而非 group_index）是因为群聊画像和用户画像的
        group_id 可能不一致：隔离关闭时群聊画像用真实 group_id，用户画像用 "default"。

        Returns:
            删除的画像数量
        """
        if not self._is_available:
            return 0

        deleted = 0
        try:
            for persona_id in await self._get_known_personas():
                ug_index_key = f"user_group_index:{persona_id}"
                group_ids = await self._storage.get_kv_data(ug_index_key, [])
                for group_id in group_ids:
                    user_ids = await self._storage.get_kv_data(
                        f"user_index:{persona_id}:{group_id}", []
                    )
                    for user_id in user_ids:
                        await self._storage.delete_kv_data(
                            f"user_profile:{persona_id}:{group_id}:{user_id}"
                        )
                        deleted += 1
                    if user_ids:
                        await self._storage.delete_kv_data(
                            f"user_index:{persona_id}:{group_id}"
                        )
                if group_ids:
                    await self._storage.delete_kv_data(ug_index_key)
        except Exception as e:
            logger.error(f"删除所有用户画像失败: {e}", exc_info=True)

        logger.info(f"已删除 {deleted} 个用户画像")
        return deleted

    async def delete_all_group_profiles(self) -> int:
        """删除所有群聊画像

        通过 persona_index / group_index 遍历，无需 KV 列表功能。

        Returns:
            删除的画像数量
        """
        if not self._is_available:
            return 0

        deleted = 0
        try:
            for persona_id in await self._get_known_personas():
                group_ids = await self._storage.get_kv_data(
                    f"group_index:{persona_id}", []
                )
                for group_id in group_ids:
                    await self._storage.delete_kv_data(
                        f"group_profile:{persona_id}:{group_id}"
                    )
                    deleted += 1
                if group_ids:
                    await self._storage.delete_kv_data(f"group_index:{persona_id}")
        except Exception as e:
            logger.error(f"删除所有群聊画像失败: {e}", exc_info=True)

        logger.info(f"已删除 {deleted} 个群聊画像")
        return deleted

    async def delete_all_profiles(self) -> dict:
        """删除所有画像（用户画像 + 群聊画像）

        Returns:
            删除统计 {"user_profiles": int, "group_profiles": int}
        """
        user_count = await self.delete_all_user_profiles()
        group_count = await self.delete_all_group_profiles()

        # 清理 persona_index（所有命名空间已清空，索引不再有意义）
        try:
            await self._storage.delete_kv_data("persona_index")
        except Exception as e:
            logger.warning(f"清理 persona_index 失败: {e}")

        return {"user_profiles": user_count, "group_profiles": group_count}

    async def export_all(self, persona_id: str = "default") -> dict:
        """导出所有画像数据

        Args:
            persona_id: 人格ID，导出该 persona 命名空间下的画像

        Returns:
            包含群聊画像和用户画像的字典
        """
        if not self._is_available:
            return {
                "version": "1.0",
                "export_time": "",
                "groups": [],
                "users": [],
                "stats": {"group_count": 0, "user_count": 0},
            }

        try:
            from datetime import datetime as _dt

            groups = await self.list_groups(persona_id)
            group_profiles = []
            for g in groups:
                profile = await self.get_group_profile(g["group_id"], persona_id)
                if profile:
                    group_profiles.append(profile_to_dict(profile))

            all_users = []
            for g in groups:
                users = await self.list_users(g["group_id"], persona_id)
                for u in users:
                    profile = await self.get_user_profile(
                        u["user_id"], g["group_id"], persona_id
                    )
                    if profile:
                        all_users.append(
                            {
                                **profile_to_dict(profile),
                                "_group_id": g["group_id"],
                            }
                        )

            users_without_group = await self.list_users("default", persona_id)
            for u in users_without_group:
                profile = await self.get_user_profile(
                    u["user_id"], "default", persona_id
                )
                if profile:
                    already = any(
                        p.get("user_id") == u["user_id"]
                        and p.get("_group_id") == "default"
                        for p in all_users
                    )
                    if not already:
                        all_users.append(
                            {
                                **profile_to_dict(profile),
                                "_group_id": "default",
                            }
                        )

            export_time = _dt.now().isoformat()

            logger.info(
                f"画像导出完成：{len(group_profiles)} 个群聊，{len(all_users)} 个用户"
            )

            return {
                "version": "1.0",
                "export_time": export_time,
                "groups": group_profiles,
                "users": all_users,
                "stats": {
                    "group_count": len(group_profiles),
                    "user_count": len(all_users),
                },
            }

        except Exception as e:
            logger.error(f"导出画像失败：{e}", exc_info=True)
            return {
                "version": "1.0",
                "export_time": "",
                "groups": [],
                "users": [],
                "stats": {"group_count": 0, "user_count": 0},
            }

    async def import_from_data(
        self, data: dict, skip_duplicates: bool = True, persona_id: str = "default"
    ) -> dict:
        """从数据字典导入画像

        Args:
            data: 导出数据字典（包含 groups 和 users）
            skip_duplicates: 是否跳过已有画像（否则覆盖更新）
            persona_id: 人格ID，导入到该 persona 命名空间

        Returns:
            导入统计 {"imported_groups": int, "imported_users": int, "skipped": int, "error_count": int}
        """
        if not self._is_available:
            return {
                "imported_groups": 0,
                "imported_users": 0,
                "skipped": 0,
                "error_count": 0,
            }

        groups_data = data.get("groups", [])
        users_data = data.get("users", [])

        imported_groups = 0
        imported_users = 0
        skipped = 0
        error_count = 0

        for group_data in groups_data:
            try:
                group_id = group_data.get("group_id")
                if not group_id:
                    skipped += 1
                    continue

                if skip_duplicates:
                    existing = await self.get_group_profile(group_id, persona_id)
                    if existing:
                        skipped += 1
                        continue

                profile = dict_to_group_profile(group_data)
                await self.save_group_profile(
                    profile, increment_version=False, persona_id=persona_id
                )
                imported_groups += 1

            except Exception as e:
                logger.error(f"导入群聊画像失败：{e}")
                error_count += 1

        for user_data in users_data:
            try:
                user_id = user_data.get("user_id")
                group_id = user_data.pop("_group_id", "default")

                if not user_id:
                    skipped += 1
                    continue

                if skip_duplicates:
                    existing = await self.get_user_profile(
                        user_id, group_id, persona_id
                    )
                    if existing:
                        skipped += 1
                        continue

                profile = dict_to_user_profile(user_data)
                await self.save_user_profile(
                    profile,
                    group_id=group_id,
                    increment_version=False,
                    persona_id=persona_id,
                )
                imported_users += 1

            except Exception as e:
                logger.error(f"导入用户画像失败：{e}")
                error_count += 1

        logger.info(
            f"画像导入完成：群聊 {imported_groups}/{len(groups_data)}，"
            f"用户 {imported_users}/{len(users_data)}，"
            f"跳过 {skipped}，错误 {error_count}"
        )

        return {
            "imported_groups": imported_groups,
            "imported_users": imported_users,
            "skipped": skipped,
            "error_count": error_count,
        }

    # ------------------------------------------------------------------
    # Bounded response-expression preference experiment
    # ------------------------------------------------------------------

    async def _load_response_preference_records(self) -> list[ResponsePreferenceRecord]:
        """Load the dedicated namespace with strict schema decoding."""

        raw = await self._storage.get_kv_data(RESPONSE_PREFERENCE_KV_KEY, None)
        if raw is None:
            return []
        return _decode_response_preference_payload(raw)

    async def _save_response_preference_records(
        self,
        records: list[ResponsePreferenceRecord],
        *,
        expected_raw: object = _MISSING,
        require_cas: bool = False,
    ) -> bool:
        """Persist and read back before reporting a successful mutation."""

        payload = {
            "schema_version": RESPONSE_PREFERENCE_SCHEMA_VERSION,
            "records": [record.to_dict() for record in records],
        }
        cas_committed = False
        if require_cas:
            compare_and_swap = getattr(self._storage, "compare_and_swap_kv_data", None)
            if not callable(compare_and_swap):
                raise ResponsePreferenceIntegrityError(
                    "response preference conditional write unavailable"
                )
            if expected_raw is _MISSING:
                expected_raw = await self._storage.get_kv_data(
                    RESPONSE_PREFERENCE_KV_KEY, None
                )
            committed = await compare_and_swap(
                RESPONSE_PREFERENCE_KV_KEY, expected_raw, payload
            )
            if committed is not True:
                raise ResponsePreferenceIntegrityError(
                    "response preference conditional write rejected"
                )
            cas_committed = True
        else:
            await self._storage.put_kv_data(RESPONSE_PREFERENCE_KV_KEY, payload)
        try:
            saved = await self._storage.get_kv_data(RESPONSE_PREFERENCE_KV_KEY, None)
            if not isinstance(saved, dict) or set(saved) != {"schema_version", "records"}:
                raise ResponsePreferenceIntegrityError("response preference write verification failed")
            if saved["schema_version"] != RESPONSE_PREFERENCE_SCHEMA_VERSION:
                raise ResponsePreferenceIntegrityError("response preference write schema mismatch")
            decoded = [ResponsePreferenceRecord.from_dict(item) for item in saved["records"]]
            if [record.to_dict() for record in decoded] != payload["records"]:
                raise ResponsePreferenceIntegrityError("response preference write readback mismatch")
        except Exception as exc:
            if cas_committed:
                raise ResponsePreferenceCommittedUnverifiedError(
                    "response preference CAS committed but readback was not verified"
                ) from exc
            raise
        return True

    async def publish_p2b_candidate(
        self,
        candidate: object,
        published_by: object,
        *,
        now: float | None = None,
    ) -> PreferenceOperationResult:
        """Explicitly publish one approved P2b candidate into ProfileStorage.

        V1 deliberately accepts only the response-length SHORT candidate.  A
        publication is itself an explicit administrator action; it creates an
        APPROVED response-preference record with the existing seven-day TTL
        and writes it through the Host CAS API.  No other P2b parameter or
        owner (Persona, Affect, Relationship, tools, or participation) is
        reachable from this method.
        """

        if not self._is_available:
            return PreferenceOperationResult(False, "storage_failed")
        if type(published_by) is not str or not published_by.strip():
            return PreferenceOperationResult(False, "storage_failed")

        from iris_memory.cognitive.behavior_candidate import (
            BehaviorCandidate,
            BehaviorParameter,
            CandidateStatus,
        )

        if type(candidate) is not BehaviorCandidate:
            return PreferenceOperationResult(False, "unsupported")
        if candidate.status is CandidateStatus.EXPIRED:
            return PreferenceOperationResult(False, "expired")
        if candidate.status is not CandidateStatus.APPROVED:
            return PreferenceOperationResult(False, "not_approved")
        if (
            candidate.parameter is not BehaviorParameter.RESPONSE_LENGTH
            or candidate.proposed_value != SHORT
            or candidate.scope.scope_kind != "PRIVATE"
        ):
            return PreferenceOperationResult(False, "unsupported")

        published_at = time.time() if now is None else float(now)
        if candidate.expires_at is not None and (
            candidate.expires_at.timestamp() <= published_at
        ):
            return PreferenceOperationResult(False, "expired")
        source = source_from_p2b_behavior_candidate(candidate)
        if source is None:
            return PreferenceOperationResult(False, "unsupported")
        try:
            scope = ResponsePreferenceScope(
                platform_id=candidate.scope.platform_id,
                account_id=candidate.scope.account_id,
                user_id=candidate.scope.user_id,
                conversation_id=candidate.scope.conversation_id,
                scope_kind=candidate.scope.scope_kind,
            )
            record = ResponsePreferenceRecord(
                candidate_id=candidate_id_for(
                    scope, source, SHORT, RESPONSE_LENGTH_PARAMETER
                ),
                scope=scope,
                parameter=RESPONSE_LENGTH_PARAMETER,
                value=SHORT,
                source=source,
                status=APPROVED,
                requested_at=candidate.created_at.timestamp(),
                approved_by=published_by.strip(),
                approved_at=published_at,
                expires_at=published_at + APPROVAL_TTL_SECONDS,
            )
            async with _response_preference_process_lock():
                raw = await self._storage.get_kv_data(
                    RESPONSE_PREFERENCE_KV_KEY, None
                )
                records = _decode_response_preference_payload(raw) if raw is not None else []
                exact = next(
                    (
                        item
                        for item in records
                        if item.scope == scope
                        and item.parameter == RESPONSE_LENGTH_PARAMETER
                        and item.source == source
                    ),
                    None,
                )
                if exact is not None:
                    return PreferenceOperationResult(True, "already_published", exact)
                same_value = next(
                    (
                        item
                        for item in records
                        if item.scope == scope
                        and item.parameter == RESPONSE_LENGTH_PARAMETER
                        and item.value == SHORT
                        and item.status == APPROVED
                        and item.is_active(published_at)
                    ),
                    None,
                )
                if same_value is not None:
                    return PreferenceOperationResult(True, "already_published", same_value)
                conflicting = next(
                    (
                        item
                        for item in records
                        if item.scope == scope
                        and item.parameter == RESPONSE_LENGTH_PARAMETER
                        and item.value != SHORT
                        and item.status in {PENDING, APPROVED}
                        and (
                            item.status == PENDING
                            or item.is_active(published_at)
                        )
                    ),
                    None,
                )
                if conflicting is not None:
                    return PreferenceOperationResult(False, "conflict", conflicting)
                await self._save_response_preference_records(
                    [*records, record], expected_raw=raw, require_cas=True
                )
                return PreferenceOperationResult(True, "published", record)
        except ResponsePreferenceCommittedUnverifiedError:
            logger.exception("P2b 发布已提交但读回未验证")
            return PreferenceOperationResult(False, "committed_unverified")
        except Exception:
            logger.exception("发布 P2b 回复长度候选失败")
            return PreferenceOperationResult(False, "storage_failed")

    async def find_p2b_publication(self, candidate: object) -> ResponsePreferenceRecord | None:
        """Find the exact deterministic publication without exposing other scopes."""
        source = source_from_p2b_behavior_candidate(candidate)
        if source is None or not self._is_available:
            return None
        try:
            scope = ResponsePreferenceScope(
                candidate.scope.platform_id, candidate.scope.account_id,
                candidate.scope.user_id, candidate.scope.conversation_id,
                candidate.scope.scope_kind,
            )
            records = await self._load_response_preference_records()
            matches = [item for item in records if item.scope == scope and item.source == source]
            return matches[0] if len(matches) == 1 else None
        except Exception:
            return None

    async def unpublish_p2b_candidate(
        self, candidate: object, revoked_by: object, *, now: float | None = None
    ) -> PreferenceOperationResult:
        """CAS-revoke the exact response preference created by P2b publication."""
        if type(revoked_by) is not str or not revoked_by.strip() or not self._is_available:
            return PreferenceOperationResult(False, "storage_failed")
        source = source_from_p2b_behavior_candidate(candidate)
        if source is None:
            return PreferenceOperationResult(False, "unsupported")
        revoked_at = time.time() if now is None else float(now)
        try:
            scope = ResponsePreferenceScope(
                candidate.scope.platform_id, candidate.scope.account_id,
                candidate.scope.user_id, candidate.scope.conversation_id,
                candidate.scope.scope_kind,
            )
            async with _response_preference_process_lock():
                raw = await self._storage.get_kv_data(RESPONSE_PREFERENCE_KV_KEY, None)
                records = _decode_response_preference_payload(raw) if raw is not None else []
                indexes = [i for i, item in enumerate(records) if item.scope == scope and item.source == source]
                if len(indexes) != 1:
                    return PreferenceOperationResult(False, "not_found")
                index = indexes[0]
                current = records[index]
                if current.status == REVOKED:
                    return PreferenceOperationResult(True, "already_unpublished", current)
                if current.status != APPROVED:
                    return PreferenceOperationResult(False, "conflict", current)
                records[index] = replace(
                    current, status=REVOKED, revoked_by=revoked_by.strip(), revoked_at=revoked_at
                )
                await self._save_response_preference_records(
                    records, expected_raw=raw, require_cas=True
                )
                return PreferenceOperationResult(True, "unpublished", records[index])
        except ResponsePreferenceCommittedUnverifiedError:
            logger.exception("P2b 撤回已提交但读回未验证")
            return PreferenceOperationResult(False, "committed_unverified")
        except Exception:
            logger.exception("撤回 P2b 回复长度候选失败")
            return PreferenceOperationResult(False, "storage_failed")

    async def dry_run_response_preference_revocation(
        self,
        candidate_id: object,
        scope: object,
        source: object,
        *,
        now: float | None = None,
    ) -> ResponsePreferenceRepairResult:
        """Build one zero-write plan from exact stored identity fields."""

        if not self._is_available:
            return ResponsePreferenceRepairResult(False, "unavailable")
        if type(candidate_id) is not str or not candidate_id.startswith("rspref:"):
            return ResponsePreferenceRepairResult(False, "invalid_candidate")
        if type(scope) is not ResponsePreferenceScope:
            return ResponsePreferenceRepairResult(False, "invalid_scope")
        if type(source) is not ResponsePreferenceSource:
            return ResponsePreferenceRepairResult(False, "invalid_source")
        try:
            async with _response_preference_process_lock():
                raw = await self._storage.get_kv_data(RESPONSE_PREFERENCE_KV_KEY, None)
                if raw is None:
                    return ResponsePreferenceRepairResult(False, "not_found")
                records = _decode_response_preference_payload(raw)
                record = next(
                    (item for item in records if item.candidate_id == candidate_id), None
                )
                if record is None:
                    return ResponsePreferenceRepairResult(False, "not_found")
                if record.scope != scope:
                    return ResponsePreferenceRepairResult(False, "scope_mismatch")
                if record.source != source:
                    return ResponsePreferenceRepairResult(False, "source_mismatch")
                if record.status != APPROVED:
                    return ResponsePreferenceRepairResult(False, "not_approved")
                if not record.is_active(time.time() if now is None else float(now)):
                    return ResponsePreferenceRepairResult(False, "not_active")
                plan = ResponsePreferenceRevocationPlan(
                    candidate_id=record.candidate_id,
                    scope=record.scope,
                    source=record.source,
                    record_sha256=_response_preference_payload_hash(record.to_dict()),
                    namespace_payload_sha256=_response_preference_payload_hash(raw),
                )
                return ResponsePreferenceRepairResult(True, "ready", plan=plan)
        except Exception:
            logger.exception("Response-preference repair dry run failed")
            return ResponsePreferenceRepairResult(False, "read_failed")

    async def execute_response_preference_revocation(
        self,
        plan: object,
        authorization_id: object,
        backup_dir: Path,
        *,
        now: float | None = None,
    ) -> ResponsePreferenceRepairResult:
        """Revoke exactly one preflighted record after backup and hash checks."""

        if not self._is_available:
            return ResponsePreferenceRepairResult(False, "unavailable")
        if type(plan) is not ResponsePreferenceRevocationPlan:
            return ResponsePreferenceRepairResult(False, "invalid_plan")
        if type(authorization_id) is not str or not authorization_id.strip():
            return ResponsePreferenceRepairResult(False, "missing_authorization")
        if not isinstance(backup_dir, Path) or not backup_dir.is_absolute():
            return ResponsePreferenceRepairResult(False, "invalid_backup_dir")
        compare_and_swap = getattr(self._storage, "compare_and_swap_kv_data", None)
        if not callable(compare_and_swap):
            return ResponsePreferenceRepairResult(False, "conditional_write_unavailable")
        try:
            async with _response_preference_process_lock():
                raw = await self._storage.get_kv_data(RESPONSE_PREFERENCE_KV_KEY, None)
                if raw is None:
                    return ResponsePreferenceRepairResult(False, "not_found")
                records = _decode_response_preference_payload(raw)
                index = next(
                    (i for i, item in enumerate(records) if item.candidate_id == plan.candidate_id),
                    None,
                )
                if index is None:
                    return ResponsePreferenceRepairResult(False, "not_found")
                record = records[index]
                if (
                    record.scope != plan.scope
                    or record.source != plan.source
                    or record.status != APPROVED
                    or not record.is_active(time.time() if now is None else float(now))
                    or _response_preference_payload_hash(record.to_dict()) != plan.record_sha256
                    or _response_preference_payload_hash(raw) != plan.namespace_payload_sha256
                ):
                    return ResponsePreferenceRepairResult(False, "skipped_conflict")
                backup_dir.mkdir(parents=True, mode=0o700)
                backup_dir.chmod(0o700)
                records[index] = replace(
                    record,
                    status=REVOKED,
                    revoked_by=f"migration:{authorization_id.strip()}",
                    revoked_at=time.time() if now is None else float(now),
                )
                after_payload = {
                    "schema_version": RESPONSE_PREFERENCE_SCHEMA_VERSION,
                    "records": [item.to_dict() for item in records],
                }
                after_hash = _response_preference_payload_hash(after_payload)
                (backup_dir / "response_style_preference.v1.before.json").write_text(
                    json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2),
                    encoding="utf-8",
                )
                (backup_dir / "manifest.json").write_text(
                    json.dumps(
                        {
                            "authorization_id": authorization_id.strip(),
                            "candidate_id": plan.candidate_id,
                            "record_sha256": plan.record_sha256,
                            "before_payload_sha256": plan.namespace_payload_sha256,
                            "after_payload_sha256": after_hash,
                            "scope": plan.scope.to_dict(),
                            "source": plan.source.to_dict(),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                try:
                    committed = await compare_and_swap(
                        RESPONSE_PREFERENCE_KV_KEY, raw, after_payload
                    )
                except NotImplementedError:
                    return ResponsePreferenceRepairResult(
                        False, "conditional_write_unavailable", plan, after_hash, backup_dir
                    )
                except Exception:
                    # A commit exception cannot prove that SQLite did not commit.
                    return ResponsePreferenceRepairResult(
                        False, "commit_outcome_unknown", plan, after_hash, backup_dir
                    )
                if committed is not True:
                    return ResponsePreferenceRepairResult(
                        False, "skipped_conflict", plan, backup_dir=backup_dir
                    )
                try:
                    saved = await self._storage.get_kv_data(RESPONSE_PREFERENCE_KV_KEY, None)
                    _decode_response_preference_payload(saved)
                except Exception:
                    return ResponsePreferenceRepairResult(
                        False, "committed_unverified", plan, after_hash, backup_dir
                    )
                if _response_preference_payload_hash(saved) != after_hash:
                    return ResponsePreferenceRepairResult(
                        False, "committed_unverified", plan, after_hash, backup_dir
                    )
                try:
                    (backup_dir / "response_style_preference.v1.after.sha256").write_text(
                        after_hash + "\n", encoding="ascii"
                    )
                except OSError:
                    logger.exception("Response-preference repair committed without final backup marker")
                    return ResponsePreferenceRepairResult(
                        False, "committed_unverified", plan, after_hash, backup_dir
                    )
                return ResponsePreferenceRepairResult(
                    True, "revoked", plan, after_hash, backup_dir
                )
        except FileExistsError:
            return ResponsePreferenceRepairResult(False, "backup_exists")
        except Exception:
            logger.exception("Response-preference repair execution failed")
            return ResponsePreferenceRepairResult(False, "write_failed")

    async def restore_response_preference_revocation_backup(
        self, backup_dir: Path, expected_after_payload_sha256: object
    ) -> ResponsePreferenceRepairResult:
        """Restore one repair backup only when the current payload is unchanged."""

        if not self._is_available:
            return ResponsePreferenceRepairResult(False, "unavailable")
        if (
            not isinstance(backup_dir, Path)
            or not backup_dir.is_absolute()
            or type(expected_after_payload_sha256) is not str
        ):
            return ResponsePreferenceRepairResult(False, "invalid_restore_request")
        compare_and_swap = getattr(self._storage, "compare_and_swap_kv_data", None)
        if not callable(compare_and_swap):
            return ResponsePreferenceRepairResult(False, "conditional_write_unavailable")
        try:
            before = json.loads(
                (backup_dir / "response_style_preference.v1.before.json").read_text(
                    encoding="utf-8"
                )
            )
            _decode_response_preference_payload(before)
            manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
            required_manifest_keys = {
                "authorization_id",
                "candidate_id",
                "record_sha256",
                "before_payload_sha256",
                "after_payload_sha256",
                "scope",
                "source",
            }
            if (
                not isinstance(manifest, dict)
                or not required_manifest_keys.issubset(manifest)
                or manifest["after_payload_sha256"] != expected_after_payload_sha256
                or manifest["before_payload_sha256"]
                != _response_preference_payload_hash(before)
            ):
                return ResponsePreferenceRepairResult(False, "invalid_backup")
        except Exception:
            logger.exception("Response-preference repair backup validation failed")
            return ResponsePreferenceRepairResult(False, "invalid_backup")
        try:
            async with _response_preference_process_lock():
                current = await self._storage.get_kv_data(RESPONSE_PREFERENCE_KV_KEY, None)
                if _response_preference_payload_hash(current) != expected_after_payload_sha256:
                    return ResponsePreferenceRepairResult(False, "skipped_conflict")
                try:
                    committed = await compare_and_swap(
                        RESPONSE_PREFERENCE_KV_KEY, current, before
                    )
                except NotImplementedError:
                    return ResponsePreferenceRepairResult(
                        False, "conditional_write_unavailable", backup_dir=backup_dir
                    )
                except Exception:
                    return ResponsePreferenceRepairResult(
                        False, "commit_outcome_unknown", backup_dir=backup_dir
                    )
                if committed is not True:
                    return ResponsePreferenceRepairResult(False, "skipped_conflict")
                try:
                    restored = await self._storage.get_kv_data(RESPONSE_PREFERENCE_KV_KEY, None)
                    _decode_response_preference_payload(restored)
                except Exception:
                    return ResponsePreferenceRepairResult(
                        False, "committed_unverified", backup_dir=backup_dir
                    )
                if _response_preference_payload_hash(restored) != _response_preference_payload_hash(before):
                    return ResponsePreferenceRepairResult(
                        False, "committed_unverified", backup_dir=backup_dir
                    )
                return ResponsePreferenceRepairResult(True, "restored", backup_dir=backup_dir)
        except Exception:
            logger.exception("Response-preference repair restore failed")
            return ResponsePreferenceRepairResult(False, "restore_failed")

    async def request_response_preference(
        self,
        event: object,
        value: object,
        *,
        parameter: str = RESPONSE_EXPANSION_PARAMETER,
        now: float | None = None,
    ) -> PreferenceOperationResult:
        """Create one pending candidate from the current real private event.

        The caller cannot provide a scope or source id.  Both are derived from
        the event's platform/account/private-conversation accessors and the
        platform message id.
        """

        if not self._is_available:
            return PreferenceOperationResult(False, "unavailable")
        scope = scope_from_event(event)
        if scope is None:
            return PreferenceOperationResult(False, "invalid_scope")
        source = source_from_event(event, scope)
        if source is None:
            return PreferenceOperationResult(False, "missing_source")
        if type(parameter) is not str or parameter not in {
            RESPONSE_EXPANSION_PARAMETER,
            RESPONSE_LENGTH_PARAMETER,
            MEMORY_RETRIEVAL_PARAMETER,
            RELATIONSHIP_FAMILIARITY_PARAMETER,
        }:
            return PreferenceOperationResult(False, "invalid_parameter")
        try:
            normalized = normalize_response_preference_value(parameter, value)
        except ValueError:
            return PreferenceOperationResult(False, "invalid_value")
        requested_at = time.time() if now is None else float(now)
        candidate = ResponsePreferenceRecord(
            candidate_id=candidate_id_for(scope, source, normalized, parameter),
            scope=scope,
            parameter=parameter,
            value=normalized,
            source=source,
            status=PENDING,
            requested_at=requested_at,
        )
        try:
            async with _response_preference_process_lock():
                records = await self._load_response_preference_records()
                for existing in records:
                    if (
                        existing.scope == candidate.scope
                        and existing.parameter == candidate.parameter
                        and existing.source == candidate.source
                    ):
                        return PreferenceOperationResult(True, "duplicate", existing)
                for index, existing in enumerate(records):
                    if (
                        existing.scope == candidate.scope
                        and existing.parameter == candidate.parameter
                        and existing.status == APPROVED
                        and existing.value != candidate.value
                        and existing.is_active(requested_at)
                    ):
                        records[index] = replace(
                            existing,
                            status=SUSPENDED,
                            suspended_reason=(
                                f"conflicting pending {candidate.parameter}"
                            ),
                        )
                records.append(candidate)
                await self._save_response_preference_records(records)
                return PreferenceOperationResult(True, "pending", candidate)
        except Exception as exc:  # noqa: BLE001 - persistence failures fail closed
            logger.exception("创建回复表达偏好候选失败：%s", exc)
            return PreferenceOperationResult(False, "write_failed")

    async def request_memory_retrieval_preference(
        self, event: object, *, now: float | None = None
    ) -> PreferenceOperationResult:
        """Create the frozen, manually approved private retrieval candidate."""

        if event_contains_indirect_content(event):
            return PreferenceOperationResult(False, "indirect_source")
        return await self.request_response_preference(
            event,
            MEMORY_RETRIEVAL_ON,
            parameter=MEMORY_RETRIEVAL_PARAMETER,
            now=now,
        )

    async def request_explicit_response_preference(
        self, event: object, *, now: float | None = None
    ) -> PreferenceOperationResult:
        """Create a pending candidate only for the fixed direct phrase.

        This is intentionally a proposal path.  It never approves a value and
        never treats a quote, forward, or malformed message chain as the
        current user's instruction.
        """

        value = explicit_response_preference_value(getattr(event, "message_str", ""))
        if value is None:
            return PreferenceOperationResult(False, "not_explicit")
        if event_contains_indirect_content(event):
            return PreferenceOperationResult(False, "indirect_source")
        return await self.request_response_preference(event, value, now=now)

    async def request_explicit_relationship_familiarity(
        self, event: object, *, now: float | None = None
    ) -> PreferenceOperationResult:
        """Propose one scoped familiarity state from the exact direct phrase.

        This is the sole L22 relationship state.  It does not express trust,
        intimacy, permission, current affect, or an instruction to reply.  It
        remains pending until an administrator approves it and expires after
        the existing seven-day bound unless the user revokes it first.
        """

        value = explicit_relationship_familiarity_value(
            getattr(event, "message_str", "")
        )
        if value is None:
            return PreferenceOperationResult(False, "not_explicit")
        if event_contains_indirect_content(event):
            return PreferenceOperationResult(False, "indirect_source")
        return await self.request_response_preference(
            event,
            FAMILIAR,
            parameter=RELATIONSHIP_FAMILIARITY_PARAMETER,
            now=now,
        )

    async def request_response_length_preference_from_aggregate(
        self, aggregate: object, *, now: float | None = None
    ) -> PreferenceOperationResult:
        """Record one eligible L09 aggregate as a manually reviewed candidate.

        This is an explicit consolidator boundary.  It reuses the existing
        response-preference KV owner and lock, never auto-approves, and does
        not invoke the request Hook.
        """

        if not self._is_available:
            return PreferenceOperationResult(False, "unavailable")
        from iris_memory.cognitive.response_preference_feedback import (
            ResponseLengthFeedbackAggregateV1,
        )

        if type(aggregate) is not ResponseLengthFeedbackAggregateV1:
            return PreferenceOperationResult(False, "invalid_aggregate")
        source = source_from_response_length_feedback_aggregate(aggregate)
        if source is None:
            return PreferenceOperationResult(False, "aggregate_ineligible")
        requested_at = time.time() if now is None else float(now)
        candidate = ResponsePreferenceRecord(
            candidate_id=candidate_id_for(
                aggregate.scope,
                source,
                aggregate.value,
                aggregate.parameter,
            ),
            scope=aggregate.scope,
            parameter=aggregate.parameter,
            value=aggregate.value,
            source=source,
            status=PENDING,
            requested_at=requested_at,
        )
        try:
            async with _response_preference_process_lock():
                records = await self._load_response_preference_records()
                for existing in records:
                    if (
                        existing.scope == candidate.scope
                        and existing.parameter == candidate.parameter
                        and existing.source == candidate.source
                    ):
                        return PreferenceOperationResult(True, "duplicate", existing)
                    if (
                        existing.scope == candidate.scope
                        and existing.parameter == candidate.parameter
                        and existing.value == candidate.value
                        and existing.status == PENDING
                    ):
                        return PreferenceOperationResult(True, "duplicate", existing)
                    if (
                        existing.scope == candidate.scope
                        and existing.parameter == candidate.parameter
                        and existing.value == candidate.value
                        and existing.status == APPROVED
                        and existing.is_active(requested_at)
                    ):
                        return PreferenceOperationResult(False, "active_duplicate", existing)
                for index, existing in enumerate(records):
                    if (
                        existing.scope == candidate.scope
                        and existing.parameter == candidate.parameter
                        and existing.status == APPROVED
                        and existing.value != candidate.value
                        and existing.is_active(requested_at)
                    ):
                        records[index] = replace(
                            existing,
                            status=SUSPENDED,
                            suspended_reason=(
                                f"conflicting pending {candidate.parameter}"
                            ),
                        )
                records.append(candidate)
                await self._save_response_preference_records(records)
                return PreferenceOperationResult(True, "pending", candidate)
        except Exception as exc:  # noqa: BLE001 - persistence failures fail closed
            logger.exception("从 L09 回复长度聚合创建候选失败：%s", exc)
            return PreferenceOperationResult(False, "write_failed")

    async def list_response_preferences(
        self, *, status: str | None = None
    ) -> list[ResponsePreferenceRecord]:
        """List records for the authenticated management command."""

        if not self._is_available:
            raise ResponsePreferenceIntegrityError("response preference storage unavailable")
        async with _response_preference_process_lock():
            records = await self._load_response_preference_records()
        if status is None:
            return records
        if status not in {PENDING, APPROVED, REVOKED, SUSPENDED, SUPERSEDED}:
            raise ValueError("unknown response preference status")
        return [record for record in records if record.status == status]

    async def get_response_preference_for_event(
        self,
        event: object,
        *,
        parameter: str = RESPONSE_EXPANSION_PARAMETER,
        now: float | None = None,
    ) -> ResponsePreferenceRecord | None:
        """Read one active preference; any identity/storage failure is fail-closed."""

        if not self._is_available:
            return None
        scope = scope_from_event(event)
        if scope is None:
            return None
        current_time = time.time() if now is None else float(now)
        try:
            async with _response_preference_process_lock():
                records = await self._load_response_preference_records()
            active = [
                record
                for record in records
                if (
                    record.scope == scope
                    and record.parameter == parameter
                    and record.is_active(current_time)
                )
            ]
            # Approval keeps at most one live value per scope.  If damaged or
            # legacy data violates that invariant, choose no value rather than
            # guessing which preference should win.
            if len(active) != 1:
                return None
            return active[0]
        except Exception as exc:  # noqa: BLE001 - corrupted storage fails closed
            logger.warning("读取回复表达偏好失败，已恢复默认：%s", exc)
            return None

    async def active_response_preference_records_for_event(
        self, event: object, *, now: float | None = None
    ) -> list[ResponsePreferenceRecord] | None:
        """Read all active whitelisted parameters for the current scope."""

        if not self._is_available:
            return None
        scope = scope_from_event(event)
        if scope is None:
            return None
        current_time = time.time() if now is None else float(now)
        try:
            async with _response_preference_process_lock():
                records = await self._load_response_preference_records()
            active: list[ResponsePreferenceRecord] = []
            for parameter in (
                RESPONSE_EXPANSION_PARAMETER,
                RESPONSE_LENGTH_PARAMETER,
                MEMORY_RETRIEVAL_PARAMETER,
                RELATIONSHIP_FAMILIARITY_PARAMETER,
            ):
                matches = [
                    record
                    for record in records
                    if (
                        record.scope == scope
                        and record.parameter == parameter
                        and record.is_active(current_time)
                    )
                ]
                if len(matches) > 1:
                    return None
                active.extend(matches)
            return active
        except Exception as exc:  # noqa: BLE001 - corrupted storage fails closed
            logger.warning("读取回复表达偏好失败，已恢复默认：%s", exc)
            return None

    async def active_memory_retrieval_preference_for_event(
        self, event: object, *, now: float | None = None
    ) -> ResponsePreferenceRecord | None:
        """Read one active retrieval hint for the exact current private scope."""

        if not self._is_available:
            return None
        scope = scope_from_event(event)
        if scope is None:
            return None
        current_time = time.time() if now is None else float(now)
        try:
            async with _response_preference_process_lock():
                records = await self._load_response_preference_records()
            active = [
                record
                for record in records
                if (
                    record.scope == scope
                    and record.parameter == MEMORY_RETRIEVAL_PARAMETER
                    and record.is_active(current_time)
                )
            ]
            return active[0] if len(active) == 1 else None
        except Exception as exc:  # noqa: BLE001 - corrupted storage fails closed
            logger.warning("读取工具偏好失败，已恢复默认：%s", exc)
            return None

    async def approve_response_preference(
        self, candidate_id: object, approved_by: object, *, now: float | None = None
    ) -> PreferenceOperationResult:
        """Approve exactly one pending candidate from the admin command."""

        if not self._is_available:
            return PreferenceOperationResult(False, "unavailable")
        if type(candidate_id) is not str or not candidate_id.startswith("rspref:"):
            return PreferenceOperationResult(False, "invalid_candidate")
        if type(approved_by) is not str or not approved_by.strip():
            return PreferenceOperationResult(False, "missing_approver")
        approved_at = time.time() if now is None else float(now)
        try:
            async with _response_preference_process_lock():
                records = await self._load_response_preference_records()
                index = next(
                    (i for i, record in enumerate(records) if record.candidate_id == candidate_id),
                    None,
                )
                if index is None:
                    return PreferenceOperationResult(False, "not_found")
                candidate = records[index]
                if candidate.status != PENDING:
                    return PreferenceOperationResult(False, "already_processed", candidate)

                current = [
                    record
                    for record in records
                    if record.scope == candidate.scope
                    and record.parameter == candidate.parameter
                    and record.status == APPROVED
                    and record.is_active(approved_at)
                ]
                same_value = [record for record in current if record.value == candidate.value]
                if same_value:
                    # Do not extend an already active preference.  Mark the
                    # new source as processed so replay cannot add duration.
                    records[index] = replace(candidate, status=SUPERSEDED)
                    await self._save_response_preference_records(records)
                    return PreferenceOperationResult(False, "active_duplicate", records[index])

                for existing in current:
                    old_index = records.index(existing)
                    records[old_index] = replace(
                        existing,
                        status=SUSPENDED,
                        suspended_reason=(
                            f"conflicting approved {candidate.parameter}"
                        ),
                    )
                approved = replace(
                    candidate,
                    status=APPROVED,
                    approved_by=approved_by.strip(),
                    approved_at=approved_at,
                    expires_at=approved_at + APPROVAL_TTL_SECONDS,
                )
                records[index] = approved
                await self._save_response_preference_records(records)
                return PreferenceOperationResult(True, "approved", approved)
        except Exception as exc:  # noqa: BLE001 - persistence failures fail closed
            logger.exception("批准回复表达偏好失败：%s", exc)
            return PreferenceOperationResult(False, "write_failed")

    async def revoke_response_preference(
        self, candidate_id: object, revoked_by: object, *, now: float | None = None
    ) -> PreferenceOperationResult:
        """Revoke a selected record from the authenticated admin command."""

        if not self._is_available:
            return PreferenceOperationResult(False, "unavailable")
        if type(candidate_id) is not str or not candidate_id.startswith("rspref:"):
            return PreferenceOperationResult(False, "invalid_candidate")
        if type(revoked_by) is not str or not revoked_by.strip():
            return PreferenceOperationResult(False, "missing_revoker")
        revoked_at = time.time() if now is None else float(now)
        try:
            async with _response_preference_process_lock():
                records = await self._load_response_preference_records()
                index = next(
                    (i for i, record in enumerate(records) if record.candidate_id == candidate_id),
                    None,
                )
                if index is None:
                    return PreferenceOperationResult(False, "not_found")
                record = records[index]
                if record.status == REVOKED:
                    return PreferenceOperationResult(False, "already_revoked", record)
                revoked = replace(
                    record,
                    status=REVOKED,
                    revoked_by=revoked_by.strip(),
                    revoked_at=revoked_at,
                )
                records[index] = revoked
                await self._save_response_preference_records(records)
                return PreferenceOperationResult(True, "revoked", revoked)
        except Exception as exc:  # noqa: BLE001 - persistence failures fail closed
            logger.exception("撤销回复表达偏好失败：%s", exc)
            return PreferenceOperationResult(False, "write_failed")

    async def revoke_response_preferences_for_event(
        self, event: object, *, now: float | None = None
    ) -> PreferenceOperationResult:
        """Let a user revoke only records matching their current private scope."""

        if not self._is_available:
            return PreferenceOperationResult(False, "unavailable")
        scope = scope_from_event(event)
        if scope is None:
            return PreferenceOperationResult(False, "invalid_scope")
        revoked_at = time.time() if now is None else float(now)
        revoker = f"user:{scope.user_id}"
        try:
            async with _response_preference_process_lock():
                records = await self._load_response_preference_records()
                indexes = [
                    i
                    for i, record in enumerate(records)
                    if record.scope == scope and record.status in {PENDING, APPROVED}
                ]
                if not indexes:
                    return PreferenceOperationResult(True, "nothing_to_revoke")
                for index in indexes:
                    records[index] = replace(
                        records[index],
                        status=REVOKED,
                        revoked_by=revoker,
                        revoked_at=revoked_at,
                    )
                await self._save_response_preference_records(records)
                return PreferenceOperationResult(True, "revoked", affected=len(indexes))
        except Exception as exc:  # noqa: BLE001 - persistence failures fail closed
            logger.exception("用户撤销回复表达偏好失败：%s", exc)
            return PreferenceOperationResult(False, "write_failed")

    async def response_preference_records_for_event(
        self, event: object
    ) -> list[ResponsePreferenceRecord] | None:
        """Return only this user's private-scope records for self status."""

        if not self._is_available:
            return None
        scope = scope_from_event(event)
        if scope is None:
            return None
        try:
            async with _response_preference_process_lock():
                records = await self._load_response_preference_records()
            return [record for record in records if record.scope == scope]
        except Exception as exc:  # noqa: BLE001 - corrupted storage fails closed
            logger.warning("读取用户回复表达偏好状态失败：%s", exc)
            return None
