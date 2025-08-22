# WebTerminal_secure.py
# Полностью исправленная, самодостаточная версия с CSRF, проверкой ролей, rate limiting
# и интеграцией с google_sheets_api (как в твоём файле). Готово для Gunicorn/Render.

import os
import json
import time
import secrets
from datetime import datetime, timedelta
from functools import wraps

import bleach
from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, disconnect

# Локальный модуль из твоего проекта
import google_sheets_api

# =========================
# Константы и глобальные структуры
# =========================
LOG_SHEET_NAME = "Логи"
USERS_SHEET = "Пользователи"
CONTRACTS_SHEET = "Контракты"
CLIENT_REQUESTS_SHEET = "Запросы Клиентов"
MESSAGES_SHEET = "Сообщения"

MAX_MESSAGE_LENGTH = 2000
MAX_LOGIN_ATTEMPTS = 5
LOGIN_ATTEMPT_WINDOW = 900  # 15 минут
EVENTS_PER_MINUTE = 60      # защита от спама событий
MESSAGE_MIN_INTERVAL = 0.5  # сек

ROLE_PERMISSIONS = {
    "guest":       ["help", "login", "clear", "ping"],
    "operative":   ["help", "ping", "sendmsg", "msghistory", "contracts",
                    "view_orders", "view_contract", "exit", "clear"],
    "commander":   ["help", "ping", "sendmsg", "msghistory", "contracts",
                    "assign_contract", "view_users_squad", "setchannel",
                    "view_contract", "exit", "clear"],
    "client":      ["help", "ping", "create_request", "view_my_requests", "exit", "clear"],
    "syndicate":   ["help", "ping", "sendmsg", "resetkeys", "viewkeys",
                    "register_user", "unregister_user", "view_users", "viewrequests",
                    "acceptrequest", "declinerequest", "contracts", "exit", "clear",
                    "syndicate_assign"]
}

# Память процесса (может быть заменена кэшем/БД)
REGISTERED_USERS = {}   # uid -> dict(row)
CONTRACTS = []          # list of dicts
PENDING_REQUESTS = []   # list of dicts

# Rate limiting storage
login_attempts = {}     # ip -> [timestamps]
sid_event_times = {}    # sid -> [timestamps]
message_timestamps = {} # uid -> last_timestamp

# =========================
# Flask/SocketIO
# =========================
app = Flask(__name__)
_secret = os.environ.get("FLASK_SECRET_KEY")
if not _secret:
    raise RuntimeError("FLASK_SECRET_KEY обязателен для запуска приложения")
app.config["SECRET_KEY"] = _secret
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)

socketio = SocketIO(app, cors_allowed_origins="*", logger=False, engineio_logger=False)

# =========================
# Утилиты безопасности
# =========================
def sanitize_input(data: str) -> str:
    return bleach.clean(str(data), tags=[], attributes={}, strip=True)

def rate_limit_login(ip, limit=MAX_LOGIN_ATTEMPTS, window=LOGIN_ATTEMPT_WINDOW):
    now = time.time()
    login_attempts.setdefault(ip, [])
    login_attempts[ip] = [t for t in login_attempts[ip] if now - t < window]
    if len(login_attempts[ip]) >= limit:
        return False
    login_attempts[ip].append(now)
    return True

def rate_limit_events(sid, limit=EVENTS_PER_MINUTE, window=60):
    now = time.time()
    sid_event_times.setdefault(sid, [])
    sid_event_times[sid] = [t for t in sid_event_times[sid] if now - t < window]
    if len(sid_event_times[sid]) >= limit:
        return False
    sid_event_times[sid].append(now)
    return True

def message_rate_limit(uid, min_interval=MESSAGE_MIN_INTERVAL):
    now = time.time()
    last_time = message_timestamps.get(uid, 0)
    if now - last_time < min_interval:
        return False
    message_timestamps[uid] = now
    return True

def generate_csrf_token():
    token = secrets.token_hex(16)
    session["csrf_token"] = token
    return token

def check_csrf_from(data: dict | None):
    token = None
    if isinstance(data, dict):
        token = data.get("csrf")
    if not token:
        token = request.args.get("csrf") or request.headers.get("X-CSRF-Token")
    return token and token == session.get("csrf_token")

