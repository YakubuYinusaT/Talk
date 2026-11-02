"""A stand-in for the language and speech models: the same HTTP contracts as the hosted services, answering by simple rules.

Run standalone:  uvicorn mocks.model_mock:app --port 9000
or in-process:   LLM_URL=inprocess://mock (the default)

"Audio" for the stand-in speech recogniser is UTF-8 text shaped like  MOCK[en]:<what the caller said>.  The voice makes silence of the right length.
"""

import io
import json
import re
import wave

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import Response

from .rules import guide_answer, meaning, understand, wording

app = FastAPI(title="Talk model stand-in")

MOCK_AUDIO = re.compile(rb"^MOCK\[(\w\w)\]:(.*)$", re.S)


@app.get("/health")
def health():
    return {"ok": True, "mock": True}


@app.post("/v1/asr/transcribe")
async def transcribe(audio: UploadFile = File(...), request: str = Form("{}")):
    """Speech to text, in the shape of Muse Voice Transcribe: the words of a MOCK[en]:... recording, and nothing for any other audio."""
    heard = MOCK_AUDIO.match(await audio.read())
    return {"transcript": " ".join(heard.group(2).decode("utf-8").split()) if heard else ""}


@app.post("/v1/speech")
async def speech(request: Request):
    """Silence a third of a second long for every word of the text."""
    body = await request.json()
    words = max(1, len(str(body.get("text", "")).split()))
    rate, seconds = 8000, min(12.0, 0.35 * words)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return Response(buf.getvalue(), media_type="audio/wav", headers={"X-Mock": "1"})


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    if system.startswith("UNDERSTAND"):
        content = json.dumps(understand(system, user))
    elif system.startswith("ANSWER"):
        content = json.dumps({"say": guide_answer(system)})
    elif system.startswith("REPLY"):
        content = json.dumps(meaning(user))
    elif system.startswith("WORDING"):
        content = json.dumps(wording(system))
    else:  # ARGUMENTS, CHOICE: the stand-in fills in nothing, so the service asks for each detail; tests that need a filled-in answer replace the extraction
        content = "{}"
    return {
        "id": "mock",
        "object": "chat.completion",
        "model": body.get("model", "mock"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }
