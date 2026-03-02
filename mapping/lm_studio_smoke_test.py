#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LM Studio 本地推理服务冒烟测试

用途：验证本机 LM Studio 服务（默认 http://127.0.0.1:1234）可达，
     且已加载模型，并能完成一次简单对话。

使用前：
  1. 在 LM Studio 中启动 Local Inference Server（Status: Running）
  2. 加载一个模型（⌘L 或 + Load Model）

运行：
  python mapping/lm_studio_smoke_test.py

可选环境变量：
  LM_STUDIO_BASE_URL  默认 http://127.0.0.1:1234
  LM_API_TOKEN        若 LM Studio 启用了认证，设置此变量
"""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:1234"
SMOKE_PROMPT = "你好，请只回复一句：冒烟测试通过。"


def get_base_url() -> str:
    return os.environ.get("LM_STUDIO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def get_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("LM_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_models(base_url: str) -> list:
    """GET /api/v1/models，返回 models 数组。"""
    url = f"{base_url}/api/v1/models"
    req = Request(url, headers=get_headers(), method="GET")
    with urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    return data.get("models") or []


def get_loaded_llm_key(models: list) -> str | None:
    """从 models 中取主用 LLM 的 key。

    优先选择「非 Flash」模型，若仅有 Flash 已加载，则退而选 Flash。
    这样可以在同时加载标准版和 Flash 版时，将标准版作为主模型使用。
    """
    primary: str | None = None
    flash: str | None = None
    for m in models:
        if m.get("type") != "llm":
            continue
        if not m.get("loaded_instances"):
            continue
        key = m.get("key") or ""
        if "flash" in key.lower():
            if flash is None:
                flash = key
        else:
            if primary is None:
                primary = key
    return primary or flash


def get_flash_llm_key(models: list) -> str | None:
    """从 models 中取第一个已加载的 Flash LLM 的 key（key 中包含 'flash'）。"""
    for m in models:
        if m.get("type") != "llm":
            continue
        if not m.get("loaded_instances"):
            continue
        key = m.get("key") or ""
        if "flash" in key.lower():
            return key
    return None


def get_qwen_tag_llm_key(models: list) -> str | None:
    """从 models 中取用于标签选择的 Qwen 模型 key。

    优先匹配名字中同时包含 'qwen'、'7b'、'instruct' 的模型，
    若未找到则退而求其次选择第一个包含 'qwen' 的已加载 LLM。
    """
    candidate: str | None = None
    fallback: str | None = None
    for m in models:
        if m.get("type") != "llm":
            continue
        if not m.get("loaded_instances"):
            continue
        key = (m.get("key") or "").lower()
        if "qwen" not in key:
            continue
        if fallback is None:
            fallback = m.get("key")
        if "7b" in key and "instruct" in key:
            candidate = m.get("key")
            break
    return candidate or fallback


def chat(
    base_url: str,
    model_key: str,
    user_input: str,
    *,
    system_prompt: str | None = None,
    timeout: int = 60,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    reasoning: str | None = None,
) -> str:
    """POST /api/v1/chat，返回模型回复的文本内容。
    reasoning: 设为 "off" 可关闭推理链输出，避免长思考导致超时或死循环。
    """
    url = f"{base_url}/api/v1/chat"
    body = {
        "model": model_key,
        "input": user_input,
        "store": False,
    }
    if system_prompt is not None:
        body["system_prompt"] = system_prompt
    if temperature is not None:
        body["temperature"] = float(temperature)
    if max_output_tokens is not None:
        body["max_output_tokens"] = int(max_output_tokens)
    if reasoning is not None:
        body["reasoning"] = reasoning
    req = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=get_headers(),
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())

    # 从 output 数组中取 type=="message" 的 content 拼接
    output = data.get("output") or []
    parts = []
    for item in output:
        if isinstance(item, dict) and item.get("type") == "message":
            content = item.get("content")
            if isinstance(content, str):
                parts.append(content.strip())
    return "\n".join(parts).strip() if parts else ""


def main() -> int:
    base_url = get_base_url()
    print(f"LM Studio 基地址: {base_url}", flush=True)
    print("1. 获取已加载模型...", flush=True)

    try:
        models = fetch_models(base_url)
    except URLError as e:
        print(f"   失败: 无法连接 {base_url}，请确认 LM Studio 本地服务已启动。", file=sys.stderr)
        if getattr(e, "reason", None):
            print(f"   原因: {e.reason}", file=sys.stderr)
        return 1
    except HTTPError as e:
        print(f"   失败: HTTP {e.code}", file=sys.stderr)
        if e.fp:
            try:
                body = e.fp.read().decode()
                print(f"   响应: {body[:200]}", file=sys.stderr)
            except Exception:
                pass
        return 1
    except Exception as e:
        print(f"   失败: {e}", file=sys.stderr)
        return 1

    model_key = get_loaded_llm_key(models)
    if not model_key:
        print("   未发现已加载的 LLM。请在 LM Studio 中加载一个模型（⌘L 或 + Load Model）后再试。", file=sys.stderr)
        return 1
    print(f"   使用模型: {model_key}", flush=True)

    print("2. 发送对话请求...", flush=True)
    try:
        reply = chat(base_url, model_key, SMOKE_PROMPT)
    except URLError as e:
        print(f"   失败: {e}", file=sys.stderr)
        return 1
    except HTTPError as e:
        print(f"   失败: HTTP {e.code}", file=sys.stderr)
        try:
            body = e.read().decode()
            print(f"   响应: {body[:300]}", file=sys.stderr)
        except Exception:
            pass
        return 1
    except Exception as e:
        print(f"   失败: {e}", file=sys.stderr)
        return 1

    if not reply:
        print("   失败: 未得到模型文本回复（output 中无 type=message 或 content 为空）。", file=sys.stderr)
        return 1

    print("3. 收到模型回复:")
    print("   ---")
    print(f"   {reply}")
    print("   ---")
    print("冒烟测试通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
