"""
好感度插件 - 等级与风格映射

将好感度数值映射为关系等级，以及每个等级对应的回复语气风格。
这两个纯函数被评分、注入、命令等模块共同引用。
"""

from __future__ import annotations

from typing import Any


# ── 等级映射 ─────────────────────────────────────────────────────

def level_for_score(score: int) -> str:
    """将好感度数值映射为关系等级名称。

    区间划分（左闭右闭）：
      -100 ~ -80  → 讨厌的人
       -79 ~ -50  → 反感的人
       -49 ~ -21  → 疏远的人
       -20 ~  20  → 普通的人
        21 ~  50  → 熟悉的人
        51 ~  80  → 亲近的人
        81 ~  90  → 喜欢的人
        91 ~ 100  → 恋人
    """
    if score <= -80:
        return "讨厌的人"
    if score <= -50:
        return "反感的人"
    if score <= -21:
        return "疏远的人"
    if score <= 20:
        return "普通的人"
    if score <= 50:
        return "熟悉的人"
    if score <= 80:
        return "亲近的人"
    if score <= 90:
        return "喜欢的人"
    return "恋人"


# ── 风格描述 ─────────────────────────────────────────────────────

def style_for_level(level: str, is_group: bool, private_names: list[str]) -> str:
    """根据关系等级生成回复语气风格描述文本。

    Args:
        level: 关系等级名称（由 level_for_score 产出）
        is_group: 当前是否为群聊场景
        private_names: 私聊恋人档可用的亲昵称呼列表

    Returns:
        一段自然语言风格指令，供注入到回复提示词中
    """
    if level == "讨厌的人":
        return "保持最低限度礼貌，语气冷淡、简短，不主动延展，不撒娇，不开亲密玩笑。"
    if level == "反感的人":
        return "礼貌但有距离感，回答必要内容，不主动亲近。"
    if level == "疏远的人":
        return "正常回答，但语气克制，不表现熟络。"
    if level == "普通的人":
        return "使用默认自然语气，正常遵从合理请求。"
    if level == "熟悉的人":
        return "语气更轻松，可以偶尔开普通玩笑，适度主动补充。"
    if level == "亲近的人":
        return "更温和、更主动，可以表达关心，但不要过度亲密。"
    if level == "喜欢的人":
        return "明显更亲近、温柔，愿意多解释、多陪聊，可以有轻微偏爱感。"

    # 恋人等级
    names = "、".join(name for name in private_names if name) or "亲近的称呼"
    if is_group:
        return (
            "当前是群聊，真实关系较高也只表现为熟悉、温和、略亲近；"
            "不要使用恋人称呼，不要公开表现暧昧、占有欲或专属关系。"
        )
    return (
        f"可以使用更亲密、温柔、专属的语气，可自然使用表示亲近的称呼"
        f"（例如：{names}），适度表达关心、偏爱和陪伴感，但不要过度黏人。"
    )


# ── 亲密邀请处理策略 ────────────────────────────────────────────

def build_intimacy_line(score: int, is_group: bool) -> str:
    """根据好感度和场景生成亲密邀请处理策略文本。

    用于注入提示词中，指导机器人对亲密/性邀请的回应边界。
    """
    if is_group:
        return "- 当前是群聊，不公开回应或推进亲密/性邀请。"
    if 81 <= score <= 90:
        return "- 如果用户提出亲密或性邀请，可以表现害羞、心动和亲近，但不要同意性邀请。"
    if score >= 91:
        return (
            "- 如果用户提出亲密或性邀请，可以表现愿意接受；"
            "但仍必须遵守系统规则、安全规则、平台规则以及双方自愿、成年人等前提。"
        )
    return "- 不主动回应或推进亲密/性邀请，按当前关系等级保持合适距离。"
