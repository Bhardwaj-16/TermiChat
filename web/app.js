const EMOJIS = {
  ':thumbsup:': '👍', ':smile:': '😊', ':heart:': '❤️', ':laughing:': '😆',
  ':wink:': '😉', ':fire:': '🔥', ':rocket:': '🚀', ':check:': '✅',
  ':cross:': '❌', ':thinking:': '🤔', ':eyes:': '👀', ':tada:': '🎉',
  ':sob:': '😭', ':sweat_smile:': '😅', ':clap:': '👏', ':rofl:': '🤣',
  ':cool:': '😎', ':sad:': '😔', ':angry:': '😠', ':poop:': '💩'
};

const loginScreen = document.getElementById('login-screen');
const chatScreen = document.getElementById('chat-screen');
const loginForm = document.getElementById('login-form');
const messagesDiv = document.getElementById('messages');
const roomListDiv = document.getElementById('room-list');
const memberListDiv = document.getElementById('member-list');
const memberCountSpan = document.getElementById('member-count');
const currentRoomSpan = document.getElementById('current-room');
const identityNameSpan = document.getElementById('identity-name');
const messageForm = document.getElementById('message-form');
const messageInput = document.getElementById('message-input');
const emojiBtn = document.getElementById('emoji-btn');
const emojiPicker = document.getElementById('emoji-picker');
const sidebarToggle = document.getElementById('sidebar-toggle');
const sidebar = document.getElementById('sidebar');
const sidebarOverlay = document.getElementById('sidebar-overlay');

let ws = null;
let currentRoom = null;
let username = '';

// Initialize Emoji Picker
Object.entries(EMOJIS).forEach(([shortcode, emoji]) => {
  const el = document.createElement('div');
  el.className = 'emoji-item';
  el.textContent = emoji;
  el.title = shortcode;
  el.onclick = () => {
    messageInput.value += shortcode + ' ';
    messageInput.focus();
    emojiPicker.classList.add('hidden');
    emojiBtn.classList.remove('active');
  };
  emojiPicker.appendChild(el);
});

emojiBtn.addEventListener('click', () => {
  emojiPicker.classList.toggle('hidden');
  emojiBtn.classList.toggle('active');
});

// Hide emoji picker when clicking outside
document.addEventListener('click', (e) => {
  if (!emojiBtn.contains(e.target) && !emojiPicker.contains(e.target)) {
    emojiPicker.classList.add('hidden');
    emojiBtn.classList.remove('active');
  }
});

// Mobile Sidebar Toggle
sidebarToggle.addEventListener('click', () => {
  sidebar.classList.toggle('open');
  sidebarOverlay.classList.toggle('active');
});

sidebarOverlay.addEventListener('click', () => {
  sidebar.classList.remove('open');
  sidebarOverlay.classList.remove('active');
});

// Format message text to replace shortcodes with emojis
function formatText(text) {
  let formatted = text || '';
  Object.entries(EMOJIS).forEach(([shortcode, emoji]) => {
    formatted = formatted.split(shortcode).join(emoji);
  });
  return formatted;
}

// Add message to chat area
function addMessage(msg) {
  const line = document.createElement('div');
  line.className = 'msg-line';
  
  if (msg.type === 'system') {
    line.innerHTML = `<span class="msg-system">✦ ${formatText(msg.text)}</span>`;
  } else if (msg.type === 'error') {
    line.innerHTML = `<span class="msg-error">¡ ${formatText(msg.text)}</span>`;
  } else if (msg.type === 'code') {
    line.innerHTML = `<span class="msg-system">Code Generated ❯ </span><span class="msg-code">${msg.text}</span>`;
  } else {
    // Normal message
    line.innerHTML = `
      <span class="msg-time">[${msg.time || new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}]</span>
      <span class="msg-name">@${msg.name}</span>
      <span class="msg-sep">❯</span>
      <span class="msg-text">${formatText(msg.text)}</span>
    `;
  }
  
  messagesDiv.appendChild(line);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// Handle login
loginForm.addEventListener('submit', (e) => {
  e.preventDefault();
  username = document.getElementById('username').value.trim();
  let host = document.getElementById('host').value.trim() || window.location.hostname || '127.0.0.1';
  
  // Default port for WS
  const wsUrl = `ws://${host}:5556`;
  
  connect(wsUrl);
});

function connect(url) {
  ws = new WebSocket(url);
  
  ws.onopen = () => {
    loginScreen.classList.add('hidden');
    chatScreen.classList.remove('hidden');
    identityNameSpan.textContent = username;
    
    // Send join message
    send({ type: 'join', name: username });
  };
  
  ws.onmessage = (event) => {
    try {
      // WS sends messages delimited by newline, or single objects.
      // But we parse line by line just in case, because python sends string + '\n'
      const lines = event.data.split('\n');
      for (const line of lines) {
        if (line.trim()) {
          const data = JSON.parse(line.trim());
          handleMessage(data);
        }
      }
    } catch (e) {
      console.error("Failed to parse message", e);
    }
  };
  
  ws.onclose = () => {
    addMessage({ type: 'error', text: 'Disconnected from server.' });
    setTimeout(() => {
      window.location.reload();
    }, 5000);
  };
  
  ws.onerror = (err) => {
    console.error("WebSocket error", err);
    alert("Connection failed. Check if server is running on " + url);
  };
}

function send(data) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(data) + '\n');
  }
}

