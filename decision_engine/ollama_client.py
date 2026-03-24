"""
decision_engine/ollama_client.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 6 — Ollama LLM Client

Handles all communication with local Ollama instance.
Sends structured prompts, parses JSON responses.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import sys
sys.path.insert(0, ".")

import httpx
from loguru import logger
from config import ollama as ollama_cfg

TIMEOUT     = 120
MAX_RETRIES = 3


def is_available() -> bool:
    try:
        r = httpx.get(f"{ollama_cfg.url}/api/tags", timeout=5)
        models = r.json().get("models", [])
        if not models:
            logger.warning("Ollama running but no models — run: ollama pull llama3")
            return False
        logger.info(f"Ollama OK — models: {[m['name'] for m in models]}")
        return True
    except Exception as e:
        logger.error(f"Ollama not reachable: {e}")
        return False


def ask(prompt: str, system: str | None = None) -> str | None:
    """
    Send prompt using /api/generate (more compatible than /api/chat).
    Combines system + prompt into single string for compatibility.
    """
    full_prompt = f"{system}\n\n{prompt}" if system else prompt

    payload = {
        "model":  ollama_cfg.MODEL,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "top_p":       0.9,
            "num_predict": 1024,   # limit output tokens
        },
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = httpx.post(
                f"{ollama_cfg.url}/api/generate",
                json=payload,
                timeout=TIMEOUT,
            )
            if r.status_code != 200:
                logger.error(f"Ollama HTTP {r.status_code}: {r.text[:300]}")
                continue
            content = r.json().get("response", "").strip()
            return content
        except httpx.TimeoutException:
            logger.warning(f"Ollama timeout (attempt {attempt}/{MAX_RETRIES})")
        except Exception as e:
            logger.error(f"Ollama request failed (attempt {attempt}): {e}")

    return None


def ask_json(prompt: str, system: str | None = None) -> dict | None:
    """Send prompt and parse response as JSON."""
    response = ask(prompt, system)
    if not response:
        return None

    logger.debug(f"Ollama raw response: {response[:300]}")

    # Strip markdown fences
    clean = response
    if "```json" in clean:
        clean = clean.split("```json")[1].split("```")[0]
    elif "```" in clean:
        clean = clean.split("```")[1].split("```")[0]

    # Find JSON object — try multiple times with progressively smaller substrings
    start = clean.find("{")
    if start == -1:
        logger.error(f"No JSON in response: {response[:300]}")
        return None

    # Try to find valid JSON by scanning for matching closing brace
    for end in range(len(clean), start, -1):
        substr = clean[start:end]
        if not substr.endswith("}"):
            continue
        try:
            return json.loads(substr)
        except json.JSONDecodeError:
            continue

    logger.error(f"JSON parse failed after scan: {clean[start:start+200]}")
    return None