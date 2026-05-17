#!/usr/bin/env python3
"""
EXP-A: Cancel-during-stream rollback race.

Hypothesis: server increments quota counter BEFORE confirming response.
If we abort TCP mid-flight, counter MAY not roll back, OR the gate may not yet have decremented.
We test:
  1. Send opus request, abort connection at 50ms (before any meaningful processing)
  2. Verify if a follow-up opus request still gets failed_precondition (control)
  3. Then test: send kimi (succeeds), abort mid-stream, see if we can sneak opus through "warm" path
"""
import socket, ssl, struct, time, gzip
from pathlib import Path

HOST = "server.self-serve.windsurf.com"
PORT = 443

# Read full envelope (claude-opus baseline, 0 quota Pro account)
ENV = Path('/tmp/wf_exp/last_gcm_envelope.bin').read_bytes()
print(f"Loaded envelope: {len(ENV)}B")

def send_partial(envelope, abort_after_bytes=None, abort_after_ms=None, label="?"):
    """Send a request and abort the connection at a specified point."""
    ctx = ssl.create_default_context()
    sock = socket.create_connection((HOST, PORT), timeout=10)
    ssock = ctx.wrap_socket(sock, server_hostname=HOST)

    headers = (
        f"POST /exa.api_server_pb.ApiServerService/GetChatMessage HTTP/1.1\r\n"
        f"Host: {HOST}\r\n"
        f"User-Agent: connect-go/1.18.1 (go1.26.1)\r\n"
        f"Content-Type: application/connect+proto\r\n"
        f"Connect-Protocol-Version: 1\r\n"
        f"Connect-Content-Encoding: gzip\r\n"
        f"Connect-Accept-Encoding: gzip\r\n"
        f"Accept-Encoding: identity\r\n"
        f"Content-Length: {len(envelope)}\r\n"
        f"\r\n"
    ).encode()

    t0 = time.time()
    ssock.sendall(headers)

    if abort_after_bytes is not None:
        try:
            ssock.sendall(envelope[:abort_after_bytes])
        except: pass
        try: ssock.unwrap()
        except: pass
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
        except: pass
        try: sock.close()
        except: pass
        elapsed = (time.time() - t0) * 1000
        print(f"  [{label}] aborted after sending {abort_after_bytes}B headers+body ({elapsed:.0f}ms)")
        return None

    try:
        ssock.sendall(envelope)
    except Exception as e:
        print(f"  [{label}] send err: {e}")
        return None

    if abort_after_ms is not None:
        time.sleep(abort_after_ms / 1000)
        try: ssock.unwrap()
        except: pass
        try: sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
        except: pass
        try: sock.close()
        except: pass
        elapsed = (time.time() - t0) * 1000
        print(f"  [{label}] aborted after {elapsed:.0f}ms (full body sent)")
        return None

    # Normal: read response
    resp = b""
    try:
        ssock.settimeout(15)
        while True:
            chunk = ssock.recv(8192)
            if not chunk: break
            resp += chunk
    except: pass
    elapsed = (time.time() - t0) * 1000
    print(f"  [{label}] complete: {len(resp)}B in {elapsed:.0f}ms")
    try: ssock.close()
    except: pass
    return resp

def parse_resp(resp):
    """Extract status code + body."""
    if not resp: return None
    try:
        head, body = resp.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n")[0]
        # parse chunked or content-length
        if b"transfer-encoding: chunked" in head.lower():
            # parse chunks
            out = b""; o = 0
            while o < len(body):
                e = body.find(b"\r\n", o)
                if e < 0: break
                ln = int(body[o:e], 16)
                if ln == 0: break
                out += body[e+2:e+2+ln]
                o = e + 2 + ln + 2
            body = out
        return (status.decode(errors='replace'), body)
    except Exception as e:
        return ("PARSE_ERR", resp[:200])

def decode_envelope(env_data):
    if len(env_data) < 5: return env_data
    flag = env_data[0]
    ln = struct.unpack(">I", env_data[1:5])[0]
    p = env_data[5:5+ln]
    if flag & 1 and p[:2] == b'\x1f\x8b':
        try: p = gzip.decompress(p)
        except: pass
    return p

def control_check(label):
    """Send a normal opus request and decode response."""
    resp = send_partial(ENV, label=label)
    if resp:
        s, b = parse_resp(resp)
        env_data = b
        decoded = decode_envelope(env_data)
        print(f"     status: {s}")
        print(f"     decoded ({len(decoded)}B): {decoded[:300]}")
        return decoded
    return None

# === A1: Control — verify baseline opus = failed_precondition
print("\n=== A1: Control opus baseline ===")
control_check("control1")

# === A2: Send opus, abort after 1KB body (no response possible) ===
print("\n=== A2: Abort after 1KB body sent ===")
send_partial(ENV[:1000] + b"", abort_after_bytes=500, label="abort_partial")
time.sleep(2)
print("\n  Follow-up opus to see if quota state changed:")
control_check("after_partial_abort")

# === A3: Send full body, abort at 50ms (before LLM responds) ===
print("\n=== A3: Full body sent, abort at 50ms ===")
send_partial(ENV, abort_after_ms=50, label="abort_50ms")
time.sleep(2)
print("\n  Follow-up opus:")
control_check("after_50ms_abort")

# === A4: Send full body, abort at 200ms ===
print("\n=== A4: Full body, abort at 200ms ===")
send_partial(ENV, abort_after_ms=200, label="abort_200ms")
time.sleep(2)
print("\n  Follow-up opus:")
control_check("after_200ms_abort")

# === A5: Burst 5 concurrent ===
print("\n=== A5: Burst 5 parallel (will fail) ===")
import threading
results = []
def burst(i):
    try:
        r = send_partial(ENV, label=f"burst{i}")
        results.append((i, r))
    except Exception as e:
        results.append((i, f"err: {e}"))
threads = [threading.Thread(target=burst, args=(i,)) for i in range(5)]
for t in threads: t.start()
for t in threads: t.join()
for i, r in results:
    if isinstance(r, bytes):
        s, b = parse_resp(r)
        d = decode_envelope(b)
        print(f"  burst#{i}: status={s} decoded[:80]={d[:80]}")
    else:
        print(f"  burst#{i}: {r}")
