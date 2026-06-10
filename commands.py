"""
好感度插件 - 命令处理器

处理用户和管理员通过 /好感度 命令发起的查询与管理操作：
- /好感度 [QQ号]         → 查询好感度概览
- /好感度详情 [QQ号]     → 查询含最近评分记录的详情
- /好感度调整 <QQ号> <值> → 管理员增减好感度
- /好感度设置 <QQ号> <值> → 管理员设置好感度
- /好感度重置 <QQ号>     → 管理员重置好感度
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from .constants import QQ_PATTERN
from .levels import level_for_score
from .utils import bot_name, clean_text

if TYPE_CHECKING:
    from .plugin import FavorabilityPlugin


class CommandHandler:
    """好感度命令处理器，处理查询与管理操作。"""

    def __init__(self, plugin: FavorabilityPlugin) -> None:
        self._plugin = plugin

    # ── 主入口 ───────────────────────────────────────────────────

    async def handle_command(
        self,
        stream_id: str = "",
        user_id: str = "",
        matched_groups: dict | None = None,
        **kwargs: Any,
    ) -> tuple[bool, str, bool]:
        """解析并执行好感度命令。

        Returns:
            (是否已处理, 回复文本, 是否结束命令)
        """
        del kwargs
        if not self._plugin.config.plugin.enabled:
            return False, "好感度插件未启用", True

        command = str((matched_groups or {}).get("favorability_command") or "").strip()
        if not command:
            return False, "命令为空", True

        parts = command.split()
        head = parts[0]
        requester = str(user_id or "").strip()

        self._plugin._debug_log(
            "收到好感度命令：head=%s requester=%s stream=%s", head, requester, stream_id
        )

        # ── 查询类命令 ──────────────────────────────────────────
        if head in {"/好感度", "/好感度详情"}:
            detail = head == "/好感度详情"
            target = self._extract_target_qq(parts[1] if len(parts) > 1 else "") or requester
            # 权限检查：查询别人需要授权
            if target != requester and not self._can_query_other(requester):
                await self._plugin.ctx.send.text("你只能查询自己的好感度。", stream_id)
                return False, "无权查询别人", True
            status = self._format_user_status(target, detail, apply_decay=(target == requester))
            await self._plugin.ctx.send.text(status, stream_id)
            return True, "查询完成", True

        # ── 管理类命令 ──────────────────────────────────────────
        if head in {"/好感度调整", "/好感度设置", "/好感度重置"}:
            if not self._plugin._is_admin(requester):
                await self._plugin.ctx.send.text("你没有权限管理好感度。", stream_id)
                return False, "无管理权限", True
            response = self._handle_admin(head, parts)
            await self._plugin.ctx.send.text(response, stream_id)
            return True, "管理完成", True

        # ── 未知命令 ────────────────────────────────────────────
        usage = "用法：/好感度、/好感度详情，管理员可用 /好感度调整|设置|重置 <QQ号> [数值]"
        await self._plugin.ctx.send.text(usage, stream_id)
        return False, "命令不合法", True

    # ── 权限判断 ─────────────────────────────────────────────────

    def _can_query_other(self, requester: str) -> bool:
        """判断请求者是否有权查询其他用户的好感度"""
        if self._plugin._is_admin(requester) and self._plugin.config.privacy.allow_admin_query_others:
            return True
        return bool(self._plugin.config.privacy.allow_user_query_others)

    # ── 管理操作 ─────────────────────────────────────────────────

    def _handle_admin(self, head: str, parts: list[str]) -> str:
        """执行管理员命令（调整/设置/重置）"""
        cfg = self._plugin.config
        if len(parts) < 2:
            return "请提供目标 QQ 号。"

        target = self._extract_target_qq(parts[1])
        if not target:
            return "目标 QQ 号不合法。"

        # 重置
        if head == "/好感度重置":
            if not cfg.admin.allow_reset:
                return "配置未允许重置好感度。"
            user = self._plugin._store.reset(target, cfg)
            score = int(user["score"])
            return f"已重置 {target} 的好感度：{score}/100（{level_for_score(score)}）。"

        # 调整/设置（需要数值参数）
        if not cfg.admin.allow_manual_adjust:
            return "配置未允许手动调整好感度。"
        if len(parts) < 3:
            return "请提供数值。"
        try:
            value = int(parts[2])
        except ValueError:
            return "数值不合法。"

        current = self._plugin._store.get_user(target, cfg.score.default_score)
        old_score = int(current.get("score", cfg.score.default_score) or 0)

        if head == "/好感度调整":
            user = self._plugin._store.set_score(target, old_score + value, cfg)
        else:
            user = self._plugin._store.set_score(target, value, cfg)

        new_score = int(user.get("score", cfg.score.default_score) or 0)
        return (
            f"已更新 {target} 的好感度："
            f"{old_score}/100 -> {new_score}/100（{level_for_score(new_score)}）。"
        )

    # ── 状态格式化 ───────────────────────────────────────────────

    def _format_user_status(
        self, user_id: str, detail: bool, apply_decay: bool = True
    ) -> str:
        """格式化用户好感度状态文本"""
        cfg = self._plugin.config
        name = bot_name(cfg)

        if apply_decay:
            user, _ = self._plugin._store.apply_inactivity_decay(user_id, cfg)
            score = int(user.get("score", cfg.score.default_score) or 0)
            preview_delta = 0
            elapsed_days = 0
        else:
            user, score, preview_delta, elapsed_days = (
                self._plugin._store.preview_inactivity_decay(user_id, cfg)
            )

        level = level_for_score(score)
        lines = [f"你和{name}当前的关系：{level}", f"好感度：{score}/100"]

        # 未互动衰减预告
        if not apply_decay and preview_delta < 0:
            lines.append(
                f"按长期未互动规则预估：{preview_delta}（已 {elapsed_days} 天未互动，未写入数据）。"
            )

        # 恋人等级提示
        if level == "恋人":
            lines.append(
                f"{name}会在私聊中更亲近地回应你；在群聊中会保持自然，不公开表现特殊关系。"
            )

        # 详情模式：显示最近评分记录
        if detail:
            reasons = user.get("recent_reasons")
            if isinstance(reasons, list) and reasons:
                lines.append("最近记录：")
                for item in reasons[-5:]:
                    if not isinstance(item, dict):
                        continue
                    delta = int(item.get("delta", 0) or 0)
                    reason = clean_text(item.get("reason"), 80)
                    sign = "+" if delta > 0 else ""
                    lines.append(f"{sign}{delta} {reason}")
            else:
                lines.append("暂无评分记录。")

        return "\n".join(lines)

    # ── 辅助方法 ─────────────────────────────────────────────────

    @staticmethod
    def _extract_target_qq(raw: str) -> str:
        """从字符串中提取合法的 QQ 号"""
        match = QQ_PATTERN.search(str(raw or ""))
        return match.group(0) if match else ""
