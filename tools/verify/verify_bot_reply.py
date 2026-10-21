"""Real Bot round trip; sends one harmless task and waits for display text."""
import asyncio
import json
import time
import uuid
from pathlib import Path

import httpx
import opuslib_next
import websockets

ROOT = Path(__file__).resolve().parents[2]  # 仓库根目录


async def main():
    marker = 'RETURN-' + uuid.uuid4().hex[:10]
    prompt = '请回复：宗主已收到你的对话，回传编号' + marker + '。这是回传测试，除约定的回传文件外不要修改文件，也不要执行其他任务。'
    headers = {'Device-Id': '02:00:00:00:00:04', 'Client-Id': 'zongzhu-reply-check'}
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.post('http://127.0.0.1:8003/xiaozhi/ota/', headers=headers,
                                     json={'application': {'version': '2.5.2.2'}, 'board': {'type': 'local-test'}})
        response.raise_for_status()
        headers['Authorization'] = 'Bearer ' + response.json()['websocket']['token']
    async with websockets.connect('ws://127.0.0.1:8000/xiaozhi/v1/', additional_headers=headers) as ws:
        await ws.send(json.dumps({'type': 'hello', 'version': 1, 'transport': 'websocket',
                                 'audio_params': {'format': 'opus', 'sample_rate': 16000, 'channels': 1, 'frame_duration': 60}}))
        assert json.loads(await asyncio.wait_for(ws.recv(), 20))['type'] == 'hello'
        await asyncio.sleep(2)
        await ws.send(json.dumps({'type': 'listen', 'state': 'detect', 'text': prompt}))
        started = time.monotonic()
        encoder = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_AUDIO)
        silent_packet = encoder.encode(bytes(1920), 960)
        async def silence():
            # Exercise the normal audio handler, including wake/VAD resume.
            for _ in range(70):
                await ws.send(silent_packet)
                await asyncio.sleep(.06)
        audio_task = asyncio.create_task(silence())
        report = {'marker': marker, 'hardware_screen_test': False, 'ack_text': [], 'audio_packets': 0}
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), max(.1, 180 - (time.monotonic() - started)))
                if isinstance(raw, bytes):
                    report['audio_packets'] += 1
                    continue
                data = json.loads(raw)
                if data.get('type') == 'tts' and data.get('text'):
                    if data.get('request_id') and marker in data['text']:
                        report.update({'request_id': data['request_id'], 'display_text': data['text'],
                                       'elapsed_seconds': round(time.monotonic() - started, 2)})
                        break
                    report['ack_text'].append(data['text'])
            assert '任务已提交' in ''.join(report['ack_text'])
            assert report['audio_packets'] > 0
            (ROOT/'logs/bot-reply-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            await audio_task


if __name__ == '__main__':
    asyncio.run(main())
