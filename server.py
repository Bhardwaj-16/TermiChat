import socket
import threading
import json
import datetime
import sys
import random
import string
import time
import os
import asyncio
import http.server
import socketserver
try:
    import websockets
except ImportError:
    websockets = None

HOST = "0.0.0.0"
DEFAULT_PORT = 5555
CODE_TTL = 600  
HISTORY_FILE = "chat_history.json"

clients = {}        # conn -> {"name": str, "room": str}
rooms   = {}        # room_name -> [conn, ...]
invites = {}        # code -> {"room": str, "expires": float}
lock    = threading.Lock()



def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_message_to_history(room, name, text, msg_type="chat"):
    with lock:
        history = load_history()
        
        history.append({
            "room": room,
            "name": name,
            "text": text,
            "type": msg_type,
            "time": timestamp()
        })
        
        if len(history) > 1000:
            history.pop(0)
            
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=4)
        except Exception as e:
            print(f"[ERROR] Failed to write history file: {e}")

def send_room_history(conn, room):
    history = load_history()
    room_history = [msg for msg in history if msg.get("room") == room]
    
    for msg in room_history[-50:]:
        send_json(conn, msg)


def timestamp():
    return datetime.datetime.now().strftime("%H:%M")


def send_json(conn, data):
    try:
        conn.sendall((json.dumps(data) + "\n").encode())
    except Exception:
        pass


def broadcast(room, data, exclude=None):
    with lock:
        targets = list(rooms.get(room, []))
    for conn in targets:
        if conn != exclude:
            send_json(conn, data)


def send_room_list(conn):
    with lock:
        room_names = list(rooms.keys())
    send_json(conn, {"type": "room_list", "rooms": room_names})


def send_member_list(conn, room):
    with lock:
        members = [clients[c]["name"] for c in rooms.get(room, []) if c in clients]
    send_json(conn, {"type": "member_list", "room": room, "members": members})


def broadcast_member_list(room):
    with lock:
        members = [clients[c]["name"] for c in rooms.get(room, []) if c in clients]
        conns   = list(rooms.get(room, []))
    for conn in conns:
        send_json(conn, {"type": "member_list", "room": room, "members": members})



def generate_code():
    chars = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choices(chars, k=6))
        if code not in invites:
            return code


def purge_expired_codes():
    while True:
        time.sleep(30)
        now = time.time()
        with lock:
            expired = [c for c, v in invites.items() if v["expires"] < now]
            for c in expired:
                del invites[c]

