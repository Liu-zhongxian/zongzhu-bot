
:::danger
2026.03.02提供V3版本训练接口支持一次训练可以在多款模型上使用，[V1版本训练接口](https://www.volcengine.com/docs/6561/1305191?lang=zh)不再迭代。
:::
:::warning
豆包声音复刻模型自上线以来，受到广大客户的欢迎，目前已有多款模型能力支持复刻功能，如声音复刻、声音复刻2.0、豆包端到端实时语音模型，后续还会推出更多模型支持复刻能力。为了方便客户使用，减少不同模型间的音色不通用，需重复下单、单独管理的问题，我们对音色机制进行了升级，使音色能适用于各个模型。
:::
:::warning
`model_type=1、2、3`为声音复刻ICL1.0效果，`model_type=4`为声音复刻ICL2.0效果。
2025.10.16开始提供声音复刻ICL2.0效果，调用时注意传递`model_type=4`为声音复刻ICL2.0效果。
2025.04.30开始提供DiT复刻效果（更适合非实时场景），`model_type=2`为DiT标准版效果（音色、不还原用户的风格），`model_type=3`为DiT还原版效果（音色、还原用户口音、语速等风格）。
2024.07.10开始提供声音复刻ICL1.0效果，调用时注意传递`model_type=1`，另外原始音频如果不是中文也必须指定语种。
:::
:::warning
使用声音复刻V3版本接口训练的音色，调用大模型语音合成接口进行语音合成的时候，会根据`X-Api-Resource-Id`自动选择对应版本的效果。
在使用大模型语音合成-V3版本API时，需要指定`X-Api-Resource-Id`：
`seed-icl-1.0`（声音复刻ICL1.0字符版）
`seed-icl-1.0-concurr`（声音复刻ICL1.0并发版）
`seed-icl-2.0`  (声音复刻ICL2.0字符版)
:::
<span id="597da1a0"></span>
# 音色复刻训练接口
<span id="3f616aa6"></span>
## 请求路径

* 服务使用的请求路径：`https://openspeech.bytedance.com/api/v3/tts/voice_clone`

<span id="91db8ac6"></span>
## 建连&鉴权

* HTTP 请求头（Request Header 中）添加以下信息


| | | | | \
|**Key** |**说明** |**是否必须** |**Value 示例** |
|---|---|---|---|
| | | | | \
|Content-Type |固定值 |必须 |"application/json" |
| | | | | \
|X-Api-App-Key |使用火山引擎控制台获取的APP ID，可参考 [控制台使用FAQ-Q1](https://www.volcengine.com/docs/6561/196768#q1%EF%BC%9A%E5%93%AA%E9%87%8C%E5%8F%AF%E4%BB%A5%E8%8E%B7%E5%8F%96%E5%88%B0%E4%BB%A5%E4%B8%8B%E5%8F%82%E6%95%B0appid%EF%BC%8Ccluster%EF%BC%8Ctoken%EF%BC%8Cauthorization-type%EF%BC%8Csecret-key-%EF%BC%9F) |必须 |123456789 |
| | | | | \
|X-Api-Access-Key |使用火山引擎控制台获取的Access Token，可参考 [控制台使用FAQ-Q1](https://www.volcengine.com/docs/6561/196768#q1%EF%BC%9A%E5%93%AA%E9%87%8C%E5%8F%AF%E4%BB%A5%E8%8E%B7%E5%8F%96%E5%88%B0%E4%BB%A5%E4%B8%8B%E5%8F%82%E6%95%B0appid%EF%BC%8Ccluster%EF%BC%8Ctoken%EF%BC%8Cauthorization-type%EF%BC%8Csecret-key-%EF%BC%9F) |必须 |your-access-key |
| | | | | \
|X-Api-Request-Id |标识客户端请求ID，uuid随机字符串 |必须 |67ee89ba-7050-4c04-a3d7-ac61a63499b3 |


* 在HTTP请求成功后，会返回这些 Response header


| | | | \
|**Key** |**说明** |**Value 示例** |
|---|---|---|
| | | | \
|X-Tt-Logid |服务端返回的 logid，建议用户获取和打印方便定位问题 |202407261553070FACFE6D19421815D605 |

<span id="6130e8a9"></span>
## 请求参数

| | | | | | \
|**参数名称** |**层级** |**参数类型** |**是否必须** |**备注** |
|---|---|---|---|---|
| | | | | | \
|speaker_id |1 |string |必须 |唯一音色代号 |
| | | | | | \
|audio |\
| |1 |\
| | |object |必须 |\
| | | | |音频格式支持：wav、mp3、ogg、m4a、aac、pcm，其中pcm仅支持24k，单通道 |\
| | | | |目前限制文件上传最大10MB |
| | | | | | \
|data |2 |string |必须 |二进制音频字节，需对二进制音频进行base64编码 |
| | | | | | \
|format |2 |string |可选 |音频格式，pcm、m4a必传，其余可选 |
| | | | | | \
|text |\
| |2 |string |\
| | | |可选 |可以让用户按照该文本念诵，服务会对比音频与该文本的差异。若差异过大会返回45001109 WERError。 |
| | | | | | \
|language |1 |int |可选，建议设置 |建议设置，会影响试听文本的语种。 |\
| | | | |使用当前接口注册可以在多个产品上使用。 |\
| | | | | |\
| | | | |1. 当语种为++中文、英文++的时候支持音色在声音复刻ICL 1.0、声音复刻ICL 2.0、S2S 1.0、S2S 2.0上使用。 |\
| | | | |2. 当语种为++日语、西班牙语、印尼语、葡萄牙语++的时候支持音色在声音复刻ICL 1.0上使用、音色不支持在声音复刻ICL 2.0、S2S 1.0、S2S 2.0上使用。 |\
| | | | |3. 当语种为++德语、法语++的时候支持音色在声音复刻ICL1.0上使用，且合成效果为DiT标准版效果（音色、不还原用户的风格）。 |\
| | | | | |\
| | | | |以下为语种对应的枚举值 |\
| | | | | |\
| | | | |* cn = 0 中文（默认） |\
| | | | |* en = 1 英文 |\
| | | | |* ja = 2 日语 |\
| | | | |* es = 3 西班牙语 |\
| | | | |* id = 4 印尼语 |\
| | | | |* pt = 5 葡萄牙语 |\
| | | | |* de = 6 德语 |\
| | | | |* fr = 7 法语 |
| | | | | | \
|model_types |\
| |1 |[]int |可选 |默认不用传 |\
| | | | |++1 为声音复刻ICL1.0效果，语种支持++ |\
| | | | | |\
| | | | |* cn = 0 中文（默认） |\
| | | | |* en = 1 英文 |\
| | | | |* ja = 2 日语 |\
| | | | |* es = 3 西班牙语 |\
| | | | |* id = 4 印尼语 |\
| | | | |* pt = 5 葡萄牙语 |\
| | | | | |\
| | | | |++2 为DiT标准版效果（音色、不还原用户的风格），语种支持++ |\
| | | | | |\
| | | | |* cn = 0 中文（默认） |\
| | | | |* en = 1 英文 |\
| | | | |* ja = 2 日语 |\
| | | | |* es = 3 西班牙语 |\
| | | | |* id = 4 印尼语 |\
| | | | |* pt = 5 葡萄牙语 |\
| | | | |* de = 6 德语 |\
| | | | |* fr = 7 法语 |\
| | | | | |\
| | | | |++3 为DiT还原版效果（音色、还原用户口音、语速等风格），语种支持++ |\
| | | | | |\
| | | | |* cn = 0 中文（默认） |\
| | | | |* en = 1 英文 |\
| | | | | |\
| | | | |++4 为声音复刻ICL2.0效果，语种支持++ |\
| | | | | |\
| | | | |* cn = 0 中文（默认） |\
| | | | |* en = 1 英文 |
| | | | | | \
|extra_params |1 |object |可选 | |
| | | | | | \
|demo_text |\
| |2 |string |\
| | | |可选 |试听文本，长度在4和80字之间，如果指定了语种需要传入对应语种的文本，否则会合成失败。 |
| | | | | | \
|enable_audio_denoise |2 |bool |可选 |是否开启降噪，开启降噪可能会对声音细节有一定影响，音频样本噪声较大的情况下建议开启降噪，音频样本质量较好的情况下建议关闭降噪。如果不设置该字段，声音复刻ICL1.0，即`model_type`为1/2/3时默认值为true，声音复刻ICL2.0，即`model_type`为4时默认值为false。 |
| | | | | | \
|enable_audio_denoise_with_snr |2 |bool |可选 |是否开启根据降噪检测阈值`denoise_max_snr_thresh`进行降噪，需要配合开启`enable_audio_denoise` |
| | | | | | \
|denoise_max_snr_thresh |2 |int |可选 |降噪检测阈值，默认为50。有效范围大于0，小于100。 |
| | | | | | \
|reject_min_snr_thresh |2 |float |可选 |信噪比低于该值拒绝复刻，当前默认值为5，会降低复刻成功率。有效范围大于0，小于100。 |
| | | | | | \
|voice_clone_denoise_model_id |2 |string |可选 |\
| | | | |人声美化模型选择，去除音频样本中的噪音等（可能会不同程度影响声音细节），复刻结果有明显噪声的情况下可以尝试切换不同的模型来测试不同效果。 |\
| | | | |默认为: `""` （空的时候默认是 `SpeechInpaintingV2`） |\
| | | | |可选值： |\
| | | | | |\
| | | | |* `SpeechInpaintingV2` （默认值） |\
| | | | |* `VocalDiffusionV2VocalDiffusionV2_44k` |
| | | | | | \
|voice_clone_enable_mss |2 |bool |可选 |是否使用音源分离去除音频样本中背景音，默认值：`false`。 |
| | | | | | \
|enable_crop_by_asr |2 |bool |可选 |\
| | | | |ASR 截断能避免单个字的发音被切开，核心原因是它能精准定位单个字在音频中的位置。默认的音频时长截断（时长 25s）则可能出现单个字发音被切开的情况。 |\
| | | | |默认值：`false` |
| | | | | | \
|enable_check_prompt_text_quality |2 |bool |可选 |是否开启音频ASR文本质量检测，会降低复刻成功率。 |
| | | | | | \
|enable_check_audio_quality |2 |bool |可选 |是否开启音频质量检测，会降低复刻成功率。 |

<span id="f6cfe46f"></span>
## **请求示例**
```JSON
{
    "speaker_id": "S_*******", // （需从控制台获取，参考文档：声音复刻下单及使用指南）
    "audios": {
        "data": "base64编码后的音频",
        "format": "wav"
    },
    "language": 0,
    "extra_params": {
        "voice_clone_denoise_model_id": ""
    }
}
```

<span id="8f420ddf"></span>
## 返回参数

| | | | | | \
|**参数名称** |**层级** |**参数类型** |**是否必须** |**备注** |
|---|---|---|---|---|
| | | | | | \
|code |1 |int |可选 |训练失败时候HTTP返回非200，该字段返回详细错误码 |
| | | | | | \
|message |1 |string |可选 |训练失败时候HTTP返回非200，该字段返回详细错误信息 |
| | | | | | \
|available_training_times |1 |int |可选 |剩余训练次数 |
| | | | | | \
|create_time |1 |int |可选 |创建时间 |
| | | | | | \
|language |1 |\
| | |int |可选 |以下为语种对应的枚举值 |\
| | | | | |\
| | | | |* cn = 0 中文（默认） |\
| | | | |* en = 1 英文 |\
| | | | |* ja = 2 日语 |\
| | | | |* es = 3 西班牙语 |\
| | | | |* id = 4 印尼语 |\
| | | | |* pt = 5 葡萄牙语 |\
| | | | |* de = 6 德语 |\
| | | | |* fr = 7 法语 |
| | | | | | \
|speaker_id |1 |string |可选 |唯一音色代号 |
| | | | | | \
|status |\
| |1 |int |可选 |训练状态，状态为2或4时都可以调用tts |\
| | | | | |\
| | | | |* NotFound = 0 |\
| | | | |* Training = 1  |\
| | | | |* Success = 2  |\
| | | | |* Failed = 3 |\
| | | | |* Active = 4 |
| | | | | | \
|speaker_status |1 |object list |可选 |音色训练状态列表 |
| | | | | | \
|model_type |2 |int |\
| | | |可选 |\
| | | | |* 1 为声音复刻ICL 1.0效果 |\
| | | | |* 2 为DiT标准版效果（音色、不还原用户的风格） |\
| | | | |* 3 为DiT还原版效果（音色、还原用户口音、语速等风格） |\
| | | | |* 4 为声音复刻ICL 2.0效果 |
| | | | | | \
|demo_audio |2 |string |可选 |Success状态时返回，一小时有效，若需要，请下载后使用 |

<span id="277c02e7"></span>
## **返回示例**
```JSON
{
  "available_training_times": 15,
  "create_time": 1772026663000,
  "language": 0,
  "speaker_id": "S_*******",
  "speaker_status": [
    {
      "demo_audio": "https://x.bytespeech.com/S_*******",
      "model_type": 1
    },
    {
      "demo_audio": "https://x.bytespeech.com/S_*******",
      "model_type": 4
    }
  ],
  "status": 2
}
```

<span id="c2ffd552"></span>
# **音色复刻状态查询接口**
<span id="69649497"></span>
## 请求路径

* 服务使用的请求路径：`https://openspeech.bytedance.com/api/v3/tts/get_voice`

<span id="2ebfe613"></span>
## 建连&鉴权

* HTTP 请求头（Request Header 中）添加以下信息


| | | | | \
|**Key** |**说明** |**是否必须** |**Value 示例** |
|---|---|---|---|
| | | | | \
|Content-Type |固定值 |必须 |"application/json" |
| | | | | \
|X-Api-App-Key |使用火山引擎控制台获取的APP ID，可参考 [控制台使用FAQ-Q1](https://www.volcengine.com/docs/6561/196768#q1%EF%BC%9A%E5%93%AA%E9%87%8C%E5%8F%AF%E4%BB%A5%E8%8E%B7%E5%8F%96%E5%88%B0%E4%BB%A5%E4%B8%8B%E5%8F%82%E6%95%B0appid%EF%BC%8Ccluster%EF%BC%8Ctoken%EF%BC%8Cauthorization-type%EF%BC%8Csecret-key-%EF%BC%9F) |必须 |123456789 |
| | | | | \
|X-Api-Access-Key |使用火山引擎控制台获取的Access Token，可参考 [控制台使用FAQ-Q1](https://www.volcengine.com/docs/6561/196768#q1%EF%BC%9A%E5%93%AA%E9%87%8C%E5%8F%AF%E4%BB%A5%E8%8E%B7%E5%8F%96%E5%88%B0%E4%BB%A5%E4%B8%8B%E5%8F%82%E6%95%B0appid%EF%BC%8Ccluster%EF%BC%8Ctoken%EF%BC%8Cauthorization-type%EF%BC%8Csecret-key-%EF%BC%9F) |必须 |your-access-key |
| | | | | \
|X-Api-Request-Id |标识客户端请求ID，uuid随机字符串 |必须 |67ee89ba-7050-4c04-a3d7-ac61a63499b3 |


* 在HTTP请求成功后，会返回这些 Response header


| | | | \
|**Key** |**说明** |**Value 示例** |
|---|---|---|
| | | | \
|X-Tt-Logid |服务端返回的 logid，建议用户获取和打印方便定位问题 |202407261553070FACFE6D19421815D605 |

<span id="db2e855d"></span>
## **请求参数**

| | | | | | \
|**参数名称** |**层级** |**类型** |**是否必须** |**备注** |
|---|---|---|---|---|
| | | | | | \
|speaker_id |1 |string |必须 |唯一音色代号 |

<span id="a18adf8a"></span>
## **请求示例**
```JSON
{
    "speaker_id": "S_*******" // （需从控制台获取，参考文档：声音复刻下单及使用指南）
}
```

<span id="f244b905"></span>
## 返回参数

| | | | | | \
|**参数名称** |**层级** |**参数类型** |**是否必须** |**备注** |
|---|---|---|---|---|
| | | | | | \
|code |1 |int |可选 |训练失败时候HTTP返回非200，该字段返回详细错误码 |
| | | | | | \
|message |1 |string |可选 |训练失败时候HTTP返回非200，该字段返回详细错误信息 |
| | | | | | \
|available_training_times |1 |int |可选 |剩余训练次数 |
| | | | | | \
|create_time |1 |int |可选 |创建时间 |
| | | | | | \
|language |1 |\
| | |int |可选 |以下为语种对应的枚举值 |\
| | | | | |\
| | | | |* cn = 0 中文（默认） |\
| | | | |* en = 1 英文 |\
| | | | |* ja = 2 日语 |\
| | | | |* es = 3 西班牙语 |\
| | | | |* id = 4 印尼语 |\
| | | | |* pt = 5 葡萄牙语 |\
| | | | |* de = 6 德语 |\
| | | | |* fr = 7 法语 |
| | | | | | \
|speaker_id |1 |string |可选 |唯一音色代号 |
| | | | | | \
|status |\
| |1 |int |可选 |训练状态，状态为2或4时都可以调用tts语音合成接口。 |\
| | | | | |\
| | | | |* NotFound = 0 |\
| | | | |* Training = 1  |\
| | | | |* Success = 2  |\
| | | | |* Failed = 3 |\
| | | | |* Active = 4 |
| | | | | | \
|speaker_status |1 |object list |可选 |音色训练状态列表 |
| | | | | | \
|model_type |2 |int |\
| | | |可选 |\
| | | | |* 1 为声音复刻ICL 1.0效果 |\
| | | | |* 2 为DiT标准版效果（音色、不还原用户的风格） |\
| | | | |* 3 为DiT还原版效果（音色、还原用户口音、语速等风格） |\
| | | | |* 4 为声音复刻ICL 2.0效果 |
| | | | | | \
|demo_audio |2 |string |可选 |Success状态时返回，一小时有效，若需要，请下载后使用 |

<span id="28224986"></span>
## **返回示例**
```JSON
{
  "available_training_times": 15,
  "create_time": 1772026663000,
  "language": 0,
  "speaker_id": "S_*******",
  "speaker_status": [
    {
      "demo_audio": "https://x.bytespeech.com/S_*******",
      "model_type": 1
    },
    {
      "demo_audio": "https://x.bytespeech.com/S_*******",
      "model_type": 4
    }
  ],
  "status": 2
}
```

<span id="ede50cef"></span>
# **升级复刻音色接口**
支持将复刻音色升级成支持统一管理的音色。
<span id="48af06b7"></span>
## 请求路径

* 服务使用的请求路径：`https://openspeech.bytedance.com/api/v3/tts/upgrade_voice`

<span id="8db1bdf7"></span>
## 建连&鉴权

* HTTP 请求头（Request Header 中）添加以下信息


| | | | | \
|**Key** |**说明** |**是否必须** |**Value 示例** |
|---|---|---|---|
| | | | | \
|Content-Type |固定值 |必须 |"application/json" |
| | | | | \
|X-Api-App-Key |使用火山引擎控制台获取的APP ID，可参考 [控制台使用FAQ-Q1](https://www.volcengine.com/docs/6561/196768#q1%EF%BC%9A%E5%93%AA%E9%87%8C%E5%8F%AF%E4%BB%A5%E8%8E%B7%E5%8F%96%E5%88%B0%E4%BB%A5%E4%B8%8B%E5%8F%82%E6%95%B0appid%EF%BC%8Ccluster%EF%BC%8Ctoken%EF%BC%8Cauthorization-type%EF%BC%8Csecret-key-%EF%BC%9F) |必须 |123456789 |
| | | | | \
|X-Api-Access-Key |使用火山引擎控制台获取的Access Token，可参考 [控制台使用FAQ-Q1](https://www.volcengine.com/docs/6561/196768#q1%EF%BC%9A%E5%93%AA%E9%87%8C%E5%8F%AF%E4%BB%A5%E8%8E%B7%E5%8F%96%E5%88%B0%E4%BB%A5%E4%B8%8B%E5%8F%82%E6%95%B0appid%EF%BC%8Ccluster%EF%BC%8Ctoken%EF%BC%8Cauthorization-type%EF%BC%8Csecret-key-%EF%BC%9F) |必须 |your-access-key |
| | | | | \
|X-Api-Request-Id |标识客户端请求ID，uuid随机字符串 |必须 |67ee89ba-7050-4c04-a3d7-ac61a63499b3 |


* 在HTTP请求成功后，会返回这些 Response header


| | | | \
|**Key** |**说明** |**Value 示例** |
|---|---|---|
| | | | \
|X-Tt-Logid |服务端返回的 logid，建议用户获取和打印方便定位问题 |202407261553070FACFE6D19421815D605 |

<span id="28b26137"></span>
## **请求参数**

| | | | | | \
|**参数名称** |**层级** |**类型** |**是否必须** |**备注** |
|---|---|---|---|---|
| | | | | | \
|speaker_id |1 |string |必须 |唯一音色代号 |

<span id="37feaaa2"></span>
## **请求示例**
```JSON
{
    "speaker_id": "S_*******" // （需从控制台获取，参考文档：声音复刻下单及使用指南）
}
```

<span id="b7bb126e"></span>
## 返回参数

| | | | | | \
|**参数名称** |**层级** |**参数类型** |**是否必须** |**备注** |
|---|---|---|---|---|
| | | | | | \
|code |1 |int |可选 |训练失败时候HTTP返回非200，该字段返回详细错误码 |
| | | | | | \
|message |1 |string |可选 |训练失败时候HTTP返回非200，该字段返回详细错误信息 |
| | | | | | \
|available_training_times |1 |int |可选 |剩余训练次数 |
| | | | | | \
|create_time |1 |int |可选 |创建时间 |
| | | | | | \
|language |1 |\
| | |int |可选 |以下为语种对应的枚举值 |\
| | | | | |\
| | | | |* cn = 0 中文（默认） |\
| | | | |* en = 1 英文 |\
| | | | |* ja = 2 日语 |\
| | | | |* es = 3 西班牙语 |\
| | | | |* id = 4 印尼语 |\
| | | | |* pt = 5 葡萄牙语 |\
| | | | |* de = 6 德语 |\
| | | | |* fr = 7 法语 |
| | | | | | \
|speaker_id |1 |string |可选 |唯一音色代号 |
| | | | | | \
|status |\
| |1 |int |可选 |训练状态，状态为2或4时都可以调用tts |\
| | | | | |\
| | | | |* NotFound = 0 |\
| | | | |* Training = 1  |\
| | | | |* Success = 2  |\
| | | | |* Failed = 3 |\
| | | | |* Active = 4 |
| | | | | | \
|speaker_status |1 |object list |可选 |音色训练状态列表 |
| | | | | | \
|model_type |2 |int |\
| | | |可选 |\
| | | | |* 1 为声音复刻ICL 1.0效果 |\
| | | | |* 2 为DiT标准版效果（音色、不还原用户的风格） |\
| | | | |* 3 为DiT还原版效果（音色、还原用户口音、语速等风格） |\
| | | | |* 4 为声音复刻ICL 2.0效果 |
| | | | | | \
|demo_audio |2 |string |可选 |Success状态时返回，一小时有效，若需要，请下载后使用 |

<span id="dc8a6a0b"></span>
## 返回示例
```JSON
{
  "available_training_times": 15,
  "create_time": 1772026663000,
  "language": 0,
  "speaker_id": "S_*******",
  "speaker_status": [
    {
      "demo_audio": "https://x.bytespeech.com/S_*******",
      "model_type": 1
    },
    {
      "demo_audio": "https://x.bytespeech.com/S_*******",
      "model_type": 4
    }
  ],
  "status": 2
}
```

<span id="b68e8725"></span>
# 错误码
您在调用API接口过程中，如果服务端返回结果报错，则表示操作失败。您可以通过返回结果中的错误码快速地定位问题，并根据对应的解决方案尝试修改代码或者反馈给终端用户加以解决。

| | | | | | \
|**参数名称** |**层级** |**参数类型** |**是否必须** |**备注** |
|---|---|---|---|---|
| | | | | | \
|code |1 |int |可选 |训练失败时候HTTP返回非200，该字段返回详细错误码 |
| | | | | | \
|message |1 |string |可选 |训练失败时候HTTP返回非200，该字段返回详细错误信息 |


| | | \
|**错误码分类** |**错误码表示** |
|---|---|
| | | \
|服务端报错 |8位错误码，以5开头，例如：50001201 |
| | | \
|客户操作错误导致的服务端报错 |8位错误码，以4开头，例如：40001101 |


| | | | | \
|**错误码code** |**状态信息message** |**原因** |**解决方案** |
|---|---|---|---|
| | | | | \
|45001001 |请求参数有误 |参数缺失/格式不对/不符合约束 |按接口校验规则修正参数；补齐必填字段；检查枚举值 |
| | | | | \
|45001101 |音频上传失败 |客户端上传到服务端失败/超时/网络问题 |重试上传；检查网络与超时；确认音频格式与大小满足限制 |
| | | | | \
|45001102 |ASR转写失败 |ASR 服务失败/超时/音频质量差导致无法转写 |重试；确认音频可识别（清晰、人声占比高）；必要时更换音频 |
| | | | | \
|45001104 |声纹检测未通过 |触发敏感声纹/黑名单/相似度过高 |更换音频或更换说话人；避免使用敏感或疑似复刻目标音色的素材 |
| | | | | \
|45001105 |获取音频数据失败 |音频数据解码失败/下载失败/数据为空（如 base64 解码失败） |确认音频字段不为空；base64 是否合法；若是 URL 确认可访问；必要时重新上传 |
| | | | | \
|45001107 |SpeakerID未找到 |speaker_id 不存在/已被删除 |确认 speaker_id 正确；先查询列表；如已删除则重新创建 |
| | | | | \
|45001108 |音频转码失败 |输入音频格式不支持/数据损坏/转码工具失败 |确认音频格式与采样率；提供可解码音频；重试或更换音频 |
| | | | | \
|45001109 |wer检测错误 |WER 检测服务异常/输入不符合要求 |重试；检查prompt音频和提供的prompt文本是否对应 |
| | | | | \
|45001110 |音色删除失败 |删除流程失败/服务端异常/资源不存在 |重试；确认 speaker_id 存在 |
| | | | | \
|45001112 |SNR检测错误 |SNR 检测服务异常 |重试；更换音频（更高信噪比）；检查音频采样率/格式 |
| | | | | \
|45001113 |降噪失败 |降噪服务异常/参数不支持/音频不适配 |重试；关闭降噪参数或换模型；更换音频 |
| | | | | \
|45001114 |音频质量较差 |音频质量差/背景噪声大/人声过弱 |建议更换音频 |
| | | | | \
|45001122 |asr未检测到人声 |音频无人声/人声过弱/噪声过大 |更换含清晰人声的音频；提高人声占比；减少背景噪声 |
| | | | | \
|45001123 |达到上传次数上限 |超过音色训练次数限制 |更换为还有训练次数的 speaker_id |
| | | | | \
|45001124 |asr文本审核拒绝 |ASR 识别文本触发审核策略 |更换音频内容；避免敏感内容；必要时走白名单/审核申诉流程 |
| | | | | \
|45001125 |demo文本审核拒绝 |demo 文本触发审核策略 |修改 demo 文本；避免敏感词；按合规要求调整 |
| | | | | \
|45001126 |demo文本长度错误 |demo 文本太短/太长/超出限制 |按长度限制调整文本；去掉多余字符或补充内容 |
| | | | | \
|45001127 |prompt音频审核拒绝 |prompt 音频触发审核策略 |更换音频；避免敏感内容/违规素材；确保音频来源合规 |
| | | | | \
|45001128 |prompt音频文本审核拒绝 |prompt 音频对应文本/识别结果触发审核 |更换音频或文本；避免敏感内容；必要时走白名单 |
| | | | | \
|55001301 |数据库查询失败 |DB 不可用/超时 |服务异常、可能需要重试 |
| | | | | \
|55001302 |数据库插入失败 |DB 不可用/超时 |服务异常、可能需要重试 |
| | | | | \
|55001303 |数据库更新失败 |DB 不可用/超时 |服务异常、可能需要重试 |
| | | | | \
|55001304 |数据库删除失败 |DB 不可用/超时 |服务异常、可能需要重试 |
| | | | | \
|55001305 |TOS上传失败 |对象存储不可用/超时 |服务异常、可能需要重试 |
| | | | | \
|55001306 |TOS下载失败 |对象存储不可用/超时 |服务异常、可能需要重试 |
| | | | | \
|55001307 |音色克隆失败 |voice clone 下游失败/超时/返回异常 |服务异常、可能需要重试 |

<span id="caf9cc55"></span>
# V1训练接口迁移指南

| | | | \
|**参数字段变化** |**参数类型变化** |**备注** |
|---|---|---|
| | | | \
|audios变更为audio |[]object变更为object |老接口为数组但是只支持一个音频文件，新接口变更为单个文件 |
| | | | \
|audios[].audio_bytes变更为audio.data |string |字段定义不变，二进制音频字节，需对二进制音频进行base64编码 |
| | | | \
|audios[].audio_format变更为audio.format |string |字段定义不变，音频格式，pcm、m4a必传，其余可选 |
| | | | \
|model_type变更为model_types |int变更为[]int |\
| | |除了需要使用DiT效果以外不需要指定 |\
| | |2 为DiT标准版效果（音色、不还原用户的风格） |\
| | |3 为DiT还原版效果（音色、还原用户口音、语速等风格） |
| | | | \
|extra_params |jsonstring变更为object |简化使用 |

<span id="be6caddf"></span>
# TTS 语音合成接口
音色训练成功后，需要通过调用TTS语音合成接口来使用音色合成指定文本的音频。

| | | | | \
|**接口** |**推荐场景** |**接口功能** |**文档链接** |
|---|---|---|---|
| | | | | \
|`wss://openspeech.bytedance.com/api/v3/tts/bidirection ` |WebSocket协议，实时交互场景，支持文本实时流式输入，流式输出音频。 |语音合成、**声音复刻**、混音 |[V3 WebSocket双向流式文档](https://www.volcengine.com/docs/6561/1329505) |
| | | | | \
|`wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream` |WebSocket协议，一次性输入合成文本，流式输出音频。 |语音合成、**声音复刻**、混音 |[V3 WebSocket单向流式文档](https://www.volcengine.com/docs/6561/1719100) |
| | | | | \
|`https://openspeech.bytedance.com/api/v3/tts/unidirectional ` |HTTP Chunked协议，一次性输入全部合成文本，流式输出音频。 |语音合成、声音复刻、混音 |[V3 HTTP Chunked单向流式文档](https://www.volcengine.com/docs/6561/1598757?lang=zh#_2-http-chunked%E6%A0%BC%E5%BC%8F%E6%8E%A5%E5%8F%A3%E8%AF%B4%E6%98%8E) |
| | | | | \
|`https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse` |HTTP SSE协议，一次性输入全部合成文本，流式输出音频。 |语音合成、声音复刻、混音 |[V3 Server Sent Events（SSE）单向流式文档](https://www.volcengine.com/docs/6561/1598757?lang=zh#_3-sse%E6%A0%BC%E5%BC%8F%E6%8E%A5%E5%8F%A3%E8%AF%B4%E6%98%8E) |


