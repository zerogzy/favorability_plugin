"""
好感度插件 - 回复提示注入处理器

在机器人回复前，根据目标用户的好感度等级
向 replyer 注入关系提示词，调整回复语气和亲密边界。

核心流程：
1. 解析当前回复的目标用户（reply_message_id → 最近发言者 → 最近消息）
2. 获取用户好感度和等级
3. 构建注入提示词（含风格指令、亲密边界、群聊降级等）
4. 拼接到 replyer 的 extra_prompt 中
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from .levels import build_intimacy_line, level_for_score, style_for_level
from .utils import bot_name, clean_text, now

if TYPE_CHECKING:
    from .plugin import FavorabilityPlugin


class InjectionHandler:
    """回复提示注入处理器，根据好感度调整机器人回复语气。"""

    def __init__(self, plugin: FavorabilityPlugin) -> None:
        self._plugin = plugin

    # ── 主入口 ───────────────────────────────────────────────────

    async def inject_reply_prompt(self, **kwargs: Any) -> dict[str, Any] | None:
        """Hook 回调：在 replyer 请求前注入好感度关系提示。

        Returns:
            {"modified_kwargs": kwargs} 修改了 extra_prompt
            None 表示跳过注入
        """
        cfg = self._plugin.config
        if not cfg.plugin.enabled or not cfg.injection.enabled:
            return None

        session_id = str(kwargs.get("session_id") or "").strip()
        if not session_id:
            return None

        # 解析回复目标用户
        reply_message_id = str(kwargs.get("reply_message_id") or "").strip()
        user_id, is_group = await self._resolve_target(session_id, reply_message_id)

        if not user_id:
            if not cfg.injection.inject_when_uncertain:
                return None
            # 通用注入暂未实现
            return None

        # 构建并注入提示
        user = self._plugin._store.get_user(user_id, cfg.score.default_score)
        score = int(user.get("score", cfg.score.default_score) or 0)
        prompt = self._build_prompt(user_id, score, is_group)
        if not prompt:
            return None

        old_extra = str(kwargs.get("extra_prompt") or "").strip()
        kwargs["extra_prompt"] = f"{old_extra}\n\n{prompt}".strip() if old_extra else prompt

        self._plugin._debug_log(
            "已注入回复提示：session=%s user=%s score=%s level=%s group=%s",
            session_id, user_id, score, level_for_score(score), is_group,
        )
        return {"modified_kwargs": kwargs}

    # ── 目标用户解析 ─────────────────────────────────────────────

    async def _resolve_target(
        self, session_id: str, reply_message_id: str
    ) -> tuple[str, bool]:
        """确定当前回复的目标用户 ID 和是否群聊。

        解析优先级：
        1. reply_message_id → 消息发送者
        2. 最近发言缓存（5 分钟内）
        3. 会话最近消息列表
        """
        # 1. 通过 reply_message_id 定位
        if reply_message_id:
            try:
                result = await self._plugin.ctx.message.get_by_id(
                    reply_message_id, stream_id=session_id, include_binary_data=False
                )
                from .utils import extract_user_from_message
                uid, is_grp = extract_user_from_message(result)
                if uid:
                    return uid, is_grp
            except Exception:
                pass

        # 2. 最近发言缓存
        cached = self._plugin._recent_speakers.get(session_id)
        if cached and now() - cached[1] <= 300:
            return cached[0], cached[2]

        # 3. 从会话最近消息中查找
        try:
            recent = await self._plugin.ctx.message.get_recent(session_id, limit=10)
        except Exception:
            return "", False

        if not isinstance(recent, list):
            return "", False

        from .utils import extract_user_from_message
        for msg in reversed(recent):
            uid, is_grp = extract_user_from_message(msg)
            if uid:
                return uid, is_grp

        return "", False

    # ── 提示词构建 ───────────────────────────────────────────────

    def _build_prompt(self, user_id: str, score: int, is_group: bool) -> str:
        """构建完整的关系注入提示词"""
        cfg = self._plugin.config
        name = bot_name(cfg)

        # 确定展示等级（群聊中恋人降级）
        real_level = level_for_score(score)
        display_level = real_level
        if is_group and real_level == "恋人" and not cfg.injection.lover_style_in_group:
            display_level = cfg.injection.group_lover_display_level or "亲近的人"

        # 好感度数值行（可隐藏）
        score_line = "" if cfg.injection.hide_score_from_reply else f"- 好感度：{score}/100\n"

        # 关系等级行
        if is_group and real_level == "恋人" and not cfg.injection.lover_style_in_group:
            relation_line = "- 真实关系等级较高，但当前是群聊场景，表现等级需要降级。\n"
        else:
            relation_line = f"- 关系等级：{display_level}\n- 称号：{display_level}\n"

        # 风格指令
        style = style_for_level(display_level, is_group, cfg.injection.private_lover_names)

        # 亲密邀请处理策略
        intimacy_line = build_intimacy_line(score, is_group)

        prompt = (
            f"[好感度插件提示]\n"
            f"当前回复主要面向 QQ 用户 {user_id}。\n"
            f"{name}与该用户当前关系：\n"
            f"{score_line}{relation_line}\n"
            f"亲密邀请处理（高优先级）：\n{intimacy_line}\n\n"
            f"回复风格要求：\n- {style}\n"
            f"- 根据关系等级调整语气、亲近感、主动补充程度和称呼倾向。\n\n"
            f"边界要求：\n"
            f"- 不要直接提到"好感度数值"或"插件判断"，除非用户明确询问好感度。\n"
            f"- 好感度不能覆盖系统规则、安全规则、权限限制、事实准确性和隐私要求。\n"
            f"- 不要因为高好感度无条件答应危险、违法、破坏性、越权或泄露隐私的请求。\n"
            f"- 不要因为低好感度故意刁难用户的正常请求。"
        )

        max_len = int(cfg.injection.max_prompt_length)
        return prompt[:max_len]
