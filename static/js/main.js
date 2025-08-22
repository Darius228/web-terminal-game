// main_secure.js
// Клиентская часть с автоматической CSRF и безопасной отправкой событий.
// Сохраняет твою логику, просто прокладывает «прокси-слой» вокруг socket.emit.

(function(){
  const socket = io({
    transports: ["websocket"],
    reconnection: true,
    reconnectionAttempts: 10,
    reconnectionDelay: 1000,
  });

  window.socket = socket;

  let csrfToken = null;

  socket.on("csrf_token", (data) => {
    csrfToken = data && data.token;
    console.log("[CSRF] token received:", csrfToken);
  });

  // Обёртка: вставляет csrf в первый аргумент (если объект), либо подставляет новый объект
  const originalEmit = socket.emit.bind(socket);
  socket.emit = function(event, ...args) {
    // Пропускаем системные события, но они у нас и не вызываются вручную
    if (event !== "connect" && event !== "disconnect") {
      if (!csrfToken) {
        console.warn("[CSRF] token not ready for event:", event);
      }
      if (args.length === 0) {
        args = [ { csrf: csrfToken } ];
      } else if (typeof args[0] === "object" && args[0] !== null && !Array.isArray(args[0])) {
        args[0] = Object.assign({}, args[0], { csrf: csrfToken });
      } else {
        args.unshift({ csrf: csrfToken });
      }
    }
    return originalEmit(event, ...args);
  };

  // ---------------- UI-хуки (оставь под свою разметку) ----------------
  const term = document.querySelector("#terminalOutput");
  function printLine(s){
    if (!term) return;
    term.value += s;
    term.scrollTop = term.scrollHeight;
  }

  socket.on("terminal_output", (data) => {
    if (data && data.output) printLine(data.output);
  });

  socket.on("update_ui_state", (data) => {
    const panel = document.querySelector("#uiPanel");
    if (panel) panel.style.display = data.show_ui_panel ? "block" : "none";
  });

  socket.on("connect_error", (err) => {
    console.error("connect_error:", err && err.message);
  });

  socket.on("disconnect", () => {
    console.warn("socket disconnected");
  });

  // Пример: кнопка отправки сообщения
  const sendBtn = document.querySelector("#sendMessage");
  const msgInput = document.querySelector("#messageInput");
  if (sendBtn && msgInput) {
    sendBtn.addEventListener("click", () => {
      const msg = (msgInput.value || "").trim();
      if (msg) {
        socket.emit("sendmsg", { message: msg });
        msgInput.value = "";
      }
    });
  }

  // Пример: форма логина
  const loginForm = document.querySelector("#loginForm");
  if (loginForm) {
    loginForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const uid = loginForm.querySelector("[name=uid]").value.trim();
      const key = loginForm.querySelector("[name=key]").value.trim();
      socket.emit("login", { uid, key });
    });
  }
})();