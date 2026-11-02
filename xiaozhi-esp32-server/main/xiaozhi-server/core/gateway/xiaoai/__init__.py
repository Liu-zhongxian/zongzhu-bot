"""G19i：宗主后端直接接小米音箱（音箱上跑 open-xiaoai Client），不再经过 xiaoai-bridge。

配置（.config.yaml，默认关）：

    gateway:
      xiaoai:
        enabled: true
        port: 4399                                   # 音箱 /data/open-xiaoai/server.txt 里写的端口
        token_file: ../../../private/open-xiaoai-token.txt   # 和音箱上 /data/open-xiaoai/token.txt 一样

第 1 步只通声音：音箱连上后放两声提示音，之后 15 秒在日志里报麦克风音量。
唤醒、对话在后面几步（docs/records/GATEWAY-TASKS.md G19i）。
"""
