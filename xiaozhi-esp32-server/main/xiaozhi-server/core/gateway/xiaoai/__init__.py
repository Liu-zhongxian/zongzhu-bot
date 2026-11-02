"""G19i：宗主后端直接接小米音箱（音箱上跑 open-xiaoai Client），不再经过 xiaoai-bridge。

配置（.config.yaml，默认关）：

    gateway:
      xiaoai:
        enabled: true
        port: 4399                                   # 音箱 /data/open-xiaoai/server.txt 里写的端口
        token_file: ../../../private/open-xiaoai-token.txt   # 和音箱上 /data/open-xiaoai/token.txt 一样
        wake_words: [你好宗主, 宗主你好]              # 可选
        kws_model_dir: models/sherpa-onnx-kws-open-xiaoai   # 可选，唤醒词模型
        kws_threshold: 0.05                           # 可选，越低越容易唤醒
        device_id: "aa:bb:cc:dd:ee:ff"               # 可选，网关页面上的设备号，不配用 xiaoai-<音箱 IP>

第 1 步通声音（连上后放一声提示音、头 15 秒在日志里报麦克风音量）；第 2 步认唤醒词、回"在"；
第 3 步唤醒后当成一块板子和后端对话（device.py）。
后面几步见 docs/records/GATEWAY-TASKS.md G19i。排查声音问题用 debug.py（录麦克风、放测试音）。
"""
