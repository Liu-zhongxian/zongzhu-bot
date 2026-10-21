"""Real Bot round trip; verifies reply subtitles and decoded speech audio."""
import asyncio
import json
import time
import uuid
import wave
import array
from pathlib import Path

import httpx
import opuslib_next
import websockets

ROOT = Path(__file__).resolve().parent


async def main():
    marker = 'SPEECH-' + uuid.uuid4().hex[:10]
    prompt = '请回复：宗主朗读测试成功，我现在可以把回复读给你听。测试编号' + marker + '。这是回传测试，除约定的回传文件外不要修改文件，也不要执行其他任务。'
    headers = {'Device-Id': '02:00:00:00:00:06', 'Client-Id': 'zongzhu-speech-check'}
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
        report = {'marker': marker, 'hardware_speaker_test': False, 'ack_text': [], 'reply_subtitles': [], 'audio_packets': 0, 'reply_audio_packets': 0}
        decoder = opuslib_next.Decoder(16000, 1)
        pcm = bytearray()
        replying = False
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), max(.1, 300 - (time.monotonic() - started)))
                if isinstance(raw, bytes):
                    report['audio_packets'] += 1
                    if replying:
                        report['reply_audio_packets'] += 1
                        pcm.extend(decoder.decode(raw, 960))
                    continue
                data = json.loads(raw)
                if data.get('type') != 'tts':
                    continue
                if data.get('state') == 'start' and data.get('request_id'):
                    replying = True
                    report['request_id'] = data['request_id']
                if data.get('text'):
                    if replying:
                        report['reply_subtitles'].append(data['text'])
                    else:
                        report['ack_text'].append(data['text'])
                if replying and data.get('state') == 'stop':
                    report['elapsed_seconds'] = round(time.monotonic() - started, 2)
                    break
            assert '任务已提交' in ''.join(report['ack_text'])
            assert report['reply_audio_packets'] > 0, report
            assert marker in ''.join(report['reply_subtitles']), report
            samples = array.array('h', pcm)
            report['pcm_peak'] = max(abs(n) for n in samples)
            report['reply_audio_seconds'] = round(len(samples) / 16000, 2)
            assert report['pcm_peak'] > 100, report
            with wave.open(str(ROOT/'logs/bot-reply-speech.wav'), 'wb') as wav:
                wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                wav.writeframes(pcm)
            (ROOT/'logs/bot-speech-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            await audio_task


if __name__ == '__main__':
    asyncio.run(main())
