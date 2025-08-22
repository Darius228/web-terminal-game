console.log("[INIT] WebTerminal main_secure.js loaded");

// --- Инициализация Socket.IO ---
const socket = io({
    transports: ["websocket"],
    reconnection: true,
    reconnectionAttempts: 5,
    reconnectionDelay: 1000
});

let csrfToken = null;

// --- Логирование всех событий Socket.IO ---
const _onevent = socket.onevent;
socket.onevent = function(packet) {
    const args = packet.data || [];
    console.log("[SOCKET EVENT]", args[0], args[1] || "");
    _onevent.call(this, packet);
};

// --- Автоматическая вставка CSRF-токена ---
const _origEmit = socket.emit.bind(socket);
socket.emit = function(event, ...args) {
    if (!csrfToken) {
        console.warn("[CSRF] Токен не получен, отправляем без него:", event);
    }
    if (args.length === 0) {
        args = [ { csrf: csrfToken } ];
    } else if (typeof args[0] === "object" && args[0] !== null && !Array.isArray(args[0])) {
        args[0] = Object.assign({}, args[0], { csrf: csrfToken });
    } else {
        args.unshift({ csrf: csrfToken });
    }
    console.log("[SOCKET EMIT]", event, args[0]);
    return _origEmit(event, ...args);
};

// --- Получение CSRF-токена ---
socket.on("csrf_token", (data) => {
    csrfToken = data.token;
    console.log("[CSRF] token received:", csrfToken);
});

// --- Обновление UI по роли ---
socket.on("update_ui_state", (data) => {
    console.log("[UI STATE]", data);

    const loadingScreen = document.querySelector("#loadingScreen");
    const uiPanel = document.querySelector("#uiPanel");

    if (data.show_ui_panel) {
        if (loadingScreen) loadingScreen.style.display = "none";
        if (uiPanel) uiPanel.style.display = "block";
    } else {
        if (uiPanel) uiPanel.style.display = "none";
        if (loadingScreen) loadingScreen.style.display = "flex";
    }
});

// --- Логирование подключения и ошибок ---
socket.on("connect", () => {
    console.log("[SOCKET] Connected to server");
});

socket.on("disconnect", (reason) => {
    console.warn("[SOCKET] Disconnected:", reason);
});

socket.on("connect_error", (err) => {
    console.error("[SOCKET] Connection error:", err);
});

// --- Вывод сообщений в терминал ---
socket.on("terminal_output", (data) => {
    if (data && data.output) {
        const terminal = document.querySelector("#terminalOutput");
        if (terminal) {
            terminal.value += data.output;
            terminal.scrollTop = terminal.scrollHeight;
        }
    }
});

// --- Обработка кнопок и команд ---
document.addEventListener("DOMContentLoaded", () => {
    console.log("[INIT] DOM fully loaded");

    const inputField = document.querySelector("#commandInput");
    const sendBtn = document.querySelector("#sendBtn");

    if (sendBtn && inputField) {
        sendBtn.addEventListener("click", () => {
            const command = inputField.value.trim();
            if (command.length > 0) {
                console.log("[COMMAND] Sending:", command);
                socket.emit("sendmsg", { message: command });
                inputField.value = "";
            }
        });
    }

    if (inputField) {
        inputField.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                sendBtn.click();
            }
        });
    }
});
