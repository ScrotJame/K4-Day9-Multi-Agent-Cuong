"""
LLM API client — hỗ trợ Mistral AI và NVIDIA NIM (với fallback tự động).
"""

import json
import time
import requests
from . import config


def call_mistral(model: str, system: str, user: str, temperature: float = 0.1) -> dict:
    """Gọi Mistral API cho Coordinator / Domain agents."""
    return _call_openai_compatible(
        api_url=config.MISTRAL_API_URL,
        api_key=config.MISTRAL_API_KEY,
        model=model,
        system=system,
        user=user,
        temperature=temperature,
        timeout=15,
    )


def call_nvidia(model: str, system: str, user: str, temperature: float = 0.1) -> dict:
    """Gọi NVIDIA NIM API cho Verifier agent. Tự động fallback sang Mistral nếu NVIDIA timeout."""
    api_url = config.NVIDIA_BASE_URL.rstrip("/") + "/chat/completions"
    api_key = config.NVIDIA_API_KEY_1 or config.NVIDIA_API_KEY_2
    res = _call_openai_compatible(
        api_url=api_url,
        api_key=api_key,
        model=model,
        system=system,
        user=user,
        temperature=temperature,
        timeout=5,
        max_retries=1,
    )
    if not res.get("success"):
        # Fallback sang Mistral nếu NVIDIA API bị timeout/unreachable
        return call_mistral("ministral-3b-2512", system, user, temperature)
    return res


def _call_openai_compatible(
    api_url: str, api_key: str, model: str,
    system: str, user: str, temperature: float = 0.1,
    timeout: int = 15, max_retries: int = 2,
) -> dict:
    """Gọi API dạng OpenAI-compatible, parse JSON output, có retry."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": 1024,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_err = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                api_url, headers=headers, json=payload,
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return {"success": True, "content": content, "parsed": _safe_json_parse(content)}
        except Exception as e:
            last_err = e
            time.sleep(1 * (attempt + 1))

    return {"success": False, "error": str(last_err), "parsed": {}}


def _safe_json_parse(text: str) -> dict:
    """Parse JSON từ LLM output, xử lý markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return {"raw_text": text[:500]}
