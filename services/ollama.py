import httpx
import json
import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "https://ollama.com/v1/chat/completions")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")

HEADERS = {"Content-Type": "application/json"}
if OLLAMA_API_KEY:
    HEADERS["Authorization"] = f"Bearer {OLLAMA_API_KEY}"


async def generate_response(message: str) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            OLLAMA_URL,
            headers=HEADERS,
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": message}],
                "stream": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def stream_response(message: str):
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            OLLAMA_URL,
            headers=HEADERS,
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": message}],
                "stream": True,
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                    delta = data["choices"][0]["delta"].get("content")
                    if delta:
                        yield delta
                except Exception:
                    continue