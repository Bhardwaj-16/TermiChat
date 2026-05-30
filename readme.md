# TermiChat

Safe terminal based chat application which uses port forwarding and saving chat history in local storage to create a  fast, safe and secure channel for communicating. 

# Themes

Black/silver theme.


---

##  dependencies

```bash
pip3 install rich prompt_toolkit websockets
```

---

## Run

### 1. Start the server
```bash
python server.py
```
Default TCP port is **5555**. The server also starts a Web Interface at **http://localhost:8000** and a WebSocket proxy at port **5556**.

You can pass a custom TCP port:
```bash
python server.py 6000
```

### 2. Start the client (each user runs this)
```bash
python client.py
```
You'll be asked for:
- Your name
- Server IP (default: `127.0.0.1` for local)
- Port (default: `5555`)

---

## Commands (inside the chat)

| Command | What it does |
|---|---|
| `/create <name>` | Create a new server/room |
| `/join <name>` | Join an existing room |
| `/leave` | Leave current room |
| `/rooms` | Refresh the room list |
| `/members` | Show members in current room |
| `/help` | Show all commands |
| `/quit` | Exit the app |

---

## External modules

| Module | Install | Purpose |
|---|---|---|
| `rich` | `pip install rich` | Terminal UI — panels, colors, layout |
| `prompt_toolkit` | `pip install prompt_toolkit` | Clean input bar at the bottom |

Everything else is Python standard library (`socket`, `threading`, `json`, `datetime`, `os`, `sys`).

---

## Files

```
server.py   — runs on the host machine, manages rooms and users
client.py   — each user runs this to connect and chat
```

---

## LAN usage

- Host runs `python server.py` on their machine
- Others connect using the host's local IP (e.g. `192.168.1.5`)
- All must be on the same network