function handleMessage(data) {
  const t = data.type;
  
  if (t === 'welcome') {
    addMessage({ type: 'system', text: data.message });
  } else if (t === 'room_list') {
    updateRooms(data.rooms);
  } else if (t === 'joined_room') {
    currentRoom = data.room;
    currentRoomSpan.textContent = `#${data.room}`;
    messagesDiv.innerHTML = ''; // Clear chat
    addMessage({ type: 'system', text: `Context mapped successfully onto channel #${data.room}` });
  } else if (t === 'member_list') {
    if (data.room === currentRoom) {
      updateMembers(data.members);
    }
  } else if (t === 'invite_code') {
    const mins = Math.floor(data.expires / 60);
    addMessage({ type: 'system', text: `Temporary invitation token allocated for #${data.room} (Valid ${mins}m)` });
    addMessage({ type: 'code', text: data.code });
  } else if (t === 'message' || t === 'system' || t === 'error') {
    addMessage(data);
  } else if (t === 'refresh_history') {
    if (currentRoom === data.room) {
      send({ type: 'join_name', room: currentRoom });
    }
  }
}

function updateRooms(rooms) {
  roomListDiv.innerHTML = '';
  if (!rooms || rooms.length === 0) {
    roomListDiv.innerHTML = '<div class="sidebar-item" style="opacity: 0.5">No channels active</div>';
    return;
  }
  rooms.forEach(r => {
    const el = document.createElement('div');
    el.className = 'sidebar-item' + (r === currentRoom ? ' active' : '');
    el.textContent = '#' + r;
    el.onclick = () => {
      send({ type: 'join_name', room: r });
      // Close sidebar on mobile after joining
      sidebar.classList.remove('open');
      sidebarOverlay.classList.remove('active');
    };
    roomListDiv.appendChild(el);
  });
}

function updateMembers(members) {
  memberListDiv.innerHTML = '';
  memberCountSpan.textContent = members ? members.length : 0;
  if (!members || members.length === 0) {
    memberListDiv.innerHTML = '<div class="sidebar-item" style="opacity: 0.5">Empty room context</div>';
    return;
  }
  members.forEach(m => {
    const el = document.createElement('div');
    el.className = 'sidebar-item';
    el.textContent = m;
    memberListDiv.appendChild(el);
  });
}

messageForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = messageInput.value.trim();
  if (!text) return;
  
  if (text.startsWith('/')) {
    const parts = text.substring(1).split(' ');
    const cmd = parts[0].toLowerCase();
    const arg = parts.slice(1).join(' ').trim();
    
    if (cmd === 'create') {
      if (!arg) addMessage({ type: 'error', text: 'Syntax checking validation error. Correct usage: /create <name>' });
      else send({ type: 'create_room', room: arg });
    } else if (cmd === 'invite') {
      send({ type: 'gen_invite' });
    } else if (cmd === 'join') {
      if (!arg) addMessage({ type: 'error', text: 'Syntax checking validation error. Correct usage: /join <code>' });
      else send({ type: 'join_room', code: arg.toUpperCase() });
    } else if (cmd === 'joinroom') {
      if (!arg) addMessage({ type: 'error', text: 'Syntax checking validation error. Correct usage: /joinroom <name>' });
      else send({ type: 'join_name', room: arg });
    } else if (cmd === 'leave') {
      send({ type: 'leave_room' });
      currentRoom = null;
      currentRoomSpan.textContent = 'DISCONNECTED';
      updateMembers([]);
    } else if (cmd === 'rooms') {
      send({ type: 'get_rooms' });
    } else if (cmd === 'members') {
      send({ type: 'get_members' });
    } else if (cmd === 'help') {
      addMessage({ type: 'system', text: '/create <name> - Instantiate a brand new server channel room' });
      addMessage({ type: 'system', text: '/invite - Generate a timed room access registration token' });
      addMessage({ type: 'system', text: '/join <code> - Connect to room using an active invite string' });
      addMessage({ type: 'system', text: '/joinroom <name> - Jump directly into an existing room name from history' });
      addMessage({ type: 'system', text: '/leave - Drop visibility access channel assignment context' });
      addMessage({ type: 'system', text: '/rooms - Query directory indexing for refreshed network list' });
      addMessage({ type: 'system', text: '/members - Force synchronized client mapping audit trace' });
    } else {
      addMessage({ type: 'error', text: `Unparsed workspace console directive target: /${cmd}` });
    }
  } else {
    if (!currentRoom) {
      addMessage({ type: 'error', text: 'No target channel selected. Connect via invitation tracking code token or use /create' });
    } else {
      send({ type: 'message', text: text });
    }
  }
  
  messageInput.value = '';
});
