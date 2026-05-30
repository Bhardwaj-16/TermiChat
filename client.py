import socket
import threading
import json
import sys
import os
import signal
import time

from prompt_toolkit import prompt
from prompt_toolkit.styles import Style as PStyle
from prompt_toolkit.patch_stdout import patch_stdout

ESC = "\033["

def ansi(*codes):
    return ESC + ";".join(str(c) for c in codes) + "m"

RESET = ansi(0)
BOLD = ansi(1)
DIM_S = ansi(2)
ITALIC = ansi(3)

C_TEXT = ansi(38, 5, 253)
C_NAME = BOLD + ansi(38, 5, 255)
C_TIME = ansi(38, 5, 242)
C_SYSTEM = ansi(38, 5, 245) + ITALIC
C_ACCENT = BOLD + ansi(38, 5, 45)
C_DIM = ansi(38, 5, 243)
C_BORDER = ansi(38, 5, 237)
C_CODE = BOLD + ansi(38, 5, 214)
C_ERROR = BOLD + ansi(38, 5, 196)
BG_SELECT = ansi(48, 5, 238) + BOLD + ansi(38, 5, 214)

def cursor_to(row, col): return f"\033[{row};{col}H" 
def clear_line():   return "\033[K" 
def hide_cursor():  sys.stdout.write("\033[?25l"); sys.stdout.flush()
def show_cursor():  sys.stdout.write("\033[?25h"); sys.stdout.flush()

def strip_ansi(s):
    import re
    return re.sub(r'\033\[[^m]*m', '', s)

def pad_to(s, width):
    visible = len(strip_ansi(s))
    if visible < width:
        return s + " " * (width - visible)
    return s

def trunc_visible(s, width):
    import re
    result = ""
    visible = 0
    i = 0
    while i < len(s):
        if s[i] == "\033":
            j = s.find("m", i)
            if j == -1:
                break
            result += s[i:j+1]
            i = j + 1
        else:
            if visible >= width:
                break
            result += s[i]
            visible += 1
            i += 1
    return result + RESET

H  = "─"
V  = "│"
TL = "┌"; TR = "┐"; BL = "└"; BR = "┘"
VL = "├"; VR = "┤"; TT = "┬"; BT = "┴"

state = {
    "name":             "",
    "room":             None,
    "members":          [],
    "rooms":            [],
    "messages":         [],   
    "raw_messages":     [],
    "connected":        False,
    "selection_mode":   False,
    "selected_index":   -1,
}
state_lock = threading.Lock()


def build_line(name, text, time_str, kind="chat"):
    if kind == "system":
        return C_SYSTEM + f"  ✦  {text}" + RESET
    elif kind == "error":
        return C_ERROR  + f"  ¡  {text}" + RESET
    elif kind == "code":
        return C_SYSTEM + "     Code Generated ❯ " + C_CODE + text + RESET
    else:
        return (C_TIME + f" [{time_str}] " +
                C_NAME + f"@{name:<12} " + RESET +
                C_BORDER + "❯ " + RESET +
                C_TEXT + text + RESET)

def add_message_struct(msg_dict):
    with state_lock:
        state["raw_messages"].append(msg_dict)
        line = build_line(msg_dict.get("name",""), msg_dict.get("text",""), msg_dict.get("time",""), kind=msg_dict.get("type","chat"))
        state["messages"].append(line)
        
        if len(state["raw_messages"]) > 500:
            state["raw_messages"].pop(0)
            state["messages"].pop(0)
    render_screen()


def term_size():
    try:
        sz = os.get_terminal_size()
        return sz.lines, sz.columns
    except OSError:
        return 24, 80

