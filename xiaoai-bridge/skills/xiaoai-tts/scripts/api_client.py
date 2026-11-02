#!/usr/bin/env python3
"""
OpenXiaoAI API 配置和基础工具
"""

import os
import json
import urllib.request
import urllib.error


def get_api_config():
    """获取 API 配置"""
    base_url = os.environ.get("OPENXIAOAI_BASE_URL", "http://192.168.3.6:9092")
    # 移除末尾的斜杠
    return base_url.rstrip("/")


def api_request(path, method="GET", data=None, headers=None):
    """发送 API 请求"""
    base_url = get_api_config()
    full_url = f"{base_url}{path}"
    
    default_headers = {
        "Content-Type": "application/json"
    }
    if headers:
        default_headers.update(headers)
    
    req = urllib.request.Request(
        full_url,
        headers=default_headers,
        method=method
    )
    
    if data:
        req.data = json.dumps(data).encode("utf-8")
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_msg = f"HTTP 错误: {e.code} - {e.reason}"
        try:
            error_body = json.loads(e.read().decode("utf-8"))
            error_msg += f"\n详情: {error_body}"
        except:
            pass
        raise Exception(error_msg)
    except Exception as e:
        raise Exception(f"请求失败: {e}")


def check_health():
    """检查服务健康状态"""
    return api_request("/api/health")


def get_status():
    """获取音箱状态"""
    return api_request("/api/status")


def wakeup(silent=True):
    """唤醒小爱"""
    return api_request("/api/wakeup", method="POST", data={"silent": silent})


def interrupt():
    """打断当前播放"""
    return api_request("/api/interrupt", method="POST")