def handle_client(conn, addr):
    buffer = ""
    try:
        while True:
            chunk = conn.recv(4096).decode("utf-8", errors="ignore")
            if not chunk:
                break
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if line:
                    try:
                        handle_message(conn, json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass
    finally:
        disconnect(conn)


def handle_message(conn, data):
    t = data.get("type")

    if t == "join":
        name = data.get("name", "Unknown")[:20]
        with lock:
            clients[conn] = {"name": name, "room": None}
        send_json(conn, {"type": "welcome", "message": f"Welcome, {name}!"})
        send_room_list(conn)

    elif t == "create_room":
        room = data.get("room", "").strip()[:30]
        if not room:
            send_json(conn, {"type": "error", "message": "Room name cannot be empty."})
            return
        with lock:
            if room in rooms and len(rooms[room]) > 0:
                send_json(conn, {"type": "error", "message": "Room already exists and has active members."})
                return
            if room not in rooms:
                rooms[room] = []
        join_room(conn, room, is_refresh=False)

    elif t == "join_name":
        room = data.get("room", "").strip()
        with lock:
            exists = room in rooms
        if not exists:
            send_json(conn, {"type": "error", "message": "That channel room does not exist."})
            return
        # Flag this execution stream as a refresh to suppress duplicated system logs
        join_room(conn, room, is_refresh=True)

    elif t == "join_room":
        code = data.get("code", "").strip().upper()
        now  = time.time()
        with lock:
            entry = invites.get(code)
        if not entry:
            send_json(conn, {"type": "error", "message": "Invalid invite code."})
            return
        if entry["expires"] < now:
            with lock:
                invites.pop(code, None)
            send_json(conn, {"type": "error", "message": "Invite code has expired."})
            return
        room = entry["room"]
        with lock:
            exists = room in rooms
        if not exists:
            send_json(conn, {"type": "error", "message": "That room no longer exists."})
            return
        join_room(conn, room, is_refresh=False)

    elif t == "gen_invite":
        with lock:
            info = clients.get(conn)
        if not info or not info["room"]:
            send_json(conn, {"type": "error", "message": "You must be in a room to create an invite."})
            return
        room    = info["room"]
        code    = generate_code()
        expires = time.time() + CODE_TTL
        with lock:
            invites[code] = {"room": room, "expires": expires}
        send_json(conn, {
            "type":    "invite_code",
            "code":    code,
            "room":    room,
            "expires": CODE_TTL,
        })

    elif t == "message":
        with lock:
            info = clients.get(conn)
        if not info or not info["room"]:
            send_json(conn, {"type": "error", "message": "Not in a room."})
            return
        text = data.get("text", "").strip()
        if not text:
            return
        
        save_message_to_history(info["room"], info["name"], text, "message")

        broadcast(info["room"], {
            "type": "message",
            "room": info["room"],
            "name": info["name"],
            "text": text,
            "time": timestamp(),
        })

    elif t == "delete_message":
        with lock:
            info = clients.get(conn)
        if not info or not info["room"]:
            return
            
        target_room = info["room"]
        target_text = data.get("text")
        target_name = data.get("sender_name")
        target_time = data.get("msg_time")
        
        with lock:
            history = load_history()
            updated_history = []
            deleted = False
            
            for msg in history:
                if (not deleted and 
                    msg.get("room") == target_room and 
                    msg.get("name") == target_name and 
                    msg.get("text") == target_text and 
                    msg.get("time") == target_time and 
                    msg.get("type", "message") == "message"):
                    deleted = True
                    continue
                updated_history.append(msg)
                
            if deleted:
                try:
                    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                        json.dump(updated_history, f, indent=4)
                except Exception as e:
                    print(f"[ERROR] Failed writing logs: {e}")
                    
        if deleted:
            broadcast(target_room, {
                "type": "refresh_history",
                "room": target_room
            })

    elif t == "leave_room":
        with lock:
            info = clients.get(conn)
        if info and info["room"]:
            leave_room(conn, info["room"])
        send_room_list(conn)

    elif t == "get_rooms":
        send_room_list(conn)

    elif t == "get_members":
        with lock:
            info = clients.get(conn)
        if info and info["room"]:
            send_member_list(conn, info["room"])

def join_room(conn, room, is_refresh=False):
    with lock:
        info = clients.get(conn)
        if not info:
            return
        old = info["room"]
        if old and old in rooms and conn in rooms[old]:
            rooms[old].remove(conn)
        info["room"] = room
        if room not in rooms:
            rooms[room] = []
        rooms[room].append(conn)
        name = info["name"]

    send_json(conn, {"type": "joined_room", "room": room})
    send_room_history(conn, room)

    if not is_refresh:
        sys_text = f"{name} joined #{room}"
        save_message_to_history(room, "", sys_text, "system")

        broadcast(room, {
            "type": "system",
            "room": room,
            "text": sys_text,
            "time": timestamp(),
        }, exclude=conn)
    
    broadcast_member_list(room)

def leave_room(conn, room):
    with lock:
        info = clients.get(conn)
        if not info:
            return
        name = info["name"]
        info["room"] = None
        if room in rooms and conn in rooms[room]:
            rooms[room].remove(conn)
    
    sys_text = f"{name} left #{room}"
    save_message_to_history(room, "", sys_text, "system")
    broadcast(room, {
        "type": "system",
        "room": room,
        "text": sys_text,
        "time": timestamp(),
    })
    broadcast_member_list(room)

def disconnect(conn):
    with lock:
        info = clients.pop(conn, None)
    if info:
        room = info["room"]
        name = info["name"]
        if room:
            with lock:
                if room in rooms and conn in rooms[room]:
                    rooms[room].remove(conn)
            
            sys_text = f"{name} disconnected"
            save_message_to_history(room, "", sys_text, "system")
            broadcast(room, {
                "type": "system",
                "room": room,
                "text": sys_text,
                "time": timestamp(),
            })
            broadcast_member_list(room)
    conn.close()

def start_http_server():
    web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
    if not os.path.exists(web_dir):
        print(f"[HTTP] Web directory not found at {web_dir}")
        return
    
    class SilentHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=web_dir, **kwargs)
        def log_message(self, format, *args):
            pass # Suppress HTTP logs to keep terminal clean

    try:
        with socketserver.TCPServer(("0.0.0.0", 8000), SilentHandler) as httpd:
            print("[HTTP] Web interface running on http://0.0.0.0:8000")
            httpd.serve_forever()
    except Exception as e:
        print(f"[HTTP] Failed to start HTTP server: {e}")

async def ws_proxy(websocket, path=None):
    try:
        reader, writer = await asyncio.open_connection('127.0.0.1', DEFAULT_PORT)
    except Exception as e:
        print(f"[WS] Failed to connect to TCP server: {e}")
        return

    async def tcp_to_ws():
        try:
            while True:
                data = await reader.readline()
                if not data:
                    break
                await websocket.send(data.decode('utf-8'))
        except Exception:
            pass
        finally:
            await websocket.close()

    async def ws_to_tcp():
        try:
            async for message in websocket:
                writer.write(message.encode('utf-8') + b'\n')
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    await asyncio.gather(tcp_to_ws(), ws_to_tcp())

async def serve_ws():
    async with websockets.serve(ws_proxy, "0.0.0.0", 5556):
        print("[WS] WebSocket proxy running on ws://0.0.0.0:5556")
        await asyncio.Future()  # run forever

def start_ws_proxy():
    if websockets is None:
        print("[WS] websockets library not found. Web interface WebSocket server will NOT start.")
        print("[WS] Run `pip install websockets` to enable.")
        return
        
    try:
        asyncio.run(serve_ws())
    except Exception as e:
        print(f"[WS] Failed to start WebSocket server: {e}")

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT

    t = threading.Thread(target=purge_expired_codes, daemon=True)
    t.start()
    
    # Start HTTP server for web interface
    threading.Thread(target=start_http_server, daemon=True).start()
    
    # Start WS proxy
    threading.Thread(target=start_ws_proxy, daemon=True).start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, port))
    server.listen(50)
    print(f"[SERVER] Listening on port {port}")
    print(f"[HISTORY] Logs are actively persisted to: {os.path.abspath(HISTORY_FILE)}")

    history = load_history()
    for item in history:
        r_name = item.get("room")
        if r_name and r_name not in rooms:
            rooms[r_name] = []

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()