// === main_secure.js ===
// Обновлённая версия твоего старого main.js
// Сохранена вся логика экранов и логина, добавлена защита и улучшена стабильность.

console.log("[INIT] WebTerminal main_secure.js loaded");

// === Инициализация Socket.IO ===
const socket = io({
    transports: ["websocket"],
    reconnection: true,
    reconnectionAttempts: 5,
    reconnectionDelay: 1000
});

let csrfToken = null;

// === Логирование всех входящих событий ===
const _onevent = socket.onevent;
socket.onevent = function (packet) {
    const args = packet.data || [];
    console.log("[SOCKET EVENT]", args[0], args[1] || "");
    _onevent.call(this, packet);
};

// === Автоматическая вставка CSRF-токена ===
const _origEmit = socket.emit.bind(socket);
socket.emit = function (event, ...args) {
    if (csrfToken) {
        if (args.length === 0) {
            args = [{ csrf: csrfToken }];
        } else if (typeof args[0] === "object" && args[0] !== null) {
            args[0] = Object.assign({}, args[0], { csrf: csrfToken });
        } else {
            args.unshift({ csrf: csrfToken });
        }
    }
    return _origEmit(event, ...args);
};

// === Получение CSRF-токена ===
socket.on("csrf_token", (data) => {
    csrfToken = data.token;
    console.log("[CSRF] token received:", csrfToken);
});

// === Экран инициализации ===
const loadingScreen = document.querySelector("#loading-screen"); // Исправлено на "-screen"
const loginScreen = document.querySelector("#loginScreen");     // Оставляем как есть, но сейчас добавим HTML
const uiPanel = document.querySelector("#main-terminal-container"); // Указываем на существующий контейнер терминала

// === main.js ===
// ЗАМЕНИТЕ СТАРЫЙ ОБРАБОТЧИК `update_ui_state` НА ЭТОТ

socket.on("update_ui_state", (data) => {
    console.log("[UI STATE]", data);

    // Убедимся, что все элементы найдены, прежде чем что-то с ними делать
    if (!loadingScreen || !loginScreen || !uiPanel) {
        console.error("Один или несколько UI-элементов не найдены в HTML!");
        return;
    }

    if (data.show_ui_panel) {
        // Показываем главный интерфейс
        loadingScreen.classList.add("hidden");
        loginScreen.classList.add("hidden");
        uiPanel.classList.remove("hidden");
    } else {
        // Показываем экран логина
        loadingScreen.classList.add("hidden");
        uiPanel.classList.add("hidden");
        loginScreen.classList.remove("hidden");
    }
});

// === Логирование подключения и ошибок ===
socket.on("connect", () => {
    console.log("[SOCKET] Connected to server");
});

socket.on("disconnect", (reason) => {
    console.warn("[SOCKET] Disconnected:", reason);
});

socket.on("connect_error", (err) => {
    console.error("[SOCKET] Connection error:", err);
});

// === Сообщения терминала ===
socket.on("terminal_output", (data) => {
    if (data && data.output) {
        const terminal = document.querySelector("#terminalOutput");
        if (terminal) {
            terminal.value += data.output;
            terminal.scrollTop = terminal.scrollHeight;
        }
    }
});

// === Форма логина ===
document.addEventListener("DOMContentLoaded", () => {
    console.log("[INIT] DOM fully loaded");

    const uidInput = document.querySelector("#uidInput");
    const keyInput = document.querySelector("#keyInput");
    const loginBtn = document.querySelector("#loginBtn");

    if (loginBtn) {
        loginBtn.addEventListener("click", () => {
            const uid = uidInput.value.trim();
            const key = keyInput.value.trim();

            if (uid.length === 0 || key.length === 0) {
                alert("Введите UID и Ключ доступа");
                return;
            }

            console.log("[LOGIN] Attempting login:", uid);
            socket.emit("login", { uid, key });
        });
    }

    keyInput?.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            loginBtn.click();
        }
    });
});

// === Отправка команд ===
document.addEventListener("DOMContentLoaded", () => {
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

        inputField.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                sendBtn.click();
            }
        });
    }
});