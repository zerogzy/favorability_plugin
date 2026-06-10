"""
好感度插件 - 主插件类（编排器）

FavorabilityPlugin 是 MaiBot 插件的入口类，负责：
1. 初始化各功能处理器（评分、涩图、注入、命令）
2. 注册 Hook 和 Command 回调
3. 将回调事件分发给对应处理器
4. 管理插件生命周期（加载/卸载/配置更新）

本文件保持精简，所有业务逻辑委托给各专用处理器模块。
"""

from __future__ import annotations

import asyncio
from typing import Any

from maibot_sdk import Command, Field, HookHandler, MaiBotPlugin
from maibot_sdk.types import ErrorPolicy, HookMode

from .commands import CommandHandler
from .config import FavorabilityConfig
from .constants import DATA_PATH
from .evaluation import EvaluationHandler
from .injection import InjectionHandler
from .spicy import SpicyImageHandler
from .store import FavorabilityStore
from .utils import clean_text, now, parse_message_user


class FavorabilityPlugin(MaiBotPlugin):
    """好感度插件主类，编排各功能模块。"""

    config_model = FavorabilityConfig

    def __init__(self) -> None:
        super().__init__()
        # 数据存储
        self._store = FavorabilityStore(DATA_PATH)
        # 功能处理器
        self._spicy = SpicyImageHandler(self)
        self._evaluation = EvaluationHandler(self)
        self._injection = InjectionHandler(self)
        self._commands = CommandHandler(self)
        # 共享状态
        self._admin_ids: set[str] = set()
        self._recent_speakers: dict[str, tuple[str, float, bool]] = {}

    # ── 生命周期 ─────────────────────────────────────────────────

    async def on_load(self) -> None:
        """插件加载时初始化"""
        self._refresh_admin_ids()
        self._spicy.refresh_immich_client()
        self.ctx.logger.info("好感度插件已加载。")

    async def on_unload(self) -> None:
        """插件卸载时清理资源"""
        await self._evaluation.cancel_all()
        await self._spicy.cancel_all()
        self._store.save()

    async def on_config_update(
        self, scope: str, config_data: dict, version: str
    ) -> None:
        """配置更新时刷新运行时状态"""
        del config_data, version
        if scope == "self":
            self._refresh_admin_ids()
            self._spicy.refresh_immich_client()

    # ── 内部状态刷新 ─────────────────────────────────────────────

    def _refresh_admin_ids(self) -> None:
        """从配置中刷新管理员 ID 集合"""
        self._admin_ids = {
            str(item).strip()
            for item in self.config.admin.admin_user_ids
            if str(item).strip()
        }

    def _is_admin(self, user_id: str) -> bool:
        """判断用户是否为管理员"""
        return str(user_id or "").strip() in self._admin_ids

    # ── 调试日志 ─────────────────────────────────────────────────

    def _debug_log(self, message: str, *args: Any, exc_info: bool = False) -> None:
        """按配置输出调试日志"""
        debug_cfg = self.config.debug
        if not debug_cfg.enabled:
            return
        if str(debug_cfg.log_level).strip().lower() == "info":
            self.ctx.logger.info("[好感度调试] " + message, *args, exc_info=exc_info)
        else:
            self.ctx.logger.debug("[好感度调试] " + message, *args, exc_info=exc_info)

    def _message_preview(self, text: str) -> str:
        """生成消息预览文本（调试用，可配置隐藏）"""
        if not self.config.debug.include_message_preview:
            return "<已隐藏>"
        return clean_text(text, 120)

    # ── Hook: 消息观察 ───────────────────────────────────────────

    @HookHandler(
        "chat.receive.before_process",
        name="favorability_message_observer",
        description="处理好感度消息并拦截已消费的涩图请求",
        mode=HookMode.BLOCKING,
        order="late",
        timeout_ms=8000,
        error_policy=ErrorPolicy.SKIP,
    )
    async def observe_message(
        self, message: dict | None = None, **kwargs: Any
    ) -> dict[str, Any] | None:
        """消息接收钩子：处理衰减、涩图请求、评分累积"""
        del kwargs
        cfg = self.config
        if not cfg.plugin.enabled:
            return None

        # 解析消息基本信息
        parsed = parse_message_user(message)
        if parsed is None:
            return None
        user_id, session_id, text, is_group = parsed

        # 记录最近发言者（供注入模块使用）
        self._recent_speakers[session_id] = (user_id, now(), is_group)
        # 缓存 NapCat 发送目标
        self._spicy.cache_napcat_target(message, session_id, user_id, is_group)

        if not text:
            return None

        # 结算久未互动衰减
        user, decay_delta = self._store.apply_inactivity_decay(
            user_id, cfg, session_id=session_id
        )
        if decay_delta:
            self._debug_log(
                "长期未互动衰减：user=%s delta=%s score=%s",
                user_id, decay_delta, user.get("score"),
            )

        # 涩图偏好消费（用户正在回复偏好追问）
        if self._spicy.consume_spicy_preference(user_id, session_id, text):
            return {"action": "abort"}

        # 涩图请求识别与处理
        if await self._spicy.maybe_handle_request(user_id, session_id, text, user):
            return {"action": "abort"}

        # AI 评分：累积消息并在满足条件时触发
        if not cfg.evaluation.enabled:
            return None

        user["message_count"] = int(user.get("message_count", 0) or 0) + 1
        self._store.save_user(user_id, user)
        self._evaluation.add_message(user_id, text)
        self._evaluation.try_evaluate(user_id, session_id)

        return None

    # ── Hook: 回复提示注入 ───────────────────────────────────────

    @HookHandler(
        "maisaka.replyer.before_request",
        name="favorability_reply_prompt_injector",
        description="根据当前目标用户好感度追加 replyer 关系提示词",
        mode=HookMode.BLOCKING,
        order="normal",
        timeout_ms=2500,
        error_policy=ErrorPolicy.SKIP,
    )
    async def inject_reply_prompt(self, **kwargs: Any) -> dict[str, Any] | None:
        """回复前注入好感度关系提示"""
        return await self._injection.inject_reply_prompt(**kwargs)

    # ── Command: 好感度命令 ─────────────────────────────────────

    @Command(
        "favorability",
        description="查询或管理机器人好感度",
        pattern=r"(?P<favorability_command>^/好感度(?:详情|调整|设置|重置)?(?:\s+\S+){0,2}\s*$)",
    )
    async def handle_favorability_command(
        self,
        stream_id: str = "",
        user_id: str = "",
        matched_groups: dict | None = None,
        **kwargs: Any,
    ) -> tuple[bool, str, bool]:
        """处理 /好感度 系列命令"""
        return await self._commands.handle_command(
            stream_id=stream_id,
            user_id=user_id,
            matched_groups=matched_groups,
            **kwargs,
        )


# ── 插件工厂函数 ────────────────────────────────────────────────

def create_plugin() -> FavorabilityPlugin:
    """MaiBot SDK 入口：创建好感度插件实例"""
    return FavorabilityPlugin()

"""我不知道为啥会报错"""
