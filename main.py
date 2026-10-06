from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import json
import os
import re
import uuid
from pathlib import Path
from urllib.parse import quote
from datetime import datetime, timezone

app = FastAPI()

# Allow CORS for loopback connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_fernet_key() -> bytes:
    """Use FERNET_KEY from env if it is a valid key; otherwise generate one."""
    env_key = os.environ.get("FERNET_KEY", "").strip().encode()
    if env_key:
        try:
            Fernet(env_key)
            return env_key
        except Exception:
            # invalid key (e.g. Render's random generateValue) -> fall through
            pass
    return Fernet.generate_key()


KEY = _load_fernet_key()
cipher_suite = Fernet(KEY)

# Files stream to disk, so the cap is disk space, not RAM.
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB
READ_BLOCK = 256 * 1024

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# file_id -> {path, key, iv, name, mime, size, sender}
STORED_FILES: dict[str, dict] = {}

# Room codes: 3-12 chars, letters/digits/dash (normalized to uppercase)
ROOM_RE = re.compile(r"^[A-Z0-9-]{3,12}$")

os.makedirs("templates", exist_ok=True)
templates = Jinja2Templates(directory="templates")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConnectionManager:
    def __init__(self):
        # room code -> list of websockets
        self.rooms: dict[str, list[WebSocket]] = {}
        # websocket id -> room code (for cleanup on disconnect)
        self.ws_room: dict[int, str] = {}
        # In-flight uploads keyed by websocket id:
        # {name, mime, size, received, tmp_path, fh}
        self.uploads: dict[int, dict] = {}

    async def connect(self, websocket: WebSocket, room: str):
        await websocket.accept()
        self.rooms.setdefault(room, []).append(websocket)
        self.ws_room[id(websocket)] = room

    def disconnect(self, websocket: WebSocket):
        room = self.ws_room.pop(id(websocket), None)
        if room:
            conns = self.rooms.get(room, [])
            if websocket in conns:
                conns.remove(websocket)
            if not conns:
                self.rooms.pop(room, None)  # empty rooms are destroyed
        upload = self.uploads.pop(id(websocket), None)
        if upload:
            try:
                upload["fh"].close()
            except OSError:
                pass
            upload["tmp_path"].unlink(missing_ok=True)

    def member_count(self, room: str) -> int:
        return len(self.rooms.get(room, []))

    async def broadcast(self, room: str, payload: dict):
        text = json.dumps(payload)
        for connection in list(self.rooms.get(room, [])):
            try:
                await connection.send_text(text)
            except Exception:
                # This client already dropped; evict it so a single dead
                # socket can never break delivery to everyone else.
                self.disconnect(connection)


manager = ConnectionManager()


@app.get("/", response_class=HTMLResponse)
async def get_chat_page(request: Request):
    return templates.TemplateResponse(request, "index.html")


async def handle_text(websocket: WebSocket, username: str, room: str, raw: str):
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Legacy/plain text fallback -> treat as a chat message
        data = {"type": "chat", "text": raw}

    msg_type = data.get("type")

    if msg_type == "chat":
        text = str(data.get("text", ""))[:4000]
        if not text.strip():
            return
        # Encrypt then decrypt at the server payload layer (Fernet demo path)
        encrypted = cipher_suite.encrypt(text.encode("utf-8"))
        decrypted = cipher_suite.decrypt(encrypted).decode("utf-8")
        await manager.broadcast(
            room,
            {"type": "chat", "sender": username, "room": room,
                "text": decrypted, "ts": now_iso()}
        )

    elif msg_type == "file_start":
        name = str(data.get("name", "file"))[:255]
        mime = str(data.get("mime", "application/octet-stream"))[:255]
        size = int(data.get("size", 0))
        if size <= 0 or size > MAX_FILE_SIZE:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "system",
                        "text": f"File '{name}' rejected (max {MAX_FILE_SIZE // (1024 * 1024 * 1024)} GB).",
                        "ts": now_iso(),
                    }
                )
            )
            return
        tmp_path = UPLOAD_DIR / f"{uuid.uuid4().hex}.upload.tmp"
        manager.uploads[id(websocket)] = {
            "name": name,
            "mime": mime,
            "size": size,
            "received": 0,
            "tmp_path": tmp_path,
            "fh": open(tmp_path, "wb"),
        }
        others = [c for c in manager.rooms.get(room, []) if c is not websocket]
        if others:
            await manager.broadcast(
                room,
                {
                    "type": "file_start",
                    "sender": username,
                    "name": name,
                    "mime": mime,
                    "size": size,
                    "ts": now_iso(),
                }
            )


def finalize_upload(upload: dict) -> str:
    """Encrypt the completed temp file with streaming AES-256-CTR and register it."""
    file_id = uuid.uuid4().hex
    key = os.urandom(32)
    iv = os.urandom(16)
    final_path = UPLOAD_DIR / f"{file_id}.bin"

    cipher = Cipher(algorithms.AES(key), modes.CTR(iv))
    enc = cipher.encryptor()
    with upload["tmp_path"].open("rb") as src, final_path.open("wb") as dst:
        while block := src.read(READ_BLOCK):
            dst.write(enc.update(block))
        dst.write(enc.finalize())

    upload["tmp_path"].unlink(missing_ok=True)
    STORED_FILES[file_id] = {
        "path": final_path,
        "key": key,
        "iv": iv,
        "name": upload["name"],
        "mime": upload["mime"],
        "size": upload["size"],
        "sender": upload["sender"],
    }
    return file_id


async def handle_chunk(websocket: WebSocket, username: str, room: str, chunk: bytes):
    upload = manager.uploads.get(id(websocket))
    if not upload:
        return  # binary frame without a matching file_start -> ignore

    upload["fh"].write(chunk)
    upload["received"] += len(chunk)

    if upload["received"] > MAX_FILE_SIZE:
        # Abort this upload but keep the chat connection alive
        upload["fh"].close()
        upload["tmp_path"].unlink(missing_ok=True)
        manager.uploads.pop(id(websocket), None)
        await websocket.send_text(
            json.dumps(
                {"type": "system", "text": "Upload exceeded size limit; cancelled.", "ts": now_iso()})
        )
        return

    if upload["received"] < upload["size"]:
        return

    upload["sender"] = username
    upload["fh"].close()
    file_id = finalize_upload(upload)
    manager.uploads.pop(id(websocket), None)

    # Tiny metadata broadcast — the file itself is fetched over HTTPS
    await manager.broadcast(
        room,
        {
            "type": "file",
            "sender": username,
            "room": room,
            "name": upload["name"],
            "mime": upload["mime"],
            "size": upload["size"],
            "url": f"/files/{file_id}",
            "ts": now_iso(),
        }
    )


@app.get("/files/{file_id}")
async def download_file(file_id: str, dl: int = 0):
    meta = STORED_FILES.get(file_id)
    if not meta or not meta["path"].exists():
        raise HTTPException(
            status_code=404, detail="File not found (it may have been cleared by a server restart).")

    cipher = Cipher(algorithms.AES(meta["key"]), modes.CTR(meta["iv"]))
    dec = cipher.decryptor()

    def stream():
        with meta["path"].open("rb") as f:
            while block := f.read(READ_BLOCK):
                yield dec.update(block)
        yield dec.finalize()

    disposition = "attachment" if dl else "inline"
    headers = {
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(meta['name'])}",
    }
    return StreamingResponse(stream(), media_type=meta["mime"] or "application/octet-stream", headers=headers)


@app.websocket("/ws/{room}/{username}")
async def websocket_endpoint(websocket: WebSocket, room: str, username: str):
    room = room.strip().upper()[:12]
    if not ROOM_RE.match(room):
        # Invalid room code -> reject before accepting
        await websocket.close(code=1008)
        return
    username = username.strip()[:32] or "anon"
    await manager.connect(websocket, room)
    await manager.broadcast(
        room,
        {"type": "system", "room": room,
            "text": f"{username} joined the chat", "ts": now_iso()},
    )
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))
            if message.get("text") is not None:
                await handle_text(websocket, username, room, message["text"])
            elif message.get("bytes") is not None:
                await handle_chunk(websocket, username, room, message["bytes"])
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast(
            room,
            {"type": "system", "room": room,
                "text": f"{username} left the chat", "ts": now_iso()},
        )
