# 🔒 CipherChat — Real-Time Encrypted Chat with Large File Sharing

> 5th Semester IT Project · FastAPI · WebSockets · Cryptography
>
> **Live demo:** https://cipherchat.onrender.com

A real-time chat application where messages and files travel through an
encrypted server payload channel. Join a room with a shareable code, chat
with instant WebSocket delivery, and send videos, audio, photos or documents
up to **2 GB** — with inline previews on the receiving side.

---

## ✨ Features

| Feature | How it works |
|---|---|
| **Real-time messaging** | Bidirectional WebSockets (no polling, no refresh) |
| **Multi-room chat** | Shareable room codes (`?room=CODE` invite links), server-side isolation between rooms |
| **Encrypted payloads** | Every message passes through **Fernet** (AES-128-CBC + HMAC, from the `cryptography` library) server-side |
| **Large file sharing** | Videos, audio, docs, photos up to 2 GB — streamed to disk in 256 KB chunks, never buffered whole in RAM |
| **Encrypted file storage** | Files re-encrypted at rest with **streaming AES-256-CTR** (random key + IV per file) |
| **Media previews** | Images, video and audio render inline; other types get download cards |
| **Drag & drop uploads** | Live progress bar with back-pressure throttling |
| **Zero-install web app** | Vanilla HTML/CSS/JS frontend served by FastAPI — no build step |

## 🏗️ Architecture

```text
[Browser A] --(WebSocket: JSON + binary chunks)--> [ FastAPI + Uvicorn ] <--(WebSocket)-- [Browser B]
                                                          |
                                     uploads/ (AES-256-CTR encrypted at rest)
                                                          |
                                          GET /files/<id> (streamed, decrypted on the fly)
```

### Message & file flow

1. Client sends a JSON frame: `{type: "chat" | "file_start" | ...}`
2. Chat text → Fernet encrypt → decrypt → broadcast to the room
3. Files → `file_start` announces name/MIME/size → client streams the file
   as **binary WebSocket frames** (256 KB each) → server appends straight to disk
4. On completion, server encrypts the file with **AES-256-CTR in 256 KB blocks**
   and broadcasts a tiny metadata message: `{type: "file", url: "/files/<uuid>"}`
5. Receivers fetch the URL — the server streams the file back, decrypting on
   the fly. Memory usage stays O(1) regardless of file size.

### Protocol design choices

- **Why not base64 over the socket?** Base64 inflates payloads ~37% and forces
  whole-file buffering in RAM on both ends. Streaming to disk + HTTPS download
  raised the limit from 60 MB to 2 GB with *less* memory usage.
- **Why AES-CTR for files but Fernet for chat?** Fernet is not a streaming
  cipher — it needs the whole message in memory. AES-CTR (via the same
  `cryptography` library) encrypts block-by-block, ideal for bulk data.
- **Unguessable IDs:** download URLs use `uuid4` file IDs; keys/IVs live only
  in server memory, never in the URL.

## 🧰 Tech Stack

- **Backend:** Python 3.12, FastAPI, Uvicorn (`uvicorn[standard]`)
- **Real-time:** WebSockets (JSON control frames + binary data frames)
- **Crypto:** `cryptography` — Fernet (messages), AES-256-CTR (files at rest)
- **Frontend:** Vanilla JS, custom CSS design system (no frameworks)
- **Hosting:** Render (free tier), deployed from GitHub with `render.yaml`

## 🚀 Run Locally

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
# open http://127.0.0.1:8000 in two browser tabs, join the same room code
```

## ✅ Testing

`smoke_test.py` runs a full end-to-end protocol test against a live server
with three concurrent WebSocket clients:

```powershell
uvicorn main:app --port 8000        # terminal 1
python smoke_test.py                # terminal 2
```

Covers: in-room chat delivery, **room isolation** (cross-room leakage),
chunked file upload with byte-identical round-trip verification through the
AES pipeline, 404 handling for unknown file IDs, oversized-upload rejection,
and invalid room-code handshake rejection.

## ☁️ Deployment (Render)

`render.yaml` is a blueprint — Render reads it and configures itself:

- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Free tier caveats: cold start after idle, ephemeral disk (shared files are
  cleared on redeploy), 512 MB RAM

## ⚠️ Limitations & Future Scope

- **Server-side encryption boundary:** messages are encrypted at the server
  payload layer; the server can technically see plaintext. True end-to-end
  encryption (client-side keys, e.g. Web Crypto / Diffie–Hellman) is the
  natural next milestone.
- **Ephemeral storage:** file registry is in-memory; a restart orphans
  uploads. Fix: persist metadata in SQLite/Postgres + object storage (S3).
- **No upload TTL sweeper:** `uploads/` grows until restart in long-running
  deployments.
- Free-tier sleep disconnects idle clients (no auto-reconnect yet).

---

*Built as a university project exploring networking, real-time web
architecture and applied cryptography. UI design direction inspired by
[BitChord](https://bitchord.kushagrasingh.in/).*
