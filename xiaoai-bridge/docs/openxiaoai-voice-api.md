# OpenXiaoAI Voice API 文档

## 简介

OpenXiaoAI HTTP API 提供了一套远程控制小爱音箱播放语音的接口。通过网络请求即可让小爱音箱播放文字、音频文件或远程音频，支持接入第三方 TTS 服务（如豆包语音合成）。

### 应用场景

- **智能家居**：与其他智能家居系统联动，实现语音播报
- **消息通知**：将系统告警、消息通知转为语音播报
- **AI 对话**：接入大模型 API，实现语音交互的 AI 助手
- **定时任务**：定时播报天气、新闻、日程提醒等

### 上下游架构

```
┌─────────────────┐     HTTP API      ┌─────────────────┐     WebSocket     ┌─────────────┐
│   上游应用       │ ─────────────────→ │  OpenXiaoAI     │ ────────────────→ │  小爱音箱    │
│  (你的服务/脚本) │                    │  HTTP API 服务  │                   │  (播放语音)  │
└─────────────────┘                    └─────────────────┘                   └─────────────┘
                                              │
                                              ↓ HTTP API (字节跳动)
                                       ┌─────────────────┐
                                       │   豆包语音合成    │
                                       │   (TTS 服务)     │
                                       └─────────────────┘
```

| 层级 | 组件 | 说明 |
|------|------|------|
| 上游 | 用户应用/脚本 | 调用 HTTP API 发送播放指令 |
| 中游 | OpenXiaoAI API | 接收 HTTP 请求，转换为小爱协议 |
| 下游 | 小爱音箱 | 接收 WebSocket 指令，播放语音 |
| 下游 | 豆包 TTS | 提供语音合成服务（可选） |

## 接口概览

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/status` | GET | 获取音箱状态 |
| `/api/wakeup` | POST | 唤醒小爱 |
| `/api/interrupt` | POST | 打断当前播放 |
| `/api/play/file` | POST | 上传并播放音频文件 |
| `/api/play/text` | POST | 小爱 TTS 播放文字 |
| `/api/play/url` | POST | 播放远程音频 URL |
| `/api/tts/doubao` | POST | 豆包 TTS 语音合成 |
| `/api/tts/doubao_voices` | GET | 获取豆包 TTS 音色列表 |

## 基础信息

- **Base URL**: `http://{host}:9092`
- **Content-Type**: `application/json`

---

## 健康检查

### GET /api/health

检查服务状态。

**Response:**
```json
{
  "success": true,
  "data": {
    "status": "healthy",
    "speaker_ready": true
  }
}
```

### 字段说明

| 字段 | 说明 |
|------|------|
| status | 服务状态：`"healthy"`, `"unhealthy"` |
| speaker_ready | 是否音箱已初始化并准备好接收指令 |

---

## 获取音箱状态

### GET /api/status

获取当前音箱的播放状态。

**Response:**
```json
{
  "success": true,
  "data": {
    "status": "idle"
  }
}
```

**字段说明：**

| 字段 | 说明 |
|------|------|
| status | 播放状态：`"playing"`, `"paused"`, `"idle"` |

---

## 唤醒音箱

### POST /api/wakeup

唤醒小爱音箱（相当于说"小爱同学"）。

**Request Body:**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| silent | bool | 否 | 是否静默唤醒（不播放提示音），默认 `true` |

**Example:**
```bash
curl -X POST http://{host}:9092/api/wakeup \
  -H "Content-Type: application/json" \
  -d '{"silent": true}'
```

---

## 打断播放

### POST /api/interrupt

打断当前播放（相当于按音箱的暂停/打断键）。

**Example:**
```bash
curl -X POST http://{host}:9092/api/interrupt
```

---

## 播放音频文件

### POST /api/play/file

上传音频文件并播放。

**Parameters:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | 音频文件 (mp3, wav, etc.) |
| blocking | bool | 否 | 是否阻塞等待播放完成，默认 `false` |

**Example (curl):**
```bash
curl -X POST "http://{host}:9092/api/play/file?blocking=true" \
  -F "file=@/path/to/audio.mp3"
```

---

## 播放文字 (TTS)

### POST /api/play/text

使用小爱自带 TTS 播放文字。

**Request Body:**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| text | string | 是 | 要播放的文字 |
| blocking | bool | 否 | 是否阻塞等待，默认 `false` |
| timeout | int | 否 | 超时时间（毫秒），默认 60000 |

**Example:**
```bash
curl -X POST http://{host}:9092/api/play/text \
  -H "Content-Type: application/json" \
  -d '{"text": "你好", "blocking": false}'
```

---

## 播放远程 URL

### POST /api/play/url

播放远程音频 URL。

**Request Body:**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| url | string | 是 | 音频 URL |
| blocking | bool | 否 | 是否阻塞等待，默认 `false` |
| timeout | int | 否 | 超时时间（毫秒），默认 60000 |

**Example:**
```bash
curl -X POST http://{host}:9092/api/play/url \
  -H "Content-Type: application/json" \
  -d '{"url": "http://example.com/audio.mp3", "blocking": false}'
```

---

## 豆包 TTS

### POST /api/tts/doubao

使用豆包（字节跳动火山引擎）语音合成播放。

