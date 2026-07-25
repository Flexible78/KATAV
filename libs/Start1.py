import os
import re
import json
import uuid
import asyncio
import logging
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import uvicorn
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest

app = FastAPI()

# ── Настройки ──────────────────────────────────────────────────────────────────
GEMINI_DIR = os.path.expanduser("~/.gemini")          
TOKEN_FILE_PATH = os.path.join(GEMINI_DIR, "oauth_creds.json")
GEMINI_CLI_VERSION = "0.40.0"                          
HOST = "127.0.0.1"
PORT = 8080

def _load_gemini_cli_oauth():
    """Try to read CLIENT_ID/SECRET from Gemini CLI bundle automatically by searching chunk files."""
    try:
        import glob as _glob
        possible_dirs = [
            os.path.join(os.environ.get("APPDATA", ""), "npm/node_modules/@google/gemini-cli/bundle"),
            os.path.join(os.environ.get("APPDATA", ""), r"npm\node_modules\@google\gemini-cli\bundle"),
            "/usr/local/lib/node_modules/@google/gemini-cli/bundle",
            "/usr/lib/node_modules/@google/gemini-cli/bundle",
        ]
        home = os.path.expanduser("~")
        possible_dirs.extend([
            os.path.join(home, ".nvm/versions/node/*/lib/node_modules/@google/gemini-cli/bundle"),
            os.path.join(home, ".config/nvm/versions/node/*/lib/node_modules/@google/gemini-cli/bundle"),
        ])

        for base_dir in possible_dirs:
            for bundle_path in _glob.glob(os.path.join(base_dir, "chunk-*.js")):
                try:
                    with open(bundle_path, encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        if "OAUTH_CLIENT_ID" in content:
                            cid = re.search(r'OAUTH_CLIENT_ID\s*=\s*"([^"]+)"', content)
                            sec = re.search(r'OAUTH_CLIENT_SECRET\s*=\s*"([^"]+)"', content)
                            if cid and sec:
                                return cid.group(1), sec.group(1)
                except Exception:
                    continue
    except Exception:
        pass
    return None, None

_auto_id, _auto_secret = _load_gemini_cli_oauth()
if not _auto_id or not _auto_secret:
    raise RuntimeError(
        "Не удалось найти CLIENT_ID/SECRET в бандле Gemini CLI. "
        "Убедитесь что Gemini CLI установлен (npm install -g @google/gemini-cli)."
    )
CLIENT_ID     = _auto_id
CLIENT_SECRET = _auto_secret

CODE_ASSIST_BASE = "https://cloudcode-pa.googleapis.com/v1internal"

_dir = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(_dir, "proxy.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("proxy")

project_id_cache = None
project_id_lock = asyncio.Lock()
result_cache: dict = {}  
thought_sig_store: dict = {}  
THOUGHT_SIG_FILE = os.path.join(_dir, "thought_sigs.json")

def load_thought_sigs():
    global thought_sig_store
    try:
        with open(THOUGHT_SIG_FILE, "r", encoding="utf-8") as f:
            thought_sig_store = json.load(f)
    except Exception:
        thought_sig_store = {}

def save_thought_sigs():
    with open(THOUGHT_SIG_FILE, "w", encoding="utf-8") as f:
        json.dump(thought_sig_store, f)

def get_credentials():
    with open(TOKEN_FILE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    creds = Credentials(
        token=data.get("access_token"),
        refresh_token=data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=data.get("scope", "").split(),
    )
    if not creds.valid:
        log.info("Обновляем токен...")
        creds.refresh(GoogleRequest())
        data["access_token"] = creds.token
        with open(TOKEN_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        log.info("Токен обновлён")
    return creds

async def get_project_id(token: str) -> str:
    global project_id_cache
    if project_id_cache:
        return project_id_cache
    async with project_id_lock:
        if project_id_cache:
            return project_id_cache
        log.info("Получаем projectId через loadCodeAssist...")
        for attempt in range(2):
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{CODE_ASSIST_BASE}:loadCodeAssist",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"metadata": {"ideType": "IDE_UNSPECIFIED", "platform": "PLATFORM_UNSPECIFIED", "pluginType": "GEMINI"}},
                    timeout=30.0,
                )
                if resp.status_code == 401 and attempt == 0:
                    creds = get_credentials()
                    creds.refresh(GoogleRequest())
                    token = creds.token
                    with open(TOKEN_FILE_PATH, "r", encoding="utf-8") as f:
                        d = json.load(f)
                    d["access_token"] = token
                    with open(TOKEN_FILE_PATH, "w", encoding="utf-8") as f:
                        json.dump(d, f, indent=2)
                    continue
                resp.raise_for_status()
                result = resp.json()
                project_id_cache = result.get("cloudaicompanionProject") or result.get("projectId") or ""
                log.info("projectId: %s", project_id_cache)
                return project_id_cache
        raise Exception("Не удалось получить projectId")

# ── Format converters ──────────────────────────────────────────────────────────
ALLOWED_SCHEMA_KEYS = {"type", "properties", "required", "description", "items", "enum"}

def clean_schema(schema: dict) -> dict:
    if not isinstance(schema, dict):
        return schema
    result = {}
    for k, v in schema.items():
        if k not in ALLOWED_SCHEMA_KEYS: continue
        if k == "properties" and isinstance(v, dict):
            result[k] = {pk: clean_schema(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            result[k] = clean_schema(v)
        else:
            result[k] = v
    return result

def anthropic_tools_to_gemini(tools: list) -> list:
    result = []
    for t in tools:
        schema = clean_schema(t.get("input_schema", {}))
        result.append({
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": schema or {"type": "object", "properties": {}},
        })
    return result

def anthropic_messages_to_gemini(messages: list) -> list:
    contents = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        content = msg.get("content", "")

        if isinstance(content, str):
            text = re.sub(r"<system-reminder>.*?</system-reminder>", "", content, flags=re.DOTALL).strip()
            if text: contents.append({"role": role, "parts": [{"text": text}]})
            continue

        parts = []
        for block in content:
            btype = block.get("type")
            if btype == "text":
                text = re.sub(r"<system-reminder>.*?</system-reminder>", "", block.get("text", ""), flags=re.DOTALL).strip()
                if text: parts.append({"text": text})
            elif btype == "tool_use":
                sig = thought_sig_store.get(block.get("id", ""))
                if sig: parts.append({"thoughtSignature": sig, "functionCall": {"name": block["name"], "args": block.get("input", {})}})
                else: parts.append({"text": f"[Called tool: {block['name']}]"})
            elif btype == "tool_result":
                tool_id = block.get("tool_use_id", "")
                tool_content = block.get("content", "")
                if isinstance(tool_content, list):
                    tool_content = " ".join(b.get("text", "") for b in tool_content if b.get("type") == "text")
                if thought_sig_store.get(tool_id):
                    parts.append({"functionResponse": {"name": tool_id, "response": {"output": tool_content}}})
                else:
                    parts.append({"text": f"[Tool result: {tool_content}]"})

        if parts: contents.append({"role": role, "parts": parts})
    return contents

def gemini_response_to_anthropic(chunks: list) -> dict:
    text_parts = []
    tool_calls = []
    finish_reason = "end_turn"
    
    for chunk in chunks:
        inner = chunk.get("response", chunk)
        candidates = inner.get("candidates", [])
        if not candidates: continue
        candidate = candidates[0]
        
        parts = candidate.get("content", {}).get("parts", [])
        for part in parts:
            if "functionCall" in part:
                fc = part["functionCall"]
                tool_id = f"toolu_{uuid.uuid4().hex[:16]}"
                tool_calls.append({
                    "id": tool_id,
                    "name": fc.get("name", ""),
                    "args": fc.get("args", {}),
                    "thought_signature": part.get("thoughtSignature"),
                })
                finish_reason = "tool_use"
            elif "text" in part:
                text_parts.append(part["text"])

    content = []
    if text_parts: content.append({"type": "text", "text": "".join(text_parts)})
    for tc in tool_calls:
        content.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["args"]})

    return {
        "content": content,
        "stop_reason": finish_reason,
        "_thought_signatures": {tc["id"]: tc["thought_signature"] for tc in tool_calls if tc["thought_signature"]},
    }

# ── HTTP helpers ───────────────────────────────────────────────────────────────
async def gemini_post(token: str, project_id: str, gemini_model: str, payload: dict, fail_fast: bool = False) -> list:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": f"GeminiCLI/{GEMINI_CLI_VERSION}/{gemini_model} (win32; x64; cli)",
    }
    max_attempts = 2 if fail_fast else 5
    async with httpx.AsyncClient() as client:
        for attempt in range(max_attempts):
            log.info(f"[PROXY] Запрос к Google API | Модель: {gemini_model} | Попытка: {attempt+1}/{max_attempts}")
            response = await client.post(f"{CODE_ASSIST_BASE}:streamGenerateContent", headers=headers, json=payload, timeout=120.0)
            log.info(f"[PROXY] Ответ Google: HTTP {response.status_code}")
            if response.status_code == 401:
                log.warning("[PROXY] Токен истёк (401), обновляем...")
                with open(TOKEN_FILE_PATH, "r", encoding="utf-8") as f: cred_data = json.load(f)
                creds = Credentials(None, refresh_token=cred_data.get("refresh_token"), token_uri="https://oauth2.googleapis.com/token", client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
                creds.refresh(GoogleRequest())
                cred_data["access_token"] = creds.token
                with open(TOKEN_FILE_PATH, "w", encoding="utf-8") as f: json.dump(cred_data, f, indent=2)
                headers["Authorization"] = f"Bearer {creds.token}"
                log.info("[PROXY] Токен обновлён, повторяем запрос...")
                continue
            if response.status_code == 429:
                if fail_fast:
                    log.warning("[PROXY] 429 Rate Limit (fail_fast=True) — возвращаем ошибку клиенту")
                    raise Exception("429_RATE_LIMIT: Google API лимит исчерпан. Подождите и повторите.")
                wait = 60
                m = re.search(r"reset after (\d+)s", response.text)
                if m: wait = int(m.group(1)) + 1
                log.warning(f"[PROXY] 429 Rate Limit — ждём {wait}с перед повтором")
                await asyncio.sleep(wait)
                continue
            response.raise_for_status()
            chunks = json.loads(response.text)
            if not isinstance(chunks, list): chunks = [chunks]
            log.info(f"[PROXY] ✅ Ответ получен ({len(chunks)} чанков)")
            return chunks
    raise Exception("Превышено число попыток после 429")

# ── Генератор стриминга для VS Code ───────────────────────────────────────────
async def gemini_stream_to_anthropic(token: str, project_id: str, gemini_model: str, payload: dict, requested_model: str):
    """Преобразует потоковый ответ от Gemini в формат Anthropic (посимвольно)."""
    msg_id = f"msg_{uuid.uuid4().hex[:16]}"
    
    # 1. Отправляем стартовый блок с обязательными input_tokens
    msg_start = {
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "model": requested_model,
            "usage": {"input_tokens": 150} # <-- Вот фикс для твоей ошибки в Continue!
        }
    }
    yield f"event: message_start\ndata: {json.dumps(msg_start)}\n\n"
    
    cbs = {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
    yield f"event: content_block_start\ndata: {json.dumps(cbs)}\n\n"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": f"GeminiCLI/{GEMINI_CLI_VERSION}/{gemini_model} (win32; x64; cli)",
    }
    
    url = f"{CODE_ASSIST_BASE}:streamGenerateContent?alt=sse"
    output_tokens = 0
    
    # 2. Читаем поток из Google и отдаем в VS Code
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream("POST", url, headers=headers, json=payload, timeout=120.0) as response:
                if response.status_code != 200:
                    err = {"type": "error", "error": {"type": "api_error", "message": f"Gemini API Error: {response.status_code}"}}
                    yield f"event: error\ndata: {json.dumps(err)}\n\n"
                    return

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            data_chunk = json.loads(line[6:])
                            if isinstance(data_chunk, list): data_chunk = data_chunk[0]
                            
                            candidates = data_chunk.get("response", data_chunk).get("candidates", [])
                            if not candidates: continue
                            
                            parts = candidates[0].get("content", {}).get("parts", [])
                            for part in parts:
                                if "text" in part:
                                    text_val = part["text"]
                                    output_tokens += 1
                                    delta = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text_val}}
                                    yield f"event: content_block_delta\ndata: {json.dumps(delta)}\n\n"
                        except Exception: pass
        except Exception as e:
            log.error(f"Сбой стрима: {e}")

    # 3. Закрываем поток
    yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"
    msg_delta = {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": output_tokens if output_tokens > 0 else 50}}
    yield f"event: message_delta\ndata: {json.dumps(msg_delta)}\n\n"
    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"


# ── Models ─────────────────────────────────────────────────────────────────────
GEMINI_MODELS = {
    "auto":                   ("gemini-3-flash-preview",        "Авто",                  True),
    "gemini-2.5-pro":         ("gemini-2.5-pro",                "Gemini 2.5 Pro",         True),
    "gemini-2.5-flash":       ("gemini-2.5-flash",              "Gemini 2.5 Flash",       True),
    "gemini-3.1-pro-preview": ("gemini-3.1-pro-preview",        "Gemini 3.1 Pro Preview", True),
    "gemini-3-flash-preview": ("gemini-3-flash-preview",        "Gemini 3 Flash Preview", True),
}
AUTO_FALLBACK = ["gemini-3-flash-preview", "gemini-2.5-flash"]

# ── Main handler ───────────────────────────────────────────────────────────────
@app.post("/v1/messages")
async def handle_claude_request(request: Request):
    data = await request.json()
    messages = data.get("messages", [])
    tools = data.get("tools", [])
    stream = data.get("stream", False) # Читаем, хочет ли VS Code стриминг

    system = data.get("system", "")
    if isinstance(system, list): system = " ".join(b.get("text", "") for b in system if b.get("type") == "text")
    system = re.sub(r"x-anthropic-billing-header:[^\n]+\n?", "", system).strip()
    system_text = (system + "\nВсегда отвечай на русском языке.").strip()

    creds = get_credentials()
    token = creds.token
    project_id = await get_project_id(token)

    requested_model = data.get("model", "gemini-2.5-flash")
    gemini_model, _, _ = GEMINI_MODELS.get(requested_model, ("gemini-2.5-flash", "", False))

    recent_messages = messages[-20:] if len(messages) > 20 else messages
    contents = anthropic_messages_to_gemini(recent_messages)

    payload: dict = {
        "model": gemini_model,
        "project": project_id,
        "request": {
            "systemInstruction": {"parts": [{"text": system_text}]},
            "contents": contents,
        }
    }

    if tools:
        payload["request"]["tools"] = [{"functionDeclarations": anthropic_tools_to_gemini(tools)}]

    # Если VS Code просит стриминг — отдаем генератор букв
    if stream:
        log.info("📡 Включен режим реального времени (Streaming)")
        return StreamingResponse(
            gemini_stream_to_anthropic(token, project_id, gemini_model, payload, requested_model),
            media_type="text/event-stream"
        )

    # Обычный режим (для Whisper)
    log.info(f"[PROXY] Обычный запрос | Модель: {gemini_model} | Текст: {str(messages[-1].get('content', ''))[:80]}...")
    last_msg_key = json.dumps(messages[-1] if messages else {}, ensure_ascii=False, sort_keys=True)
    dedup_key = f"{gemini_model}:{last_msg_key}"

    if dedup_key in result_cache:
        cached, ts = result_cache[dedup_key]
        if asyncio.get_event_loop().time() - ts < 5:
            log.info("[PROXY] Отдаём из кэша")
            return cached
        del result_cache[dedup_key]

    try:
        # fail_fast=True: при 429 сразу возвращаем ошибку, не ждём 5 минут
        chunks = await gemini_post(token, project_id, gemini_model, payload, fail_fast=True)
        result = gemini_response_to_anthropic(chunks)
        for tool_id, sig in result.get("_thought_signatures", {}).items(): thought_sig_store[tool_id] = sig
        save_thought_sigs()
        
        if not result["content"]: result["content"] = [{"type": "text", "text": "✓"}]
        log.info(f"[PROXY] ✅ Ответ готов ({len(str(result['content']))} символов)")
    except Exception as e:
        log.error(f"[PROXY] ❌ Ошибка: {e}")
        result = {"content": [{"type": "text", "text": f"Ошибка: {e}"}], "stop_reason": "end_turn"}

    response_body = {
        "id": f"msg_{uuid.uuid4().hex[:16]}",
        "type": "message",
        "role": "assistant",
        "model": requested_model,
        "content": result["content"],
        "stop_reason": result["stop_reason"],
        "stop_sequence": None,
        "usage": {"input_tokens": 150, "output_tokens": 150} # Фикс для Continue в обычном режиме
    }
    result_cache[dedup_key] = (response_body, asyncio.get_event_loop().time())
    return response_body

if __name__ == "__main__":
    load_thought_sigs()
    log.info("Токен: %s", TOKEN_FILE_PATH)
    log.info("Запущен на http://%s:%d", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT)