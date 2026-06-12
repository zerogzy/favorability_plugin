"""
好感度插件 - Immich 图库 API 客户端

封装与 Immich 图库服务的 HTTP 交互，包括：
- 相册查询与资源列表获取
- 标签列表查询
- 随机搜索与原图下载
"""

from __future__ import annotations

import json
from contextlib import closing
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import asyncio

from .constants import IMAGE_EXTENSIONS
from .utils import is_image_asset, normalize_for_match
from pathlib import Path


class ImmichClient:
    """Immich 图库 HTTP 客户端。

    通过 REST API 与 Immich 交互，支持相册查询、标签搜索、
    随机资源检索和原图下载。所有网络请求在独立线程中执行，
    避免阻塞异步事件循环。
    """

    def __init__(self, base_url: str, api_key: str, timeout: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key.strip()
        self._timeout = timeout

    # ── 底层请求 ─────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        """发送 HTTP 请求到 Immich API。

        自动尝试带 /api 前缀的路径作为降级。
        返回 JSON 解析结果或原始二进制数据。
        """
        query = ""
        if params:
            query = "?" + urlencode(
                {k: v for k, v in params.items() if v is not None}, doseq=True
            )

        body = None
        headers = {"x-api-key": self._api_key}
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        # 尝试原始路径和 /api 前缀路径
        urls = [f"{self._base_url}{path}{query}"]
        if not self._base_url.endswith("/api"):
            urls.append(f"{self._base_url}/api{path}{query}")

        last_error: Exception | None = None
        for url in urls:
            request = Request(url, data=body, headers=headers, method=method)
            try:
                with urlopen(request, timeout=self._timeout) as response:
                    content_type = response.headers.get("Content-Type", "")
                    payload = response.read()
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")[:300]
                last_error = RuntimeError(f"Immich API 请求失败：HTTP {exc.code} {detail}")
                continue
            except URLError as exc:
                raise RuntimeError(f"Immich API 连接失败：{exc.reason}") from exc

            # JSON 响应直接解析
            if "application/json" in content_type:
                return json.loads(payload.decode("utf-8"))
            # 非HTML二进制响应直接返回
            if "text/html" not in content_type.lower():
                return payload

        if last_error is not None:
            raise last_error
        return b""

    # ── 相册操作 ─────────────────────────────────────────────────

    async def get_album_by_name(self, name: str) -> dict[str, Any] | None:
        """按名称查找相册，返回相册字典或 None"""
        albums = await asyncio.to_thread(self._request, "GET", "/albums")
        if not isinstance(albums, list):
            return None
        normalized = normalize_for_match(name)
        for album in albums:
            if isinstance(album, dict) and normalize_for_match(
                album.get("albumName") or album.get("name")
            ) == normalized:
                return album
        return None

    async def get_album_assets(self, album_id: str) -> list[dict[str, Any]]:
        """获取相册中的所有图片资源"""
        album = await asyncio.to_thread(self._request, "GET", f"/albums/{album_id}")
        if not isinstance(album, dict):
            return []
        assets = album.get("assets") or []
        return [a for a in assets if isinstance(a, dict) and is_image_asset(a)]

    # ── 标签操作 ─────────────────────────────────────────────────

    async def list_tags(self) -> list[dict[str, Any]]:
        """获取所有标签列表"""
        tags = await asyncio.to_thread(self._request, "GET", "/tags")
        if isinstance(tags, list):
            return [t for t in tags if isinstance(t, dict)]
        return []

    # ── 搜索与下载 ───────────────────────────────────────────────

    async def search_random_assets(
        self, album_id: str, tag_ids: list[str], size: int
    ) -> list[dict[str, Any]]:
        """在相册中随机搜索图片资源，可按标签过滤"""
        payload: dict[str, Any] = {
            "albumIds": [album_id],
            "size": size,
            "type": "IMAGE",
            "withDeleted": False,
        }
        if tag_ids:
            payload["tagIds"] = tag_ids
        assets = await asyncio.to_thread(self._request, "POST", "/search/random", data=payload)
        if isinstance(assets, list):
            return [a for a in assets if isinstance(a, dict) and is_image_asset(a)]
        return []

    async def download_asset(self, asset_id: str) -> bytes:
        """下载图片原始文件，返回二进制数据"""
        data = await asyncio.to_thread(self._request, "GET", f"/assets/{asset_id}/original")
        if not isinstance(data, bytes):
            raise RuntimeError("Immich 下载资源返回了非二进制数据")
        return data