def render_screen():
    with state_lock:
        room     = state["room"]
        members  = list(state["members"])
        msgs     = list(state["messages"])
        rooms    = list(state["rooms"])
        name     = state["name"]
        sel_mode = state["selection_mode"]
        sel_idx  = state["selected_index"]

    rows, cols = term_size()

    UI_ROWS  = max(10, rows - 1)
    SIDE_W   = 24
    CHAT_W   = max(10, cols - SIDE_W - 3)
    HEADER_H = 3
    FOOTER_H = 3
    BODY_H   = max(2, UI_ROWS - HEADER_H - FOOTER_H)

    out = []
    out.append("\033[?25l")
    current_row = 1

    active_channel = f"#{room}" if room else "DISCONNECTED"
    header_title   = f" ⚡ CORD TERMINAL "
    header_status  = f" CHANNEL: {active_channel} "
    
    center_space   = cols - len(header_title) - len(header_status) - 2
    if center_space < 1: center_space = 1
    
    top_bar_content = C_NAME + header_title + C_DIM + ("─" * center_space) + C_ACCENT + header_status + RESET
    
    out.append(cursor_to(current_row, 1) + C_BORDER + TL + H * (cols - 2) + TR + RESET + clear_line())
    current_row += 1
    out.append(cursor_to(current_row, 1) + C_BORDER + V + RESET + pad_to(top_bar_content, cols - 2) + C_BORDER + V + RESET + clear_line())
    current_row += 1
    out.append(cursor_to(current_row, 1) + C_BORDER + VL + H * CHAT_W + TT + H * SIDE_W + VR + RESET + clear_line())
    current_row += 1

    side_lines = []
    side_lines.append(C_DIM + "  SERVERS" + RESET)
    side_lines.append(C_BORDER + "  " + "╌" * (SIDE_W - 4) + RESET)
    
    if rooms:
        for r in rooms:
            if r == room:
                side_lines.append(C_ACCENT + "  ● #" + f"{r:<16}" + RESET)
            else:
                side_lines.append(C_SYSTEM + "    #" + f"{r:<16}" + RESET)
    else:
        side_lines.append(C_DIM + "    No channels active" + RESET)

    side_lines.append("")  
    side_lines.append(C_DIM + f"  MEMBERS ({len(members)})" + RESET)
    side_lines.append(C_BORDER + "  " + "╌" * (SIDE_W - 4) + RESET)
    
    if room and members:
        for m in members:
            side_lines.append(C_TEXT + "  ○ " + f"{m[:16]:<16}" + RESET)
    else:
        side_lines.append(C_DIM + "    Empty room context" + RESET)

    while len(side_lines) < BODY_H:
        side_lines.append("")

    visible_count = BODY_H
    visible_msgs  = msgs[-visible_count:] if len(msgs) >= visible_count else msgs
    chat_lines    = [""] * (visible_count - len(visible_msgs)) + visible_msgs

    slice_start_idx = max(0, len(msgs) - visible_count)

    for i in range(BODY_H):
        chat_raw  = chat_lines[i] if i < len(chat_lines) else ""
        side_raw  = side_lines[i] if i < len(side_lines) else ""

        slot_index = i - (visible_count - len(visible_msgs))
        if sel_mode and slot_index >= 0:
            global_msg_idx = slice_start_idx + slot_index
            if global_msg_idx == sel_idx:
                chat_raw = BG_SELECT + "  ➔  " + strip_ansi(chat_raw) + RESET

        chat_part = trunc_visible(" " + chat_raw, CHAT_W)
        chat_part = pad_to(chat_part, CHAT_W)
        side_part = trunc_visible(" " + side_raw, SIDE_W)
        side_part = pad_to(side_part, SIDE_W)

        out.append(cursor_to(current_row, 1) + C_BORDER + V + RESET + chat_part + C_BORDER + V + RESET + side_part + C_BORDER + V + RESET + clear_line())
        current_row += 1

    out.append(cursor_to(current_row, 1) + C_BORDER + VL + H * CHAT_W + BT + H * SIDE_W + VR + RESET + clear_line())
    current_row += 1
    
    if sel_mode:
        footer_row_content = C_CODE + "  ▲/▼ Scroll History  │  ENTER Confirm Delete  │  ESC Abort Target Selection  " + RESET
    else:
        identity_badge = C_DIM + " Identity Profile: " + C_NAME + f"@{name}" + RESET
        help_indicator = C_DIM + "Type " + C_ACCENT + "/help" + C_DIM + " for manual console actions " + RESET
        bot_space      = cols - len(strip_ansi(identity_badge)) - len(strip_ansi(help_indicator)) - 2
        if bot_space < 1: bot_space = 1
        footer_row_content = identity_badge + (" " * bot_space) + help_indicator

    out.append(cursor_to(current_row, 1) + C_BORDER + V + RESET + pad_to(footer_row_content, cols - 2) + C_BORDER + V + RESET + clear_line())
    current_row += 1
    out.append(cursor_to(current_row, 1) + C_BORDER + BL + H * (cols - 2) + BR + RESET + clear_line())

    if sel_mode:
        out.append(cursor_to(rows, 1) + C_CODE + " SCROLL-DELETE MODE " + C_BORDER + "❯ " + RESET + clear_line() + "\033[?25l")
    else:
        out.append(cursor_to(rows, 1) + "\033[?25h")

    sys.stdout.write("".join(out))
    sys.stdout.flush()


def show_help():
    lines = [
        ("── PLATFORM COMMAND CONTROLS ─────────────────────────", "system"),
        ("/create <name>   Instantiate a brand new server channel room", "system"),
        ("/invite          Generate a timed room access registration token", "system"),
        ("/join   <code>   Connect to room using an active invite string", "system"),
        ("/joinroom <name> Jump directly into an existing room name from history", "system"),
        ("/delete          Enter scroll mode to select and remove a message", "system"),
        ("/leave           Drop visibility access channel assignment context", "system"),
        ("/rooms           Query directory indexing for refreshed network list", "system"),
        ("/members         Force synchronized client mapping audit trace", "system"),
        ("/quit            Safely spin down app connection runtime modules", "system"),
    ]
    for text, kind in lines:
        add_message_struct({"type": kind, "text": text, "name": "", "time": ""})