**Request Body:**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| text | string | 是 | 要合成的文本 |
| app_id | string | 否 | App ID（默认从 config.py 读取） |
| access_key | string | 否 | Access Key（默认从 config.py 读取） |
| resource_id | string | 否 | 资源 ID（自动根据音色检测） |
| speaker_id | string | 否 | 音色 ID（默认 `zh_female_vv_uranus_bigtts`） |
| speed | float | 否 | 语速，0.8-2.0（默认 1.0） |
| emotion | string | 否 | 情感参数（仅多情感音色支持） |
| context_texts | array | 否 | 上下文指令（仅 2.0 音色支持） |
| blocking | bool | 否 | 是否阻塞等待（默认 `false`） |

**Example - 基础调用:**
```bash
curl -X POST http://{host}:9092/api/tts/doubao \
  -H "Content-Type: application/json" \
  -d '{"text": "你好，我是豆包语音助手"}'
```

**Example - 指定音色和情感:**
```bash
curl -X POST http://{host}:9092/api/tts/doubao \
  -H "Content-Type: application/json" \
  -d '{
    "text": "你怎么能这样！",
    "speaker_id": "zh_male_lengkugege_emo_v2_mars_bigtts",
    "emotion": "angry"
  }'
```

**Example - 2.0 音色 + 指令控制:**
```bash
curl -X POST http://{host}:9092/api/tts/doubao \
  -H "Content-Type: application/json" \
  -d '{
    "text": "这是一个很长的句子",
    "speaker_id": "zh_female_vv_uranus_bigtts",
    "context_texts": ["你可以说慢一点吗？"]
  }'
```

---

## 获取音色列表

### GET /api/tts/doubao_voices

获取豆包 TTS 可用音色列表。

**Query Parameters:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| version | string | 否 | 版本筛选：`"1.0"`, `"2.0"`, `"all"` |

**Example:**
```bash
# 获取所有版本概览
curl http://{host}:9092/api/tts/doubao_voices

# 仅获取 2.0 音色
curl http://{host}:9092/api/tts/doubao_voices?version=2.0

# 仅获取 1.0 音色
curl http://{host}:9092/api/tts/doubao_voices?version=1.0
```

---

## 音色分类

> 完整音色列表及详细说明请参考官方文档：[大模型语音合成API-音色列表](https://www.volcengine.com/docs/6561/1257544?lang=zh)

### 2.0 音色 (seed-tts-2.0)

| 音色名称 | voice_type | 特点 |
|---------|------------|------|
| Vivi 2.0 | zh_female_vv_uranus_bigtts | 通用场景，情感变化 |
| 小何 2.0 | zh_female_xiaohe_uranus_bigtts | 通用场景 |
| 云舟 2.0 | zh_male_m191_uranus_bigtts | 通用场景 |
| 小天 2.0 | zh_male_taocheng_uranus_bigtts | 通用场景 |
| 儿童绘本 | zh_female_xueayi_saturn_bigtts | 有声阅读 |
| 大壹 | zh_male_dayi_saturn_bigtts | 视频配音 |
| ... | ... | ... |

### 1.0 音色 (seed-tts-1.0)

| 音色名称 | voice_type | 特点 |
|---------|------------|------|
| 灿灿 | zh_female_cancan_mars_bigtts | 通用场景 |
| 爽快思思 | zh_female_shuangkuaisisi_moon_bigtts | 通用场景 |
| 冷酷哥哥(多情感) | zh_male_lengkugege_emo_v2_mars_bigtts | 支持 emotion 参数 |
| 高冷御姐(多情感) | zh_female_gaolengyujie_emo_v2_mars_bigtts | 支持 emotion 参数 |
| ... | ... | ... |

---

## 情感参数 (emotion)

仅**多情感音色**支持（如 `zh_male_lengkugege_emo_v2_mars_bigtts`）。

> 完整情感参数及支持音色请参考官方文档：[大模型语音合成API-音色列表-多情感音色](https://www.volcengine.com/docs/6561/1257544?lang=zh)

| 中文情感 | 英文参数 |
|---------|---------|
| 开心 | happy |
| 悲伤 | sad |
| 生气 | angry |
| 惊讶 | surprised |
| 恐惧 | fear |
| 厌恶 | hate |
| 激动 | excited |
| 冷漠 | coldness |
| 中性 | neutral |
| 沮丧 | depressed |
| 撒娇 | lovey-dovey |
| 害羞 | shy |
| 安慰鼓励 | comfort |
| 咆哮/焦急 | tension |
| 温柔 | tender |
| 讲故事 | storytelling |
| 情感电台 | radio |
| 磁性 | magnetic |
| 广告营销 | advertising |
| 气泡音 | vocal-fry |
| 低语 | ASMR |
| 新闻播报 | news |
| 娱乐八卦 | entertainment |
| 方言 | dialect |

---

## 配置说明

在 `config.py` 中配置豆包 TTS 默认参数：

```python
"tts": {
    "doubao": {
        "app_id": "your_app_id",
        "access_key": "your_access_key",
        # "resource_id": "seed-tts-2.0",  # 可选，自动检测
        "default_speaker": "zh_female_vv_uranus_bigtts",
    }
}
```

---

## 错误码

| HTTP Status | 说明 |
|------------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 500 | 服务器内部错误 |
| 503 | Speaker 未初始化 |
