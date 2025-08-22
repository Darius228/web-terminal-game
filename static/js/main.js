// === main_secure.js (fixed) ===
// Основан на твоём старом main.js. Исправлена ключевая ошибка: событие
// `update_ui_state` приходило ДО загрузки DOM, из-за чего элементы не находились
// и экран оставался на «ИНИЦИАЛИЗАЦИЯ СИСТЕМЫ…». Теперь состояние UI
// безопасно откладывается и применяется после DOMContentLoaded.

console.log("[INIT] WebTerminal main_secure.js loaded");

// === Socket.IO ===
const socket = io({
  transports: ["websocket"],
  reconnection: true,
  reconnectionAttempts: 5,
  reconnectionDelay: 1000
});

let csrfToken = null;
let pendingUiState = null; // сюда положим состояние, если DOM ещё не готов

// === Логирование ВСЕХ входящих событий ===
const _onevent = socket.onevent;
socket.onevent = function (packet) {
  const args = packet.data || [];
  console.log("[SOCKET EVENT]", args[0], args[1] || "");
  _onevent.call(this, packet);
};

// === Автоприкрепление CSRF к emit ===
const _origEmit = socket.emit.bind(socket);
socket.emit = function (event, ...args) {
  if (csrfToken) {
    if (args.length === 0) {
      args = [{ csrf: csrfToken }];
    } else if (typeof args[0] === "object" && args[0] !== null && !Array.isArray(args[0])) {
      args[0] = Object.assign({}, args[0], { csrf: csrfToken });
    } else {
      args.unshift({ csrf: csrfToken });
    }
  } else {
    console.warn("[CSRF] токен ещё не получен, отправляем без него:", event);
  }
  return _origEmit(event, ...args);
};

// === Получение CSRF-токена ===
socket.on("csrf_token", (data) => {
  csrfToken = data.token;
  console.log("[CSRF] token received:", csrfToken);
});

// === Утилиты работы с DOM ===
function firstSel(selectors) {
  for (const s of selectors) {
    const el = document.querySelector(s);
    if (el) return el;
  }
  return null;
}

function applyUiState(data) {
  // Ищем элементы каждый раз (не кэшируем), чтобы не зависеть от момента загрузки
  const loading = firstSel(["#loadingScreen", ".loading-screen", "#init", "#preloader", "#init-screen"]);
  const login   = firstSel(["#loginScreen", ".login-screen", "#authScreen", "#auth", "#login", "#loginPanel", "#login-form"]);
  const panel   = firstSel(["#uiPanel", ".ui-panel", "#panel", "#mainPanel"]);

  const haveDom = !!(loading || login || panel);
  if (!haveDom) {
    console.log("[UI] DOM ещё не готов — отложили state", data);
    return false; // сообщаем вызывающему, что пока применить не к чему
  }

  console.log("[UI] applying state", data, { loading: !!loading, login: !!login, panel: !!panel });

  if (data.show_ui_panel) {
    if (loading) loading.style.display = "none";
    if (login)   login.style.display   = "none";
    if (panel)   panel.style.display   = "block";
  } else {
    // Показываем экран логина, скрываем остальное
    if (panel)   panel.style.display   = "none";
    if (loading) loading.style.display = "none"; // убираем вечную инициализацию
    if (login)   login.style.display   = "flex";  // по умолчанию логин — flex
  }
  return true;
}

// === Сервер сообщает состояние UI ===
socket.on("update_ui_state", (data) => {
  console.log("[UI STATE]", data);
  // Пытаемся применить сразу; если элементов ещё нет — отложим
  if (!applyUiState(data)) {
    pendingUiState = data;
  }
});

// === Подключение/ошибки ===
socket.on("connect", () => {
  console.log("[SOCKET] Connected to server");
});

socket.on("disconnect", (reason) => {
  console.warn("[SOCKET] Disconnected:", reason);
});

socket.on("connect_error", (err) => {
  console.error("[SOCKET] Connection error:", err);
});

// === Поток вывода терминала ===
socket.on("terminal_output", (data) => {
  if (data && data.output) {
    const terminal = firstSel(["#terminalOutput", ".terminal-output"]);
    if (terminal) {
      terminal.value += data.output;
      terminal.scrollTop = terminal.scrollHeight;
    }
  }
});

// === Когда DOM готов — применяем отложенное состояние и вешаем обработчики ===
document.addEventListener("DOMContentLoaded", () => {
  console.log("[INIT] DOM fully loaded");

  // Если до этого пришёл update_ui_state — применим его сейчас
  if (pendingUiState) {
    applyUiState(pendingUiState);
    pendingUiState = null;
  }

  // --- Логин ---
  const uidInput  = firstSel(["#uidInput", "#uid", "input[name=uid]"]); 
  const keyInput  = firstSel(["#keyInput", "#key", "input[name=key]"]); 
  const loginBtn  = firstSel(["#loginBtn", "#login-button", "button[data-action=login]"]); 

  if (loginBtn) {
    loginBtn.addEventListener("click", () => {
      const uid = (uidInput?.value || "").trim();
      const key = (keyInput?.value || "").trim();
      if (!uid || !key) {
        alert("Введите UID и Ключ доступа");
        return;
        }
      console.log("[LOGIN] Attempting login:", uid);
      socket.emit("login", { uid, key });
    });
  }

  if (keyInput) {
    keyInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") loginBtn?.click();
    });
  }

  // --- Отправка команд ---
  const inputField = firstSel(["#commandInput", ".command-input"]);
  const sendBtn    = firstSel(["#sendBtn", "#send", "button[data-action=send]"]); 

  if (sendBtn && inputField) {
    sendBtn.addEventListener("click", () => {
      const command = inputField.value.trim();
      if (command.length > 0) {
        console.log("[COMMAND] Sending:", command);
        socket.emit("sendmsg", { message: command });
        inputField.value = "";
      }
    });

    inputField.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        sendBtn.click();
      }
    });
  }
});
