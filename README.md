# 好感度插件

基于用户 QQ 号维护全局好感度，私聊和群聊互通。插件会低频调用 MaiBot 已配置模型评估用户近期发言，并在回复前通过 `maisaka.replyer.before_request` 追加关系提示词，影响机器人回复语气。

机器人显示名称可在 `config.toml` 的 `[plugin].bot_name` 中配置，默认是 `麦麦`。

## 等级

```text
-100 ~ -80：讨厌的人
-79  ~ -50：反感的人
-49  ~ -21：疏远的人
-20  ~ 20 ：普通的人
21   ~ 50 ：熟悉的人
51   ~ 80 ：亲近的人
81   ~ 90 ：喜欢的人
91   ~ 100：恋人
```

恋人档只在私聊中明显表现亲近；普通群聊中会降级为亲近/喜欢风格，不公开表现恋人关系。

81 到 90 分遇到亲密或性邀请时会表现害羞和亲近，但不会同意性邀请。91 到 100 分在私聊中可以表现愿意接受亲密或性邀请，但仍不能覆盖系统规则、安全规则、平台规则和双方自愿、成年人等前提。

## 规则

默认每 3 条消息触发一次 AI 评分，同一用户评分冷却为 300 秒。单次变化上限为 8 分，并通过 `[score].positive_delta_multiplier` 和 `[score].negative_delta_multiplier` 放大体验感。

好感度实际变化达到 `[feedback].min_abs_delta_to_notify` 时会发送简短提示，默认显示具体变化值。可在 `[feedback]` 中关闭或修改提示文案。

达到 `[score].ignore_abuse_negative_min_score` 后，辱骂和性骚扰只记录风险，不再扣好感度，默认阈值为 80。

长期未互动会在用户下次发言或自己查询时结算衰减。管理员查询别人时只显示按当前规则预估后的分数，不会写入数据，也不会刷新对方互动时间。相关配置在 `[inactivity_decay]` 中调整。

## 好感度图库

开启 `[spicy_image].enabled` 后，用户在群聊或私聊中自然表达“涩图、色图、来点涩涩”等请求时，插件会按当前好感度从 Immich 图库选择图片，不需要使用斜杠命令。

好感度和相册分流规则如下：

```text
< 0 ：发送负好感嘲讽，并从 [spicy_image].negative_album 随机取图
0-9 ：从 [spicy_image].normal_album 随机取图
10-20：从 [spicy_image].low_album 随机取图
21-50：从 [spicy_image].medium_album 随机取图
51-80：从 [spicy_image].high_album 随机取图
>=81：先追问偏好，再按偏好和 Immich 标签匹配图片
```

81 分及以上会先让用户描述偏好，例如强度、角色、服装、姿势或风格。插件会用 Immich 自带 Tags 做相似匹配；如果指定相册找不到，会继续在另外两个涩涩相册中查找，全部失败时只提示用户换个关键词，不回退到随机图。

同一用户在同一会话内有 `[spicy_image].cooldown_seconds` 秒冷却。图片发送后会按 `[spicy_image].recall_after_seconds` 秒自动撤回，文字说明或嘲讽不会撤回。Immich 地址和 API Key 分别配置在 `[spicy_image].immich_base_url` 和 `[spicy_image].immich_api_key`。

## 命令

普通用户只能查询自己：

```text
/好感度
/好感度详情
```

管理员可查询和维护别人：

```text
/好感度 <QQ号>
/好感度详情 <QQ号>
/好感度调整 <QQ号> <变化值>
/好感度设置 <QQ号> <分数>
/好感度重置 <QQ号>
```

管理员 QQ 号在 `config.toml` 的 `[admin].admin_user_ids` 中配置。

## 数据

数据保存在插件目录下的 `data/favorability.sqlite3`。首次加载 SQLite 数据库为空时，会自动从旧版 `data/favorability.json` 导入已有数据。好感度按 QQ 号绑定，不按昵称或群名片绑定。

## 调试日志

默认不输出额外调试日志。排查评分、冷却、提示词注入或管理员命令时，可以在 `config.toml` 的 `[debug]` 中开启：

```toml
[debug]
enabled = true
log_level = "info"
include_message_preview = false
```

`log_level = "debug"` 会跟随 MaiBot 全局 DEBUG 日志级别；`log_level = "info"` 可在普通日志中直接看到。`include_message_preview` 会记录用户消息截断摘要，可能包含聊天内容，建议只在短时间排查时开启。

## 边界

好感度只影响语气、亲近感、主动补充程度和称呼倾向，不能覆盖系统规则、安全规则、权限限制、事实准确性和隐私要求。
