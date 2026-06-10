from pathlib import Path
import re

# ── 配置 Schema 版本 ──────────────────────────────────────────────
CONFIG_SCHEMA_VERSION = "1.1.1"

# ── 路径常量 ─────────────────────────────────────────────────────
# 插件包所在目录，数据文件存放在其下的 data/ 子目录
PLUGIN_DIR = Path(__file__).resolve().parent
DATA_PATH = PLUGIN_DIR / "data" / "favorability.sqlite3"
LEGACY_DATA_PATH = PLUGIN_DIR / "data" / "favorability.json"

# ── 正则模式 ─────────────────────────────────────────────────────
# QQ 号格式：5~12 位纯数字
QQ_PATTERN = re.compile(r"\d{5,12}")

# 涩图请求关键词匹配（涵盖"涩/瑟/色"等变体）
SPICY_REQUEST_PATTERN = re.compile(
    r"(涩|瑟|色|社保|色色|涩涩|瑟瑟|色图|涩图|瑟图|涩一张"
    r"|来点.*[涩瑟色]|想看.*[涩瑟色]|求.*[涩瑟色])"
)

# ── 图片格式 ─────────────────────────────────────────────────────
# Immich 中识别为图片的文件扩展名
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

# ── 涩图相册名称 ────────────────────────────────────────────────
SPICY_LOW_ALBUM = "涩涩-低"
SPICY_MEDIUM_ALBUM = "涩涩-中"
SPICY_HIGH_ALBUM = "涩涩-高"
SPICY_ALBUM_NAMES = [SPICY_LOW_ALBUM, SPICY_MEDIUM_ALBUM, SPICY_HIGH_ALBUM]

# ── 好感度过低时的嘲讽消息 ──────────────────────────────────────
# 当好感度为负且随机到拒绝时发送
TAUNT_MESSAGES = [
    "你也配看？先攒攒好感度吧。",
    "哼，关系这么差还想要图，脸皮真厚。",
    "不给，自己反省一下为什么好感度这么低。",
    "想得美，先把好感度刷回正数再说。",
    "你现在只适合被我冷处理。",
]

# ── 负好感度惩罚配图提示 ────────────────────────────────────────
# 当好感度为负但仍发图（惩罚图）时附带的消息
POOP_TAUNTS = [
    "给你挑了张最适合你当前好感度的。",
    "关系这么差，就先看这个吧。",
    "这张和你的好感度很搭，哼。",
    "别嫌弃，这是你现在应得的待遇。",
]