class Client:
    def __init__(self, host, port, name):
        self.host   = host
        self.port   = port
        self.name   = name
        self.sock   = None
        self.buf    = ""
        self._stop  = False

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect((self.host, self.port))
        self.sock.settimeout(None)
        self.send({"type": "join", "name": self.name})
        threading.Thread(target=self._recv, daemon=True).start()

    def send(self, data):
        try:
            self.sock.sendall((json.dumps(data) + "\n").encode())
        except Exception:
            pass

    def _recv(self):
        while not self._stop:
            try:
                chunk = self.sock.recv(4096).decode("utf-8", errors="ignore")
                if not chunk:
                    break
                self.buf += chunk
                while "\n" in self.buf:
                    line, self.buf = self.buf.split("\n", 1)
                    line = line.strip()
                    if line:
                        try:
                            self._handle(json.loads(line))
                        except Exception:
                            pass
            except Exception:
                break
        add_message_struct({"type": "error", "text": "Connection state dropped from main host interface.", "name": "", "time": ""})

    def close(self):
        self._stop = True
        try:
            self.sock.close()
        except Exception:
            pass

    def _handle(self, data):
        t = data.get("type")

        if t == "welcome":
            with state_lock:
                state["connected"] = True
            add_message_struct({"type": "system", "text": data["message"], "name": "", "time": ""})

        elif t == "room_list":
            with state_lock:
                state["rooms"] = data.get("rooms", [])
            render_screen()

        elif t == "joined_room":
            with state_lock:
                state["room"] = data["room"]
                state["messages"] = []
                state["raw_messages"] = []
            add_message_struct({"type": "system", "text": f"Context mapped successfully onto channel #{data['room']}", "name": "", "time": ""})

        elif t == "member_list":
            with state_lock:
                if data["room"] == state["room"]:
                    state["members"] = data.get("members", [])
            render_screen()

        elif t == "invite_code":
            mins = data["expires"] // 60
            add_message_struct({"type": "system", "text": f"Temporary invitation token allocated for #{data['room']} (Valid {mins}m)", "name": "", "time": ""})
            add_message_struct({"type": "code", "text": data["code"], "name": "", "time": ""})

        elif t == "message" or t == "system" or t == "error":
            add_message_struct(data)

        elif t == "refresh_history":
            with state_lock:
                current_room = state["room"]
            if current_room == data.get("room"):
                self.send({"type": "join_name", "room": current_room})

def enter_selection_mode(client: Client):
    with state_lock:
        msgs = list(state["raw_messages"])
        if not msgs:
            state["raw_messages"].append({"type": "error", "text": "No trace variables present in active console logging canvas to isolate for deletion.", "name": "", "time": ""})
            state["messages"].append(build_line("", "No trace variables present in active console logging canvas to isolate for deletion.", "", "error"))
            render_screen()
            return
        state["selection_mode"] = True
        state["selected_index"] = len(msgs) - 1

    render_screen()
    import termios
    import tty
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch1 = sys.stdin.read(1)
            if ch1 == '\x1b':
                ch2 = sys.stdin.read(1)
                if ch2 == '[':
                    ch3 = sys.stdin.read(1)
                    if ch3 == 'A':
                        with state_lock:
                            if state["selected_index"] > 0:
                                state["selected_index"] -= 1
                        render_screen()
                    elif ch3 == 'B':
                        with state_lock:
                            if state["selected_index"] < len(state["raw_messages"]) - 1:
                                state["selected_index"] += 1
                        render_screen()
                elif ch2 == '\x1b' or ch2 == '':
                    with state_lock: state["selection_mode"] = False
                    break
            elif ch1 == '\r' or ch1 == '\n':
                with state_lock:
                    idx = state["selected_index"]
                    msgs = list(state["raw_messages"])
                    state["selection_mode"] = False
                
                if idx >= 0 and idx < len(msgs):
                    target_msg = msgs[idx]
                    if target_msg.get("type", "message") == "message":
                        client.send({
                            "type": "delete_message",
                            "text": target_msg.get("text"),
                            "sender_name": target_msg.get("name"),
                            "msg_time": target_msg.get("time")
                        })
                    else:
                        with state_lock:
                            state["raw_messages"].append({"type": "error", "text": "System metrics logs cannot be targeted for remote workspace removal.", "name": "", "time": ""})
                            state["messages"].append(build_line("", "System metrics logs cannot be targeted for remote workspace removal.", "", "error"))
                break
            elif ch1 == '\x03':
                with state_lock: state["selection_mode"] = False
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    render_screen()


