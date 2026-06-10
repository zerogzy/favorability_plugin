"""
好感度插件 - SQLite 数据存储

管理用户好感度数据的持久化，包括：
- 建表与 JSON 遗留数据迁移
- 用户数据的 CRUD 操作
- 好感度变化（delta）的写入与晋级校验
- 久未互动衰减的计算与应用
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .config import FavorabilityConfig
from .constants import DATA_PATH, LEGACY_DATA_PATH
from .utils import clamp, clean_text, now, normalize_risk


class FavorabilityStore:
    """好感度 SQLite 数据存储。

    每次操作都打开独立连接（SQLite WAL 模式下可安全并发读），
    避免长期持有连接导致锁问题。
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.load()

    # ── 初始化与迁移 ─────────────────────────────────────────────

    def load(self) -> None:
        """初始化数据库 schema 并尝试从旧版 JSON 迁移数据"""
        with closing(self._connect()) as conn:
            self._init_schema(conn)
            self._migrate_legacy_json(conn)

    def save(self) -> None:
        """兼容旧版接口，SQLite 模式下无需手动保存"""
        return None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _init_schema(conn: sqlite3.Connection) -> None:
        """创建 users 表（如不存在）"""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                score INTEGER NOT NULL,
                message_count INTEGER NOT NULL,
                positive_eval_count INTEGER NOT NULL,
                negative_eval_count INTEGER NOT NULL,
                last_eval_at REAL NOT NULL,
                last_interaction_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                recent_reasons TEXT NOT NULL
            )
            """
        )
        conn.commit()

    def _migrate_legacy_json(self, conn: sqlite3.Connection) -> None:
        """从旧版 JSON 文件迁移数据到 SQLite（仅在表为空时执行）"""
        if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None:
            return
        if not LEGACY_DATA_PATH.exists():
            return
        try:
            raw = json.loads(LEGACY_DATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        users = raw.get("users") if isinstance(raw, dict) else None
        if not isinstance(users, dict):
            return
        for user_id, user in users.items():
            if not isinstance(user, dict):
                continue
            default = int(user.get("score", 0) or 0)
            self._upsert_user(conn, str(user_id), self._normalize_user(user, default))
        conn.commit()

    # ── 用户数据格式化 ───────────────────────────────────────────

    @staticmethod
    def _default_user(default_score: int) -> dict[str, Any]:
        """生成新用户的默认数据结构"""
        ts = now()
        return {
            "score": default_score, "message_count": 0,
            "positive_eval_count": 0, "negative_eval_count": 0,
            "last_eval_at": 0.0, "last_interaction_at": ts,
            "updated_at": ts, "recent_reasons": [],
        }

    @staticmethod
    def _normalize_user(user: dict[str, Any], default_score: int) -> dict[str, Any]:
        """将用户字典规范化，补全缺失字段并校验类型"""
        ts = now()
        reasons = user.get("recent_reasons")
        if not isinstance(reasons, list):
            reasons = []
        return {
            "score": int(user.get("score", default_score) or 0),
            "message_count": int(user.get("message_count", 0) or 0),
            "positive_eval_count": int(user.get("positive_eval_count", 0) or 0),
            "negative_eval_count": int(user.get("negative_eval_count", 0) or 0),
            "last_eval_at": float(user.get("last_eval_at", 0.0) or 0.0),
            "last_interaction_at": float(
                user.get("last_interaction_at", user.get("updated_at", ts)) or ts
            ),
            "updated_at": float(user.get("updated_at", ts) or ts),
            "recent_reasons": reasons,
        }

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> dict[str, Any]:
        """将数据库行转为用户字典，解析 recent_reasons JSON"""
        try:
            reasons = json.loads(str(row["recent_reasons"] or "[]"))
        except json.JSONDecodeError:
            reasons = []
        if not isinstance(reasons, list):
            reasons = []
        return {
            "score": int(row["score"]),
            "message_count": int(row["message_count"]),
            "positive_eval_count": int(row["positive_eval_count"]),
            "negative_eval_count": int(row["negative_eval_count"]),
            "last_eval_at": float(row["last_eval_at"]),
            "last_interaction_at": float(row["last_interaction_at"]),
            "updated_at": float(row["updated_at"]),
            "recent_reasons": reasons,
        }

    # ── 写入操作 ─────────────────────────────────────────────────

    @staticmethod
    def _upsert_user(conn: sqlite3.Connection, user_id: str, user: dict[str, Any]) -> None:
        """插入或更新用户记录（ON CONFLICT DO UPDATE）"""
        conn.execute(
            """
            INSERT INTO users (
                user_id, score, message_count, positive_eval_count, negative_eval_count,
                last_eval_at, last_interaction_at, updated_at, recent_reasons
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                score = excluded.score,
                message_count = excluded.message_count,
                positive_eval_count = excluded.positive_eval_count,
                negative_eval_count = excluded.negative_eval_count,
                last_eval_at = excluded.last_eval_at,
                last_interaction_at = excluded.last_interaction_at,
                updated_at = excluded.updated_at,
                recent_reasons = excluded.recent_reasons
            """,
            (
                user_id,
                int(user.get("score", 0) or 0),
                int(user.get("message_count", 0) or 0),
                int(user.get("positive_eval_count", 0) or 0),
                int(user.get("negative_eval_count", 0) or 0),
                float(user.get("last_eval_at", 0.0) or 0.0),
                float(user.get("last_interaction_at", now()) or now()),
                float(user.get("updated_at", now()) or now()),
                json.dumps(
                    user.get("recent_reasons") if isinstance(user.get("recent_reasons"), list) else [],
                    ensure_ascii=False,
                ),
            ),
        )

    def save_user(self, user_id: str, user: dict[str, Any]) -> None:
        """保存（更新）单个用户数据"""
        with closing(self._connect()) as conn:
            default = int(user.get("score", 0) or 0)
            self._upsert_user(conn, user_id, self._normalize_user(user, default))
            conn.commit()

    # ── 读取操作 ─────────────────────────────────────────────────

    def get_user(self, user_id: str, default_score: int) -> dict[str, Any]:
        """获取用户数据，不存在则创建默认记录"""
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row is not None:
                return self._row_to_user(row)
            user = self._default_user(default_score)
            self._upsert_user(conn, user_id, user)
            conn.commit()
            return user

    # ── 好感度变更 ───────────────────────────────────────────────

    def set_score(self, user_id: str, score: int, cfg: FavorabilityConfig) -> dict[str, Any]:
        """直接设置用户好感度为指定值（管理员操作）"""
        user = self.get_user(user_id, cfg.score.default_score)
        user["score"] = clamp(int(score), cfg.score.min_score, cfg.score.max_score)
        user["updated_at"] = now()
        self.save_user(user_id, user)
        return user

    def reset(self, user_id: str, cfg: FavorabilityConfig) -> dict[str, Any]:
        """重置用户好感度为默认值（删除后重建）"""
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            conn.commit()
        return self.get_user(user_id, cfg.score.default_score)

    def apply_delta(
        self,
        user_id: str,
        delta: int,
        confidence: float,
        reason: str,
        risk: str,
        session_id: str,
        cfg: FavorabilityConfig,
    ) -> tuple[dict[str, Any], int]:
        """应用好感度变化值，包含倍率、晋级门槛和风险保护逻辑。

        Returns:
            (更新后的用户字典, 实际变化值)
        """
        user = self.get_user(user_id, cfg.score.default_score)
        risk = normalize_risk(risk, reason)
        old_score = int(user.get("score", cfg.score.default_score) or 0)

        # 1. 钳制原始 delta 并应用倍率
        max_delta = max(1, int(cfg.score.max_delta_per_eval))
        adj_delta = clamp(int(delta), -max_delta, max_delta)
        if adj_delta > 0:
            adj_delta = max(1, round(adj_delta * float(cfg.score.positive_delta_multiplier)))
        elif adj_delta < 0:
            adj_delta = min(-1, round(adj_delta * float(cfg.score.negative_delta_multiplier)))
        adj_delta = clamp(adj_delta, -max_delta, max_delta)

        # 2. 高好感度时辱骂/骚扰不再扣分
        if old_score >= int(cfg.score.ignore_abuse_negative_min_score) and adj_delta < 0:
            if risk in {"insult", "sexual_harassment"}:
                adj_delta = 0

        # 3. 恋人档增长减速
        if cfg.progression.lover_growth_slowdown and old_score >= 91 and adj_delta > 2:
            adj_delta = 2

        # 4. 晋级门槛校验
        candidate = clamp(old_score + adj_delta, cfg.score.min_score, cfg.score.max_score)
        # → 喜欢：需要最低置信度
        if old_score <= 80 < candidate and confidence < cfg.progression.liked_unlock_min_confidence:
            candidate = min(candidate, 80)
        # → 恋人：需要置信度 + 正向评价次数
        if old_score <= 90 < candidate:
            enough_conf = confidence >= cfg.progression.lover_unlock_min_confidence
            enough_hist = int(user.get("positive_eval_count", 0) or 0) >= cfg.progression.lover_min_positive_eval_count
            if not (enough_conf and enough_hist):
                candidate = min(candidate, 90)

        # 5. 写入变更
        actual_delta = candidate - old_score
        user["score"] = candidate
        user["updated_at"] = now()
        user["last_eval_at"] = now()
        if actual_delta > 0:
            user["positive_eval_count"] = int(user.get("positive_eval_count", 0) or 0) + 1
        elif actual_delta < 0:
            user["negative_eval_count"] = int(user.get("negative_eval_count", 0) or 0) + 1

        # 6. 记录评分原因
        if cfg.privacy.store_reasons and cfg.privacy.max_reason_records > 0:
            records = user.setdefault("recent_reasons", [])
            if not isinstance(records, list):
                records = []
                user["recent_reasons"] = records
            records.append({
                "delta": actual_delta,
                "reason": clean_text(reason, 160),
                "confidence": round(float(confidence), 3),
                "risk": risk,
                "timestamp": now(),
                "session_id": session_id,
            })
            max_records = int(cfg.privacy.max_reason_records)
            if len(records) > max_records:
                del records[:-max_records]

        self.save_user(user_id, user)
        return user, actual_delta

    # ── 久未互动衰减 ─────────────────────────────────────────────

    def _calculate_inactivity_decay(
        self, user: dict[str, Any], cfg: FavorabilityConfig, ts: float
    ) -> tuple[int, int, int]:
        """计算因长期未互动导致的好感度衰减。

        Returns:
            (新分数, 实际变化值, 已未互动天数)
        """
        last = float(user.get("last_interaction_at", user.get("updated_at", ts)) or ts)
        elapsed_days = int((ts - last) // 86400)
        old_score = int(user.get("score", cfg.score.default_score) or 0)

        if not cfg.inactivity_decay.enabled or elapsed_days <= int(cfg.inactivity_decay.grace_days):
            return old_score, 0, elapsed_days

        interval = max(1, int(cfg.inactivity_decay.interval_days))
        periods = 1 + (elapsed_days - int(cfg.inactivity_decay.grace_days)) // interval
        decay = min(periods * int(cfg.inactivity_decay.delta_per_interval), int(cfg.inactivity_decay.max_delta_once))
        floor = max(int(cfg.score.min_score), int(cfg.inactivity_decay.min_score))
        new_score = max(floor, old_score - decay)
        return new_score, new_score - old_score, elapsed_days

    def preview_inactivity_decay(
        self, user_id: str, cfg: FavorabilityConfig
    ) -> tuple[dict[str, Any], int, int, int]:
        """预览久未互动衰减效果（不写入数据库）"""
        user = self.get_user(user_id, cfg.score.default_score)
        new_score, actual_delta, elapsed = self._calculate_inactivity_decay(user, cfg, now())
        return user, new_score, actual_delta, elapsed

    def apply_inactivity_decay(
        self, user_id: str, cfg: FavorabilityConfig, session_id: str = ""
    ) -> tuple[dict[str, Any], int]:
        """应用久未互动衰减并写入数据库"""
        user = self.get_user(user_id, cfg.score.default_score)
        ts = now()
        new_score, actual_delta, elapsed = self._calculate_inactivity_decay(user, cfg, ts)

        # 无论是否衰减，都刷新最后互动时间
        user["last_interaction_at"] = ts
        if actual_delta == 0:
            self.save_user(user_id, user)
            return user, 0

        user["score"] = new_score
        user["updated_at"] = ts

        # 记录衰减原因
        if cfg.privacy.store_reasons and cfg.privacy.max_reason_records > 0:
            records = user.setdefault("recent_reasons", [])
            if not isinstance(records, list):
                records = []
                user["recent_reasons"] = records
            records.append({
                "delta": actual_delta,
                "reason": f"连续 {elapsed} 天未互动，好感度自然衰减",
                "confidence": 1.0,
                "risk": "inactivity_decay",
                "timestamp": ts,
                "session_id": session_id,
            })
            max_records = int(cfg.privacy.max_reason_records)
            if len(records) > max_records:
                del records[:-max_records]

        self.save_user(user_id, user)
        return user, actual_delta
