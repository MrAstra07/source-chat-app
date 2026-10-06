"""Quick E2E smoke test for the chat WebSocket protocol (run against a live server)."""
import asyncio
import json
import urllib.error
import urllib.request
import websockets

WS_URL = "ws://127.0.0.1:8000/ws/"
HTTP_URL = "http://127.0.0.1:8000"


async def recv_json(ws, timeout=5):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def main():
    alice = await websockets.connect(WS_URL + "alice")
    bob = await websockets.connect(WS_URL + "bob")

    # both see alice join; drain system messages
    for ws in (alice, bob):
        await recv_json(ws)

    # --- chat message ---
    await alice.send(json.dumps({"type": "chat", "text": "hello encrypted world"}))
    msg = await recv_json(bob)
    assert msg["type"] == "chat" and msg["sender"] == "alice", msg
    assert msg["text"] == "hello encrypted world", msg
    print("[OK] chat:", msg["text"])

    # --- file transfer (small fake png, streamed to disk + fetched over HTTPS) ---
    payload = b"\x89PNG\r\n\x1a\n" + b"x" * 1000
    await alice.send(json.dumps({"type": "file_start", "name": "pic.png", "mime": "image/png", "size": len(payload)}))
    note = await recv_json(bob)
    assert note["type"] == "file_start", note
    print("[OK] file_start notice:", note["name"])

    CH = 256
    for i in range(0, len(payload), CH):
        await alice.send(payload[i:i + CH])
    file_msg = await recv_json(bob)
    assert file_msg["type"] == "file" and file_msg["name"] == "pic.png", file_msg
    assert file_msg["url"].startswith("/files/"), file_msg
    got = urllib.request.urlopen(HTTP_URL + file_msg["url"]).read()
    assert got == payload, "file bytes mismatch after AES-CTR encrypt/decrypt round-trip"
    print("[OK] streamed file bytes intact:",
          len(got), "bytes via", file_msg["url"])

    # --- unknown file id -> 404 ---
    try:
        urllib.request.urlopen(HTTP_URL + "/files/deadbeef")
        raise AssertionError("expected 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404, e.code
        print("[OK] unknown file id returns 404")

    # --- oversized rejection (limit is 2 GB) ---
    carol = await websockets.connect(WS_URL + "carol")
    await recv_json(carol)  # join system msg
    await carol.send(json.dumps({"type": "file_start", "name": "huge.bin", "mime": "application/octet-stream", "size": 3 * 1024 * 1024 * 1024}))
    rej = await recv_json(carol)
    assert rej["type"] == "system" and "rejected" in rej["text"], rej
    print("[OK] oversized rejected:", rej["text"])

    await alice.close()
    await bob.close()
    await carol.close()
    print("\nALL CHECKS PASSED")


asyncio.run(main())