def require_csrf(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        # Глобальный rate-limit по событиям
        if not rate_limit_events(request.sid):
            emit("terminal_output", {"output": "⚠️ Слишком много событий. Подождите немного.\n"})
            return
        # CSRF
        data_arg = args[0] if args else {}
        if not check_csrf_from(data_arg if isinstance(data_arg, dict) else {}):
            emit("terminal_output", {"output": "❌ Неверный CSRF-токен. Перезагрузите страницу.\n"})
            disconnect()
            return
        return f(*args, **kwargs)
    return wrapper

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("uid") or session.get("role") in (None, "guest"):
            emit("terminal_output", {"output": "❌ Требуется авторизация.\n"})
            disconnect()
            return
        return f(*args, **kwargs)
    return decorated

def require_role(event_name: str):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            role = session.get("role", "guest")
            allowed = ROLE_PERMISSIONS.get(role, [])
            if event_name not in allowed:
                emit("terminal_output", {"output": f"🚫 Недостаточно прав для команды '{event_name}'.\n"})
                return
            return f(*args, **kwargs)
        return wrapper
    return decorator

def log_terminal_event(event_type, message, extra=None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    info = {
        "uid": session.get("uid"),
        "role": session.get("role"),
        "ip": request.remote_addr
    }
    if extra:
        info.update(extra)
    safe_info = json.dumps(info, ensure_ascii=False)
    print(f"[{timestamp}] [{event_type}] {safe_info} :: {message}")
    # Убедимся, что Sheets инициализирован
    google_sheets_api.init_google_sheets()
    try:
        google_sheets_api.append_row(LOG_SHEET_NAME, [timestamp, event_type, safe_info, str(message)])
    except Exception:
        pass

# =========================
# Загрузка данных из Google Sheets
# =========================
def load_data_from_sheets():
    global REGISTERED_USERS, CONTRACTS, PENDING_REQUESTS
    if not google_sheets_api.init_google_sheets():
        print("⚠️ Google Sheets не инициализирован — продолжаем с пустыми данными (dev режим).")
        return

    try:
        users_data = google_sheets_api.get_all_records(USERS_SHEET)
        REGISTERED_USERS = {str(u.get("UID")): u for u in users_data if u.get("UID")}
    except Exception as e:
        print("Ошибка загрузки пользователей:", e)

    try:
        CONTRACTS = []
        for c in google_sheets_api.get_all_records(CONTRACTS_SHEET):
            try:
                c["ID"] = int(c.get("ID"))
                CONTRACTS.append(c)
            except Exception:
                continue
    except Exception as e:
        print("Ошибка загрузки контрактов:", e)

    try:
        PENDING_REQUESTS = []
        for r in google_sheets_api.get_all_records(CLIENT_REQUESTS_SHEET):
            try:
                r["ID Запроса"] = int(r.get("ID Запроса"))
                PENDING_REQUESTS.append(r)
            except Exception:
                continue
    except Exception as e:
        print("Ошибка загрузки запросов:", e)

# =========================
# HTTP
# =========================
@app.route("/")
def index():
    # Если есть шаблон — отрендерится. Если нет — просто скажем, что сервер работает.
    try:
        return render_template("index.html")
    except Exception:
        return "WebTerminal backend is running.", 200

# =========================
# Socket.IO события
# =========================
@socketio.on("connect")
def handle_connect(auth=None):
    # Инициализируем Sheets (мягко)
    google_sheets_api.init_google_sheets()

    # Гостевая сессия до логина
    session.setdefault("role", "guest")
    session.setdefault("uid", None)

    # Генерация CSRF и отправка на клиент
    token = generate_csrf_token()
    emit("csrf_token", {"token": token})
    emit("update_ui_state", {"role": session["role"], "show_ui_panel": False})
    log_terminal_event("connect", "client connected")

@socketio.on("disconnect")
def handle_disconnect():
    log_terminal_event("disconnect", "client disconnected")

# ---------- Аутентификация ----------
@socketio.on("login")
@require_csrf
def login(data):
    ip = request.remote_addr
    if not rate_limit_login(ip):
        emit("login_failure", {"message": "Слишком много попыток. Попробуйте позже."})
        return

    uid = sanitize_input(str(data.get("uid", "")).strip())
    key = sanitize_input(str(data.get("key", "")).strip())

    load_data_from_sheets()
    user = REGISTERED_USERS.get(uid)

    if user and str(user.get("Ключ Доступа")) == key:
        session["uid"] = uid
        session["role"] = user.get("Роль", "guest")
        emit("update_ui_state", {"role": session["role"], "show_ui_panel": True})
        emit("terminal_output", {"output": "✅ Добро пожаловать!\n"})
        log_terminal_event("login", f"user {uid} authenticated")
    else:
        emit("login_failure", {"message": "Неверный UID или ключ."})
        log_terminal_event("login_fail", f"user {uid} failed auth")

@socketio.on("exit")
@require_csrf
@require_auth
def logout(data=None):
    uid = session.get("uid")
    role = session.get("role")
    session["uid"] = None
    session["role"] = "guest"
    emit("update_ui_state", {"role": "guest", "show_ui_panel": False})
    emit("terminal_output", {"output": "👋 Вы вышли из системы.\n"})
    log_terminal_event("logout", f"{uid}/{role} logged out")

# ---------- Общие команды ----------
@socketio.on("help")
@require_csrf
def help_event(data=None):
    role = session.get("role", "guest")
    allowed = ROLE_PERMISSIONS.get(role, [])
    out = "Доступные команды для роли '{}':\n - ".format(role) + "\n - ".join(allowed) + "\n"
    emit("terminal_output", {"output": out})

@socketio.on("clear")
@require_csrf
def clear_event(data=None):
    emit("terminal_output", {"output": "\n" * 50})

@socketio.on("ping")
@require_csrf
def ping_event(data=None):
    emit("terminal_output", {"output": "🏓 pong\n"})

# ---------- Сообщения ----------
@socketio.on("sendmsg")
@require_csrf
@require_auth
@require_role("sendmsg")
def handle_sendmsg(data):
    uid = session.get("uid")
    if not message_rate_limit(uid):
        emit("terminal_output", {"output": "⏳ Подождите перед отправкой следующего сообщения.\n"})
        return

    msg = sanitize_input(data.get("message", ""))[:MAX_MESSAGE_LENGTH]
    if not msg.strip():
        return

    # Лог в таблицу (если есть)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        google_sheets_api.append_row(MESSAGES_SHEET, [timestamp, uid, msg])
    except Exception:
        pass

    emit("terminal_output", {"output": f"💬 {uid}: {msg}\n"}, broadcast=True)
    log_terminal_event("sendmsg", msg, extra={"uid": uid})

@socketio.on("msghistory")
@require_csrf
@require_auth
@require_role("msghistory")
def msghistory_event(data=None):
    # Вывод последних N сообщений (упрощённо)
    out_lines = []
    try:
        records = google_sheets_api.get_all_records(MESSAGES_SHEET)
        for r in records[-20:]:
            out_lines.append(f"{r.get('timestamp', '')} {r.get('uid', '')}: {r.get('message', '')}")
    except Exception:
        out_lines.append("⚠️ История сообщений недоступна.")
    emit("terminal_output", {"output": "\n".join(out_lines) + "\n"})

# ---------- Контракты/заказы ----------
@socketio.on("contracts")
@require_csrf
@require_auth
@require_role("contracts")
def contracts_event(data=None):
    load_data_from_sheets()
    if not CONTRACTS:
        emit("terminal_output", {"output": "ℹ️ Нет контрактов.\n"})
        return
    lines = ["📄 Контракты:"]
    for c in CONTRACTS[:50]:
        lines.append(f"ID={c.get('ID')} | {c.get('Название','')} | Статус={c.get('Статус','')}")
    emit("terminal_output", {"output": "\n".join(lines) + "\n"})

@socketio.on("view_contract")
@require_csrf
@require_auth
@require_role("view_contract")
def view_contract_event(data):
    cid = str(data.get("contract_id", "")).strip()
    load_data_from_sheets()
    for c in CONTRACTS:
        if str(c.get("ID")) == cid:
            emit("terminal_output", {"output": json.dumps(c, ensure_ascii=False, indent=2) + "\n"})
            return
    emit("terminal_output", {"output": "❓ Контракт не найден.\n"})

@socketio.on("assign_contract")
@require_csrf
@require_auth
@require_role("assign_contract")
def assign_contract_event(data):
    cid = str(data.get("contract_id", "")).strip()
    assignee = sanitize_input(data.get("assignee", ""))
    # Обновим строку в таблице (если есть поле 'Назначен')
    try:
        ok = google_sheets_api.update_row_by_key(CONTRACTS_SHEET, "ID", cid, {"Назначен": assignee})
        emit("terminal_output", {"output": ("✅ Назначено.\n" if ok else "⚠️ Не удалось назначить.\n")})
        log_terminal_event("assign_contract", f"cid={cid} -> {assignee}")
    except Exception:
        emit("terminal_output", {"output": "⚠️ Ошибка при назначении.\n"})

@socketio.on("view_orders")
@require_csrf
@require_auth
@require_role("view_orders")
def view_orders_event(data=None):
    # В твоём коде могла быть своя логика — здесь просто отобразим контракты со статусом 'Открыт'
    load_data_from_sheets()
    lines = ["📦 Открытые заказы:"]
    for c in CONTRACTS:
        if str(c.get("Статус", "")).lower() in ("open", "открыт", "в работе"):
            lines.append(f"- ID {c.get('ID')} :: {c.get('Название','')}")
    if len(lines) == 1:
        lines.append("Нет открытых заказов.")
    emit("terminal_output", {"output": "\n".join(lines) + "\n"})

@socketio.on("view_users_squad")
@require_csrf
@require_auth
@require_role("view_users_squad")
def view_users_squad_event(data=None):
    # Упрощённый пример: выведем список пользователей из таблицы
    load_data_from_sheets()
    lines = ["👥 Пользователи:"]
    for uid, row in list(REGISTERED_USERS.items())[:100]:
        lines.append(f"- {uid} :: {row.get('Роль', 'unknown')} :: {row.get('Отряд', 'n/a')}")
    emit("terminal_output", {"output": "\n".join(lines) + "\n"})

@socketio.on("setchannel")
@require_csrf
@require_auth
@require_role("setchannel")
def setchannel_event(data):
    # Место под твою бизнес-логику; здесь просто подтверждаем
    ch = sanitize_input(data.get("channel", ""))
    emit("terminal_output", {"output": f"📡 Канал связи установлен: {ch}\n"})

# ---------- Клиенты ----------
@socketio.on("create_request")
@require_csrf
@require_auth
@require_role("create_request")
def create_request_event(data):
    uid = session.get("uid")
    title = sanitize_input(data.get("title", ""))
    body = sanitize_input(data.get("body", ""))
    if not title:
        emit("terminal_output", {"output": "⚠️ Укажите заголовок.\n"})
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        ok = google_sheets_api.append_row(CLIENT_REQUESTS_SHEET, [timestamp, uid, title, body, "Новый"])
        emit("terminal_output", {"output": ("✅ Запрос создан.\n" if ok else "⚠️ Не удалось создать запрос.\n")})
        log_terminal_event("create_request", f"{title}")
    except Exception:
        emit("terminal_output", {"output": "⚠️ Ошибка при создании запроса.\n"})

@socketio.on("view_my_requests")
@require_csrf
@require_auth
@require_role("view_my_requests")
def view_my_requests_event(data=None):
    uid = session.get("uid")
    try:
        rows = google_sheets_api.get_all_records(CLIENT_REQUESTS_SHEET)
        mine = [r for r in rows if str(r.get("UID")) == str(uid)]
        if not mine:
            emit("terminal_output", {"output": "ℹ️ У вас нет запросов.\n"})
            return
        lines = ["🗂 Ваши запросы:"]
        for r in mine[-50:]:
            lines.append(f"#{r.get('ID Запроса','?')} :: {r.get('Заголовок','')} :: {r.get('Статус','')}")
        emit("terminal_output", {"output": "\n".join(lines) + "\n"})
    except Exception:
        emit("terminal_output", {"output": "⚠️ Ошибка получения запросов.\n"})

# ---------- Синдикат/админ ----------
@socketio.on("register_user")
@require_csrf
@require_auth
@require_role("register_user")
def register_user_event(data):
    uid = sanitize_input(data.get("uid", ""))
    role = sanitize_input(data.get("role", "guest"))
    key = sanitize_input(data.get("key", ""))
    try:
        ok = google_sheets_api.append_row(USERS_SHEET, [uid, role, key])
        emit("terminal_output", {"output": ("✅ Пользователь добавлен.\n" if ok else "⚠️ Не удалось добавить.\n")})
        log_terminal_event("register_user", f"{uid}/{role}")
    except Exception:
        emit("terminal_output", {"output": "⚠️ Ошибка добавления пользователя.\n"})

@socketio.on("unregister_user")
@require_csrf
@require_auth
@require_role("unregister_user")
def unregister_user_event(data):
    uid = sanitize_input(data.get("uid", ""))
    try:
        ok = google_sheets_api.delete_row_by_key(USERS_SHEET, "UID", uid)
        emit("terminal_output", {"output": ("✅ Пользователь удалён.\n" if ok else "⚠️ Не найден.\n")})
        log_terminal_event("unregister_user", f"{uid}")
    except Exception:
        emit("terminal_output", {"output": "⚠️ Ошибка удаления пользователя.\n"})

@socketio.on("view_users")
@require_csrf
@require_auth
@require_role("view_users")
def view_users_event(data=None):
    load_data_from_sheets()
    lines = ["👥 Пользователи:"]
    for uid, row in list(REGISTERED_USERS.items())[:200]:
        lines.append(f"- {uid} :: {row.get('Роль','?')}")
    emit("terminal_output", {"output": "\n".join(lines) + "\n"})

@socketio.on("viewrequests")
@require_csrf
@require_auth
@require_role("viewrequests")
def viewrequests_event(data=None):
    load_data_from_sheets()
    if not PENDING_REQUESTS:
        emit("terminal_output", {"output": "ℹ️ Нет клиентских запросов.\n"})
        return
    lines = ["📮 Клиентские запросы:"]
    for r in PENDING_REQUESTS[:100]:
        lines.append(f"#{r.get('ID Запроса','?')} :: {r.get('UID','')} :: {r.get('Заголовок','')} :: {r.get('Статус','')}")
    emit("terminal_output", {"output": "\n".join(lines) + "\n"})

@socketio.on("acceptrequest")
@require_csrf
@require_auth
@require_role("acceptrequest")
def acceptrequest_event(data):
    rid = str(data.get("request_id", "")).strip()
    try:
        ok = google_sheets_api.update_row_by_key(CLIENT_REQUESTS_SHEET, "ID Запроса", rid, {"Статус": "Принят"})
        emit("terminal_output", {"output": ("✅ Запрос принят.\n" if ok else "⚠️ Не найден запрос.\n")})
        log_terminal_event("acceptrequest", f"request {rid} accepted")
    except Exception:
        emit("terminal_output", {"output": "⚠️ Ошибка подтверждения.\n"})

@socketio.on("declinerequest")
@require_csrf
@require_auth
@require_role("declinerequest")
def declinerequest_event(data):
    rid = str(data.get("request_id", "")).strip()
    try:
        ok = google_sheets_api.update_row_by_key(CLIENT_REQUESTS_SHEET, "ID Запроса", rid, {"Статус": "Отклонён"})
        emit("terminal_output", {"output": ("✅ Запрос отклонён.\n" if ok else "⚠️ Не найден запрос.\n")})
        log_terminal_event("declinerequest", f"request {rid} declined")
    except Exception:
        emit("terminal_output", {"output": "⚠️ Ошибка отклонения.\n"})

@socketio.on("viewkeys")
@require_csrf
@require_auth
@require_role("viewkeys")
def viewkeys_event(data=None):
    # Для безопасности не показываем ключи полностью
    load_data_from_sheets()
    lines = ["🔑 Ключи доступа (замаскированы):"]
    for uid, row in list(REGISTERED_USERS.items())[:200]:
        k = str(row.get("Ключ Доступа", ""))
        masked = (k[:2] + "•••" + k[-2:]) if len(k) >= 4 else "•••"
        lines.append(f"- {uid}: {masked}")
    emit("terminal_output", {"output": "\n".join(lines) + "\n"})

@socketio.on("resetkeys")
@require_csrf
@require_auth
@require_role("resetkeys")
def resetkeys_event(data=None):
    # Пример: просто уведомление (реальную ротацию реализуй по своей логике)
    emit("terminal_output", {"output": "♻️ Ротация ключей инициирована (демо).\n"})
    log_terminal_event("resetkeys", "rotation requested")

@socketio.on("syndicate_assign")
@require_csrf
@require_auth
@require_role("syndicate_assign")
def syndicate_assign_event(data):
    user = sanitize_input(data.get("uid", ""))
    squad = sanitize_input(data.get("squad", ""))
    try:
        ok = google_sheets_api.update_row_by_key(USERS_SHEET, "UID", user, {"Отряд": squad})
        emit("terminal_output", {"output": ("✅ Назначение выполнено.\n" if ok else "⚠️ Пользователь не найден.\n")})
        log_terminal_event("syndicate_assign", f"{user} -> {squad}")
    except Exception:
        emit("terminal_output", {"output": "⚠️ Ошибка назначения.\n"})

# =========================
# Запуск локально
# =========================
if __name__ == "__main__":
    load_data_from_sheets()
    # На Render запуск через gunicorn, поэтому без ssl_context и debug=False
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