def input_loop(client: Client):
    pt_style = PStyle.from_dict({
        "":       "#e0e0e0",
        "prompt": "bold #00ffff",
    })

    with patch_stdout(raw=True):
        while True:
            with state_lock:
                sel_mode = state["selection_mode"]
            if sel_mode:
                enter_selection_mode(client)
                continue

            render_screen()
            try:
                user_input = prompt(" Message ❯ ", style=pt_style)
            except (EOFError, KeyboardInterrupt):
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.startswith("/"):
                parts = user_input[1:].split(None, 1)
                cmd   = parts[0].lower() if parts else ""
                arg   = parts[1].strip() if len(parts) > 1 else ""

                if cmd == "quit":
                    break
                elif cmd == "help":
                    show_help()
                elif cmd == "create":
                    if not arg:
                        add_message_struct({"type": "error", "text": "Syntax checking validation error. Correct usage: /create <name>", "name": "", "time": ""})
                    else:
                        client.send({"type": "create_room", "room": arg})
                elif cmd == "invite":
                    client.send({"type": "gen_invite"})
                elif cmd == "join":
                    if not arg:
                        add_message_struct({"type": "error", "text": "Syntax checking validation error. Correct usage: /join <code>", "name": "", "time": ""})
                    else:
                        client.send({"type": "join_room", "code": arg.upper()})
                elif cmd == "joinroom":
                    if not arg:
                        add_message_struct({"type": "error", "text": "Syntax checking validation error. Correct usage: /joinroom <name>", "name": "", "time": ""})
                    else:
                        client.send({"type": "join_name", "room": arg})
                elif cmd == "delete":
                    with state_lock: state["selection_mode"] = True
                    continue
                elif cmd == "leave":
                    client.send({"type": "leave_room"})
                    with state_lock:
                        state["room"]    = None
                        state["members"] = []
                    render_screen()
                elif cmd == "rooms":
                    client.send({"type": "get_rooms"})
                elif cmd == "members":
                    client.send({"type": "get_members"})
                else:
                    add_message_struct({"type": "error", "text": f"Unparsed workspace console directive target: /{cmd}", "name": "", "time": ""})
            else:
                with state_lock:
                    in_room = state["room"]
                if not in_room:
                    add_message_struct({"type": "error", "text": "No target channel selected. Connect via invitation tracking code token or use /create", "name": "", "time": ""})
                else:
                    client.send({"type": "message", "text": user_input})

    show_cursor()
    client.close()
    sys.stdout.write("\033[?1049l") 
    sys.stdout.flush()
    print("Session disconnected. Goodbye.")


def boot_screen():
    sys.stdout.write("\033[H\033[2J")
    sys.stdout.flush()
    rows, cols = term_size()
    pad = " " * max((cols - 30) // 2, 0)
    print("\n" * 2)
    print(pad + BOLD + ansi(97) + "      ░░░░  ░░░░  ░░░░  ░░░  " + RESET)
    print(pad + BOLD + ansi(97) + "      █     █  █  █  █  █  █ " + RESET)
    print(pad + BOLD + ansi(252) + "      █     █  █  ███   █  █ " + RESET)
    print(pad + BOLD + ansi(244) + "      ████  ████  █  █  ███  " + RESET)
    print("\n" + pad + C_DIM + "        --- TERMINAL CHAT ---" + RESET)
    print("\n" * 2)
    print(C_BORDER + "─" * cols + RESET)
    print()

def main():
    boot_screen()

    name = ""
    while not name.strip():
        name = input(C_DIM + "  Set Identity Handle ❯ " + RESET).strip()
    name = name[:20]

    host     = input(C_DIM + "  Orchestrator Host IP (Default: 127.0.0.1) ❯ " + RESET).strip() or "127.0.0.1"
    port_str = input(C_DIM + "  Service Network Port (Default: 5555) ❯ " + RESET).strip()
    port     = int(port_str) if port_str.isdigit() else 5555

    state["name"] = name

    client = Client(host, port, name)
    try:
        client.connect()
    except Exception as e:
        print(C_ERROR + f"Socket orchestration routing failure: {e}" + RESET)
        sys.exit(1)

    sys.stdout.write("\033[?1049h\033[H\033[2J")
    sys.stdout.flush()

    add_message_struct({"type": "system", "text": "Handshake verified. Enter /help to check command list documentation.", "name": "", "time": ""})

    try:
        signal.signal(signal.SIGWINCH, lambda *_: render_screen())
    except (AttributeError, OSError):
        pass

    input_loop(client)


if __name__ == "__main__":
    main()