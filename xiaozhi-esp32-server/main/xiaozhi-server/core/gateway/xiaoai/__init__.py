"""G19i：宗主后端直接接小米音箱（音箱上跑 open-xiaoai Client）；以前要经过电脑上单独运行的 xiaoai-bridge。

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

各文件：
- protocol.py：和音箱上 Client 的连接协议；按 4 声道录音（3 个麦克风 + 音箱自己放出的声音）
- server.py：开 4399 端口接音箱，连上后放一声提示音；认出唤醒词回"在"
- wake.py：唤醒词识别（sherpa-onnx，模型下载见 docs/GUIDE.md"接入小米智能音箱 Pro"）
- prompts.py："在"用后端的 TTS 合成一次存着
- device.py：唤醒后当成一块板子接进后端（识别、网关、TTS 照用），打断、等音箱放完再听
- debug.py：排查用：录麦克风（debug_dir）、放测试音（debug_probe）、在音箱上跑只读命令（debug_inspect）；
  录音里有你说的话，查完要关
"""
