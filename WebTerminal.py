# WebTerminal.py

import os
import json
import secrets
from datetime import datetime, timedelta
from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room

# Импортируем наш модуль для работы с Google Таблицами
import google_sheets_api

# --- НОВЫЕ КОНСТАНТЫ ---
LOG_SHEET_NAME = "Логи"
MESSAGES_SHEET_NAME = "Сообщения" # Название нового листа для сообщений

# --- Глобальные переменные и константы ---
ROLE_PERMISSIONS = {
    "guest": ["help", "login", "clear", "ping"],
    # --- ИЗМЕНЕНИЕ: Добавлена команда msghistory ---
    "operative": ["help", "ping", "sendmsg", "msghistory", "contracts", "view_orders", "view_contract", "exit", "clear"],
    "commander": ["help", "ping", "sendmsg", "msghistory", "contracts", "assign_contract", "view_users_squad", "setchannel", "view_contract", "exit", "clear"],
    "client": ["help", "ping", "create_request", "view_my_requests", "exit", "clear"],
    "syndicate": [
        "help", "ping", "sendmsg", "resetkeys", "viewkeys", "register_user",
        "unregister_user", "view_users", "viewrequests", "acceptrequest",
        "declinerequest", "contracts", "exit", "clear", "syndicate_assign"
    ]
}
COMMAND_DESCRIPTIONS = {
    "help": "Отображает список доступных команд.",
    "login": "Вход в систему. login <UID> <ключ>",
    "clear": "Очищает окно терминала.",
    "ping": "Проверяет соединение.",
    "sendmsg": "Отправляет сообщение. sendmsg <сообщение> | sendmsg <UID> <сообщение>",
    # --- ИЗМЕНЕНИЕ: Добавлено описание для msghistory ---
    "msghistory": "Показывает последние 20 сообщений в чате вашего отряда.",
    "contracts": "Просмотр всех активных и назначенных контрактов.",
    "view_contract": "Просмотр деталей контракта. view_contract <ID_контракта>",
    "view_orders": "Просмотр ваших контрактов.",
    "assign_contract": "Назначить контракт оперативнику (или себе). assign_contract <ID_контракта> <UID>",
    "view_users_squad": "Просмотр оперативников в отряде.",
    "setchannel": "Установить новую частоту отряда. setchannel <частота>",
    "create_request": "Создать запрос. create_request <ID_Discord> <Причина> <Текст запроса>",
    "view_my_requests": "Просмотр ваших запросов.",
    "resetkeys": "Сбросить ключи доступа. resetkeys <роль>",
    "viewkeys": "Просмотр текущих ключей доступа.",
    "register_user": "Зарегистрировать пользователя. register_user <ключ> <UID> <позывной> <отряд>",
    "unregister_user": "Деактивировать пользователя. unregister_user <UID>",
    "view_users": "Просмотр всех пользователей.",
    "viewrequests": "Просмотр запросов клиентов.",
    "acceptrequest": "Принять запрос. acceptrequest <ID> <название> <описание> <награда>",
    "declinerequest": "Отклонить запрос. declinerequest <ID>",
    "exit": "Выход из сессии.",
    "syndicate_assign": "Назначить контракт отряду(ам). syndicate_assign <ID> <alpha|beta|alpha,beta>"
}
ACCESS_KEYS = {}
KEY_TO_ROLE = {}
REGISTERED_USERS = {}
CONTRACTS = []
PENDING_REQUESTS = []
SQUAD_FREQUENCIES = {
    "alpha": "142.7 МГц",
    "beta": "148.8 МГц"
}
dossiers = {}
active_operatives = {}
active_users = {}

def log_terminal_event(event_type, user_info, message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    console_log_entry = f"[{timestamp}] [{event_type.upper()}] [Пользователь: {user_info}] {message}"
    print(console_log_entry)
    sheet_row_data = [timestamp, event_type.upper(), user_info, message]
    google_sheets_api.append_row(LOG_SHEET_NAME, sheet_row_data)

# --- НОВАЯ ФУНКЦИЯ: Запись сообщения в Google Таблицу ---
def log_message_to_sheet(sender_uid, sender_callsign, sender_squad, recipient_type, recipient_id, message_text):
    """Сохраняет отправленное сообщение в лист 'Сообщения'."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    message_row = [
        timestamp,
        sender_uid,
        sender_callsign,
        sender_squad,
        recipient_type,
        recipient_id,
        message_text
    ]
    google_sheets_api.append_row(MESSAGES_SHEET_NAME, message_row)


def load_access_keys():
    """Загружает ключи доступа из переменной окружения ACCESS_KEYS_JSON."""
    global ACCESS_KEYS, KEY_TO_ROLE
    keys_json_str = os.environ.get('ACCESS_KEYS_JSON')
    if not keys_json_str:
        print("❌ Ошибка: Переменная окружения 'ACCESS_KEYS_JSON' не найдена.")
        ACCESS_KEYS = {}
    else:
        try:
            ACCESS_KEYS = json.loads(keys_json_str)
        except json.JSONDecodeError:
            print("❌ Ошибка: Неверный формат JSON в переменной окружения 'ACCESS_KEYS_JSON'.")
            raise ValueError("Invalid ACCESS_KEYS_JSON format")
    KEY_TO_ROLE.clear()
    for role, keys_list in ACCESS_KEYS.items():
        for key in keys_list:
            KEY_TO_ROLE[key] = role

def load_data_from_sheets():
    """Загружает все необходимые данные из Google Таблиц в кэш."""
    global REGISTERED_USERS, CONTRACTS, PENDING_REQUESTS
    print("Загрузка данных из Google Таблиц...")
    users_data = google_sheets_api.get_all_records('Пользователи')
    REGISTERED_USERS = {str(user.get('UID')): user for user in users_data if user.get('UID')}
    CONTRACTS.clear()
    contracts_data = google_sheets_api.get_all_records('Контракты')
    for contract in contracts_data:
        try:
            contract['ID'] = int(contract.get('ID'))
            CONTRACTS.append(contract)
        except (ValueError, TypeError):
            continue
    PENDING_REQUESTS.clear()
    requests_data = google_sheets_api.get_all_records('Запросы Клиентов')
    for req in requests_data:
        try:
            req['ID Запроса'] = int(req.get('ID Запроса'))
            PENDING_REQUESTS.append(req)
        except (ValueError, TypeError):
            continue
    print("Данные успешно загружены.")

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a_very_temporary_secret_key_for_dev_only')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
socketio = SocketIO(app)

if not google_sheets_api.init_google_sheets():
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать Google Таблицы.")
load_access_keys()
load_data_from_sheets()

@app.route('/')
def index():
    return render_template('index.html')

# ... (остальные обработчики @socketio.on('connect'), @socketio.on('disconnect'), @socketio.on('login') остаются без изменений) ...
@socketio.on('connect')
def handle_connect():
    session['role'] = 'guest'
    session['uid'] = None
    session['callsign'] = None
    session['squad'] = None
    active_users[request.sid] = {'uid': None, 'callsign': None, 'role': 'guest', 'squad': None}
    emit('update_ui_state', {'role': 'guest', 'show_ui_panel': False, 'squad': None})
    log_terminal_event("connection", f"SID:{request.sid}", "Новое подключение.")

@socketio.on('disconnect')
def handle_disconnect():
    uid_disconnected = session.get('uid', 'N/A')
    callsign_disconnected = session.get('callsign', 'N/A')
    if request.sid in active_operatives:
        del active_operatives[request.sid]
    if request.sid in active_users:
        del active_users[request.sid]
    log_terminal_event("disconnection", f"UID:{uid_disconnected}, Callsign:{callsign_disconnected}, SID:{request.sid}", "Пользователь отключился.")

@socketio.on('login')
def login(data):
    uid = str(data.get('uid'))
    key = data.get('key')
    user_info = f"UID: {uid}, Key: {key}"
    load_data_from_sheets()
    if uid in REGISTERED_USERS and REGISTERED_USERS[uid].get("Ключ Доступа") == key:
        session['uid'] = uid
        session['role'] = REGISTERED_USERS[uid].get("Роль")
        session['callsign'] = REGISTERED_USERS[uid].get("Позывной")
        session['squad'] = REGISTERED_USERS[uid].get("Отряд")
        session.permanent = True
        active_users[request.sid] = {'uid': session['uid'], 'callsign': session['callsign'], 'role': session['role'], 'squad': session['squad']}
        if session['role'] in ["operative", "commander"]:
            active_operatives[request.sid] = {'uid': session['uid'], 'callsign': session['callsign'], 'squad': session['squad']}
            if session['squad'] and session['squad'].lower() != 'none':
                join_room(session['squad'])
        if session['role'] == "syndicate":
            join_room("syndicate_room")
        log_terminal_event("login_success", user_info, f"Пользователь '{session['callsign']}' успешно вошел как {session['role'].upper()}.")
        welcome_message = f"✅ Добро пожаловать, {session['callsign']}! Вы вошли как {session['role'].upper()}.\n"
        emit('terminal_output', {'output': welcome_message})
        ui_data = {'role': session['role'], 'callsign': session['callsign'], 'squad': session['squad'], 'show_ui_panel': True}
        if session['role'] == 'syndicate':
            ui_data['squad_frequencies'] = SQUAD_FREQUENCIES
            ui_data['channel_frequency'] = "Н/Д"
        else:
            ui_data['channel_frequency'] = SQUAD_FREQUENCIES.get(session.get('squad'), '--:--')
        emit('update_ui_state', ui_data, room=request.sid)
        return
    log_terminal_event("login_failure", user_info, "Попытка входа не удалась: неверный UID или ключ доступа.")
    emit('login_failure', {'message': "❌ Ошибка: Неверный UID или ключ доступа. Повторите попытку."}, room=request.sid)

@socketio.on('terminal_input')
def handle_terminal_input(data):
    global ROLE_PERMISSIONS, COMMAND_DESCRIPTIONS, SQUAD_FREQUENCIES, ACCESS_KEYS, KEY_TO_ROLE

    command = data.get('command', '').strip()
    current_role = session.get('role', 'guest')
    user_uid = session.get('uid', 'N/A')
    user_callsign = session.get('callsign', 'N/A')
    user_squad = session.get('squad', 'None')
    user_info = f"UID:{user_uid}, Callsign:{user_callsign}, Role:{current_role}"

    log_terminal_event("command_input", user_info, f"Команда: '{command}'")

    parts = command.split(" ", 1)
    base_command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    output = ""

    if base_command == "login":
        login_parts = args.split(" ")
        if len(login_parts) == 2:
            uid, key = login_parts
            login({'uid': uid, 'key': key})
            return
        else:
            output = "ℹ️ Использование: login <UID> <ключ_доступа>\n"
            emit('terminal_output', {'output': output + '\n'}, room=request.sid)
            return

    if base_command not in ROLE_PERMISSIONS.get(current_role, []):
        output = (f"❓ Неизвестная команда: '{base_command}' или недоступна для вашей роли ({current_role}).\n"
                  "Введите 'help' для списка команд.\n")
    elif base_command == "help":
        output = "--- 📖 СПИСОК ДОСТУПНЫХ КОМАНД ---\n"
        for cmd in sorted(ROLE_PERMISSIONS.get(current_role, [])):
            description = COMMAND_DESCRIPTIONS.get(cmd, "Нет описания.")
            output += f"- {cmd}: {description}\n"
        output += "---------------------------------\n"
    elif base_command == "clear":
        emit('terminal_output', {'output': "<CLEAR_TERMINAL>\n"}, room=request.sid)
        return
    elif base_command == "ping":
        output = "📡 Пинг: 42мс (стабильно)\n"

    # --- ИЗМЕНЕНИЕ: Обновлена логика sendmsg для сохранения сообщений ---
    elif base_command == "sendmsg":
        if current_role not in ["operative", "commander", "syndicate"]:
            output = "❌ Ошибка: Команда 'sendmsg' доступна только для Оперативников, Командиров и Синдиката.\n"
        elif not args:
            output = "ℹ️ Использование: sendmsg <сообщение> ИЛИ sendmsg <UID_получателя> <сообщение>\n"
        else:
            msg_parts = args.split(" ", 1)
            target_id_or_msg = msg_parts[0]
            message_text_if_private = msg_parts[1] if len(msg_parts) > 1 else ""
            load_data_from_sheets()

            if message_text_if_private and target_id_or_msg in REGISTERED_USERS:
                target_uid = target_id_or_msg
                target_callsign = REGISTERED_USERS[target_uid]['Позывной']
                target_sid = next((sid for sid, user_data in active_users.items() if user_data.get('uid') == target_uid), None)
                if target_sid:
                    # Сохраняем личное сообщение
                    log_message_to_sheet(user_uid, user_callsign, user_squad, 'private', target_uid, message_text_if_private)
                    emit('terminal_output', {'output': f"💬 [ЛИЧНО] От {user_callsign}: {message_text_if_private}\n"}, room=target_sid)
                    output = f"✅ Сообщение отправлено '{target_callsign}'.\n"
                    log_terminal_event("message_sent", user_info, f"Личное сообщение для {target_callsign} (UID:{target_uid}): '{message_text_if_private}'")
                else:
                    output = f"❌ Ошибка: Пользователь '{target_callsign}' (UID: {target_uid}) не в сети.\n"
            else:
                full_message = args
                if current_role == "syndicate":
                    # Сохраняем глобальное сообщение
                    log_message_to_sheet(user_uid, user_callsign, user_squad, 'global', 'all', full_message)
                    emit('terminal_output', {'output': f"📢 [ГЛОБАЛ] Синдикат {user_callsign}: {full_message}\n"}, broadcast=True)
                    output = "✅ Глобальное сообщение отправлено.\n"
                    log_terminal_event("message_sent", user_info, f"Глобальное сообщение: '{full_message}'")
                elif user_squad and user_squad.lower() != 'none':
                    # Сохраняем сообщение отряда
                    log_message_to_sheet(user_uid, user_callsign, user_squad, 'squad', user_squad, full_message)
                    message_to_send = f"💬 [{user_squad.upper()}] {user_callsign}: {full_message}\n"
                    emit('terminal_output', {'output': message_to_send}, room=user_squad)
                    output = f"✅ Сообщение отправлено в отряд {user_squad.upper()}.\n"
                    log_terminal_event("message_sent", user_info, f"Сообщение в отряд {user_squad}: '{full_message}'")
                else:
                    output = "❌ Ошибка: Не указан получатель или вы не состоите в отряде.\n"

    # --- НОВЫЙ БЛОК: Логика команды msghistory ---
    elif base_command == "msghistory" and current_role in ["operative", "commander"]:
        if not user_squad or user_squad.lower() == 'none':
            output = "❌ Ошибка: Вы не состоите в отряде, чтобы просматривать историю сообщений.\n"
        else:
            output = f"--- 📜 ИСТОРИЯ СООБЩЕНИЙ ОТРЯДА: {user_squad.upper()} (последние 20) ---\n"
            all_messages = google_sheets_api.get_all_records(MESSAGES_SHEET_NAME)
            
            squad_messages = [
                msg for msg in all_messages
                if msg.get('Recipient_Type') == 'squad' and msg.get('Recipient_ID') == user_squad
            ]

            if not squad_messages:
                output += "  Сообщений пока нет.\n"
            else:
                # Сортируем по времени (от старых к новым) и берем последние 20
                squad_messages.sort(key=lambda x: x.get('Timestamp', ''))
                recent_messages = squad_messages[-20:]
                
                for msg in recent_messages:
                    # Форматируем для красивого вывода
                    ts = msg.get('Timestamp', '----')
                    sender = msg.get('Sender_Callsign', 'Неизвестный')
                    text = msg.get('Message_Text', '')
                    output += f"  [{ts}] {sender}: {text}\n"

            output += "--------------------------------------------------------\n"

    # ... (остальные команды остаются без изменений) ...
    elif base_command == "exit":
        if current_role == "guest":
            output = "ℹ️ Вы уже находитесь в режиме Гостя. Для входа в систему используйте 'login'.\n"
        else:
            if session.get('squad') and session['squad'].lower() != 'none': leave_room(session['squad'])
            if current_role == "syndicate": leave_room("syndicate_room")
            if request.sid in active_operatives: del active_operatives[request.sid]
            if request.sid in active_users: active_users[request.sid] = {'uid': None, 'callsign': None, 'role': 'guest', 'squad': None}
            log_terminal_event("logout", user_info, "Выход из системы.")
            session.clear()
            session['role'] = 'guest'
            session['uid'] = None
            session['callsign'] = None
            session['squad'] = None
            output = "🔌 Вы вышли из системы. Роль сброшена до гостя.\n"
            socketio.emit('update_ui_state', {'role': 'guest', 'show_ui_panel': False}, room=request.sid)
    elif base_command == "resetkeys" and current_role == "syndicate":
        role_to_reset = args.strip().lower()
        if role_to_reset == "заказчик": role_to_reset = "client"
        if not role_to_reset or role_to_reset not in ["operative", "commander", "client"]:
            output = "ℹ️ Использование: resetkeys <operative | commander | client>\n"
        elif role_to_reset not in ACCESS_KEYS:
            output = f"❌ Ошибка: Роль '{role_to_reset}' не найдена в системе ключей.\n"
        else:
            num_keys = len(ACCESS_KEYS[role_to_reset])
            if num_keys == 0:
                output = f"ℹ️ Для роли '{role_to_reset}' не задано количество ключей. Сброс невозможен.\n"
            else:
                new_keys_for_role = [secrets.token_hex(4) for _ in range(num_keys)]
                ACCESS_KEYS[role_to_reset] = new_keys_for_role
                KEY_TO_ROLE.clear()
                for role, keys_list in ACCESS_KEYS.items():
                    for key in keys_list:
                        KEY_TO_ROLE[key] = role
                output = f"--- 🔑 Сгенерированы новые ключи для роли '{role_to_reset.upper()}'. ---\n"
                output += "ВНИМАНИЕ: Для применения этих ключей обновите переменную окружения 'ACCESS_KEYS_JSON' и перезапустите приложение.\n"
                output += f"{role_to_reset.upper()}: {', '.join(new_keys_for_role)}\n"
                log_terminal_event("syndicate_action", user_info, f"Сгенерированы новые ключи для роли: {role_to_reset}.")
    elif base_command == "viewkeys" and current_role == "syndicate":
        output = "--- 🔑 ТЕКУЩИЕ АКТИВНЫЕ КЛЮЧИ ДОСТУПА ---\n"
        for role, keys in ACCESS_KEYS.items():
            if role == "guest": continue
            output += f"{role.upper()}: {', '.join(keys)}\n"
        output += "--------------------------------------\n"
    elif base_command == "register_user" and current_role == "syndicate":
        reg_parts = args.split(" ", 3)
        if len(reg_parts) < 4:
            output = "ℹ️ Использование: register_user <ключ> <UID> <позывной> <отряд|NONE>\n"
        else:
            key, uid, callsign, squad_input = reg_parts
            squad_input = squad_input.lower()
            load_data_from_sheets()
            key_is_used = any(user.get("Ключ Доступа") == key for user in REGISTERED_USERS.values())
            if key_is_used:
                output = f"❌ Ошибка: Ключ '{key}' уже используется другим пользователем.\n"
            elif uid in REGISTERED_USERS:
                output = f"❌ Ошибка: Пользователь с UID '{uid}' уже зарегистрирован.\n"
            else:
                role_from_key = KEY_TO_ROLE.get(key)
                if not role_from_key:
                    output = "❌ Ошибка: Указанный ключ доступа недействителен.\n"
                else:
                    squad_to_assign = "None"
                    if role_from_key in ["operative", "commander"]:
                        if squad_input not in ["alpha", "beta"]:
                            output = "❌ Ошибка: Для оперативника/командира отряд должен быть 'alpha' или 'beta'.\n"; emit('terminal_output', {'output': output}); return
                        squad_to_assign = squad_input
                        commander_count = sum(1 for u in REGISTERED_USERS.values() if u.get('Роль') == 'commander' and u.get('Отряд') == squad_to_assign)
                        if role_from_key == "commander" and commander_count >= 1:
                            output = f"❌ Ошибка: В отряде '{squad_to_assign}' уже есть Командир.\n"; emit('terminal_output', {'output': output}); return
                    user_data_row = [uid, key, role_from_key, callsign, squad_to_assign]
                    if google_sheets_api.append_row('Пользователи', user_data_row):
                        REGISTERED_USERS[uid] = {"UID": uid, "Ключ Доступа": key, "Роль": role_from_key, "Позывной": callsign, "Отряд": squad_to_assign}
                        output = f"✅ Пользователь '{callsign}' (UID: {uid}) с ролью '{role_from_key.upper()}' зарегистрирован.\n"
                        if squad_to_assign not in [None, "None", "none"]:
                            output += f"Привязан к отряду: {squad_to_assign.upper()}.\n"
                        log_terminal_event("syndicate_action", user_info, f"Зарегистрирован пользователь: UID={uid}, Callsign={callsign}.")
                    else:
                        output = "❌ Ошибка: Не удалось зарегистрировать пользователя в Google Таблицах.\n"
    elif base_command == "unregister_user" and current_role == "syndicate":
        target_uid = args.strip()
        if not target_uid:
            output = "ℹ️ Использование: unregister_user <UID>\n"
        else:
            load_data_from_sheets()
            if target_uid not in REGISTERED_USERS:
                output = f"❌ Ошибка: Пользователь с UID '{target_uid}' не найден.\n"
            else:
                callsign_to_remove = REGISTERED_USERS[target_uid].get('Позывной')
                if google_sheets_api.delete_row_by_key('Пользователи', 'UID', target_uid):
                    del REGISTERED_USERS[target_uid]
                    output = f"✅ Пользователь '{callsign_to_remove}' (UID: {target_uid}) успешно деактивирован.\n"
                    log_terminal_event("syndicate_action", user_info, f"Дерегистрирован пользователь: UID={target_uid}.")
                else:
                    output = "❌ Ошибка: Не удалось деактивировать пользователя в Google Таблицах.\n"
    elif base_command == "setchannel" and current_role == "commander":
        new_frequency = args.strip()
        user_squad = session.get('squad')
        if not new_frequency:
            output = "ℹ️ Использование: setchannel <новая_частота>\n"
        elif not user_squad or user_squad not in SQUAD_FREQUENCIES:
            output = "❌ Ошибка: Вы не приписаны к отряду, для которого можно сменить частоту.\n"
        else:
            SQUAD_FREQUENCIES[user_squad] = new_frequency
            output = f"✅ Частота для отряда {user_squad.upper()} установлена на {new_frequency}.\n"
            log_terminal_event("commander_action", user_info, f"Сменил частоту отряда {user_squad} на {new_frequency}")
            for sid, user_data in list(active_users.items()):
                if user_data.get('squad') == user_squad:
                    socketio.emit('update_ui_state', {'channel_frequency': new_frequency}, room=sid, namespace='/')
                    if sid != request.sid:
                        socketio.emit('terminal_output', {'output': f"📢 КОМАНДИР {session['callsign']} сменил частоту вашего отряда на {new_frequency}.\n"}, room=sid, namespace='/')
            socketio.emit('update_ui_state', {'squad_frequencies': SQUAD_FREQUENCIES}, room='syndicate_room', namespace='/')
    elif base_command == "view_users" and current_role == "syndicate":
        output = "--- 👥 ЗАРЕГИСТРИРОВАННЫЕ ПОЛЬЗОВАТЕЛИ ---\n"
        load_data_from_sheets()
        if REGISTERED_USERS:
            for uid, user_data in REGISTERED_USERS.items():
                output += (f"  UID: {user_data.get('UID', 'N/A')}, Позывной: {user_data.get('Позывной', 'N/A')}, "
                           f"Роль: {user_data.get('Роль', 'N/A').upper()}, Отряд: {user_data.get('Отряд', 'N/A').upper()}\n")
        else:
            output += "  Нет зарегистрированных пользователей.\n"
        output += "---------------------------------------\n"
    elif base_command == "view_users_squad" and current_role == "commander":
        output = f"--- 👥 ОПЕРАТИВНИКИ В ОТЯДЕ {session['squad'].upper()} ---\n"
        load_data_from_sheets()
        found_operatives = False
        for uid, user_data in REGISTERED_USERS.items():
            if user_data.get('Роль') == 'operative' and user_data.get('Отряд') == session['squad']:
                output += (f"  UID: {user_data.get('UID', 'N/A')}, Позывной: {user_data.get('Позывной', 'N/A')}\n")
                found_operatives = True
        if not found_operatives:
            output += "  Нет оперативников в вашем отряде.\n"
        output += "---------------------------------------\n"
    elif base_command == "contracts":
        load_data_from_sheets()
        output = "--- 📋 Активные контракты ---\n"
        found = False
        user_squad = session.get('squad')
        for contract in CONTRACTS:
            status = str(contract.get('Статус', '')).lower()
            if status not in ["провален", "выполнен", "failed", "completed"]:
                assignee = contract.get('Назначено', 'None')
                assignee_display = assignee if assignee != 'None' else "Никому"
                if assignee != 'None' and assignee not in ['alpha', 'beta', 'alpha,beta'] and current_role != 'syndicate':
                    assignee_squad = next((u.get('Отряд') for u in REGISTERED_USERS.values() if u.get('Позывной') == assignee), None)
                    if user_squad and assignee_squad and user_squad != assignee_squad:
                         assignee_display = "(другой отряд)"
                output += f"ID: {contract.get('ID')}, Название: {contract.get('Название')}, Статус: {status.upper()}, Назначен: {assignee_display}\n"
                found = True
        if not found:
            output += "  Нет контрактов в работе.\n"
        output += "--------------------------\n"
    elif base_command == "assign_contract" and current_role == "commander":
        assign_parts = args.split(" ")
        if len(assign_parts) < 2:
            output = "ℹ️ Использование: assign_contract <ID_контракта> <UID_оперативника>\n"
        else:
            try:
                contract_id = int(assign_parts[0])
                target_uid = assign_parts[1]
                load_data_from_sheets()
                target_contract = next((c for c in CONTRACTS if c.get('ID') == contract_id), None)
                if not target_contract:
                    output = f"❌ Контракт с ID '{contract_id}' не найден.\n"
                else:
                    is_self_assign = (target_uid == session.get('uid'))
                    target_user_data = REGISTERED_USERS.get(target_uid)
                    target_callsign = None
                    if is_self_assign:
                        target_callsign = session.get('callsign')
                    elif target_user_data and target_user_data.get('Роль') == 'operative' and target_user_data.get('Отряд') == session.get('squad'):
                        target_callsign = target_user_data.get('Позывной')
                    if target_callsign:
                        updates = {'Назначено': target_callsign, 'Статус': 'Назначен'}
                        if google_sheets_api.update_row_by_key('Контракты', 'ID', contract_id, updates):
                            output = f"✅ Контракт ID:{contract_id} назначен: {target_callsign}.\n"
                            log_terminal_event("commander_action", user_info, f"Назначил контракт {contract_id} на {target_uid}")
                        else:
                            output = "❌ Ошибка обновления контракта в Google Sheets.\n"
                    else:
                        output = f"❌ UID '{target_uid}' не является оперативником вашего отряда или неверный.\n"
            except ValueError:
                output = "❌ ID контракта должен быть числом.\n"
    elif base_command == "view_orders" and current_role == "operative":
        output = "--- 📝 ВАШИ НАЗНАЧЕНИЯ ---\n"
        load_data_from_sheets()
        found_orders = False
        for contract in CONTRACTS:
            if contract.get('Назначено') == session['callsign']:
                output += (f"  ID: {contract.get('ID', 'N/A')}, Название: {contract.get('Название', 'N/A')},\n"
                           f"  Описание: {contract.get('Описание', 'N/A')},\n"
                           f"  Награда: {contract.get('Награда', 'N/A')}, Статус: {contract.get('Статус', 'N/A')}\n")
                found_orders = True
        if not found_orders: output += "  У вас нет текущих назначений.\n"
        output += "---------------------------\n"
    elif base_command == "view_contract" and current_role in ["operative", "commander"]:
        contract_id_str = args.strip()
        if not contract_id_str:
            output = "ℹ️ Использование: view_contract <ID_контракта>\n"
        else:
            try:
                contract_id = int(contract_id_str)
                load_data_from_sheets()
                target_contract = next((c for c in CONTRACTS if c.get('ID') == contract_id), None)
                if not target_contract:
                    output = f"❌ Контракт с ID '{contract_id}' не найден.\n"
                else:
                    user_squad = session.get('squad')
                    user_callsign = session.get('callsign')
                    assignee = str(target_contract.get('Назначено', '')).lower()
                    can_view = False
                    if assignee == user_callsign.lower():
                        can_view = True
                    elif user_squad and user_squad in assignee.split(','):
                        can_view = True
                    if not can_view:
                        output = f"❌ У вас нет доступа к деталям этого контракта (ID: {contract_id}).\n"
                    else:
                        output = f"--- 📜 ДЕТАЛИ КОНТРАКТА ID: {target_contract.get('ID')} ---\n"
                        output += f"  Название: {target_contract.get('Название', 'Н/Д')}\n"
                        output += f"  Описание: {target_contract.get('Описание', 'Н/Д')}\n"
                        output += f"  Награда:  {target_contract.get('Награда', 'Н/Д')}\n"
                        output += f"  Статус:   {target_contract.get('Статус', 'Н/Д').upper()}\n"
                        output += f"  Назначен: {target_contract.get('Назначено', 'Н/Д')}\n"
                        output += "--------------------------------------\n"
                        log_terminal_event("action", user_info, f"Просмотрел детали контракта ID:{contract_id}")
            except ValueError:
                output = "❌ ID контракта должен быть числом.\n"
    elif base_command == "create_request" and current_role == "client":
        req_parts = args.split(" ", 2)
        if len(req_parts) < 3:
            output = "ℹ️ Использование: create_request <ID_Discord> <Причина> <Текст запроса>\n"
        else:
            discord_id, reason, request_text = req_parts
            load_data_from_sheets()
            valid_ids = [req.get('ID Запроса', 0) for req in PENDING_REQUESTS if isinstance(req.get('ID Запроса'), int)]
            next_request_id = max(valid_ids) + 1 if valid_ids else 1
            request_data_row = [next_request_id, session['uid'], session['callsign'], discord_id, reason, request_text, 'Новый']
            if google_sheets_api.append_row('Запросы Клиентов', request_data_row):
                output = f"✅ Ваш запрос (ID: {next_request_id}) отправлен.\n"
                log_terminal_event("client_action", user_info, f"Создан запрос ID={next_request_id}")
                socketio.emit('terminal_output', {'output': f"🔔 Новый запрос от клиента {session['callsign']} (ID: {next_request_id})!\n"}, room="syndicate_room")
            else:
                output = "❌ Ошибка создания запроса в Google Sheets.\n"
    elif base_command == "syndicate_assign" and current_role == "syndicate":
        assign_parts = args.split(" ")
        if len(assign_parts) != 2:
            output = "ℹ️ Использование: syndicate_assign <ID_контракта> <alpha|beta|alpha,beta>\n"
        else:
            try:
                contract_id = int(assign_parts[0])
                squads_str = assign_parts[1].lower()
                if not all(s in ["alpha", "beta"] for s in squads_str.split(',')):
                    output = "❌ Неверное имя отряда. Допустимы: alpha, beta, alpha,beta.\n"
                else:
                    load_data_from_sheets()
                    if any(c.get('ID') == contract_id for c in CONTRACTS):
                        updates = {'Назначено': squads_str, 'Статус': 'Назначен'}
                        if google_sheets_api.update_row_by_key('Контракты', 'ID', contract_id, updates):
                             output = f"✅ Контракт ID:{contract_id} назначен отряду(ам): {squads_str}.\n"
                             log_terminal_event("syndicate_action", user_info, f"Назначил контракт {contract_id} на {squads_str}")
                        else:
                            output = "❌ Ошибка обновления контракта в Google Sheets.\n"
                    else:
                        output = f"❌ Контракт с ID '{contract_id}' не найден.\n"
            except ValueError:
                output = "❌ ID контракта должен быть числом.\n"
    elif base_command == "view_my_requests" and current_role == "client":
        output = "--- ✉️ ВАШИ ЗАПРОСЫ ---\n"
        load_data_from_sheets()
        found_requests = False
        for req in PENDING_REQUESTS:
            if req.get('UID Клиента') == session['uid']:
                output += (f"  ID: {req.get('ID Запроса', 'N/A')}, Статус: {req.get('Статус', 'N/A')},\n"
                           f"  Текст: {req.get('Текст Запроса', 'N/A')}\n")
                found_requests = True
        if not found_requests: output += "  У вас пока нет запросов.\n"
        output += "-----------------------\n"
    elif base_command == "viewrequests" and current_role == "syndicate":
        output = "--- ✉️ ЗАПРОСЫ КЛИЕНТОВ (ОЖИДАЮЩИЕ) ---\n"
        load_data_from_sheets()
        found_requests = False
        for req in PENDING_REQUESTS:
            if req.get('Статус', '').lower() == 'новый':
                output += (f"  ID: {req.get('ID Запроса', 'N/A')}, От: {req.get('Позывной Клиента', 'N/A')} (UID: {req.get('UID Клиента', 'N/A')}),\n"
                           f"  Текст: {req.get('Текст Запроса', 'N/A')}\n")
                found_requests = True
        if not found_requests: output += "  Нет ожидающих запросов.\n"
        output += "--------------------------------------\n"
    elif base_command == "acceptrequest" and current_role == "syndicate":
        req_parts = args.split(" ", 3)
        if len(req_parts) < 4:
            output = "ℹ️ Использование: acceptrequest <ID_запроса> <название_контракта> <описание> <награда>\n"
        else:
            try:
                request_id = int(req_parts[0])
                contract_title, contract_description, contract_reward = req_parts[1], req_parts[2], req_parts[3]
                load_data_from_sheets()
                target_request = next((r for r in PENDING_REQUESTS if r.get('ID Запроса') == request_id), None)
                if not target_request:
                    output = f"❌ Ошибка: Запрос с ID '{request_id}' не найден.\n"
                elif target_request.get('Статус', '').lower() != 'новый':
                    output = f"❌ Ошибка: Запрос с ID '{request_id}' уже был обработан.\n"
                else:
                    if google_sheets_api.update_row_by_key('Запросы Клиентов', 'ID Запроса', request_id, {'Статус': 'Принят'}):
                        valid_c_ids = [c['ID'] for c in CONTRACTS if isinstance(c.get('ID'), int)]
                        next_contract_id = max(valid_c_ids) + 1 if valid_c_ids else 1
                        contract_data_row = [next_contract_id, contract_title, contract_description, contract_reward, 'active', 'None']
                        if google_sheets_api.append_row('Контракты', contract_data_row):
                            target_request['Статус'] = 'Принят'
                            CONTRACTS.append({"ID": next_contract_id, "Название": contract_title, "Описание": contract_description, "Награда": contract_reward, "Статус": "active", "Назначено": "None"})
                            output = (f"✅ Запрос ID:{request_id} принят. Создан контракт (ID: {next_contract_id}) '{contract_title}'.\n")
                            log_terminal_event("syndicate_action", user_info, f"Принят запрос ID:{request_id}, создан контракт ID:{next_contract_id}.")
                            client_sid = next((sid for sid, data in active_users.items() if data.get('uid') == target_request.get('UID Клиента')), None)
                            if client_sid:
                                socketio.emit('terminal_output', {'output': f"🔔 Ваш запрос (ID: {request_id}) был ПРИНЯТ Синдикатом!\n"}, room=client_sid)
                        else:
                            google_sheets_api.update_row_by_key('Запросы Клиентов', 'ID Запроса', request_id, {'Статус': 'Новый'})
                            output = "❌ Ошибка: Не удалось создать контракт в Google Таблицах.\n"
                    else:
                        output = "❌ Ошибка: Не удалось обновить статус запроса в Google Таблицах.\n"
            except ValueError:
                output = "❌ Ошибка: ID запроса должен быть числом.\n"
                emit('terminal_output', {'output': output})
                return
    elif base_command == "declinerequest" and current_role == "syndicate":
        parts = args.split(" ")
        if not parts or not parts[0]:
            output = "ℹ️ Использование: declinerequest <ID_запроса>\n"
        else:
            try:
                request_id = int(parts[0])
                load_data_from_sheets()
                target_request = next((r for r in PENDING_REQUESTS if r.get('ID Запроса') == request_id), None)
                if not target_request:
                    output = f"❌ Ошибка: Запрос с ID '{request_id}' не найден.\n"
                elif target_request.get('Статус', '').lower() != 'новый':
                    output = f"❌ Ошибка: Запрос с ID '{request_id}' уже был обработан.\n"
                else:
                    if google_sheets_api.update_row_by_key('Запросы Клиентов', 'ID Запроса', request_id, {'Статус': 'Отклонен'}):
                        target_request['Статус'] = 'Отклонен'
                        output = f"✅ Запрос ID:{request_id} отклонен.\n"
                        log_terminal_event("syndicate_action", user_info, f"Отклонен запрос ID:{request_id}.")
                        client_sid = next((sid for sid, data in active_users.items() if data.get('uid') == target_request.get('UID Клиента')), None)
                        if client_sid:
                            socketio.emit('terminal_output', {'output': f"🔔 Ваш запрос (ID: {request_id}) был ОТКЛОНЕН Синдикатом.\n"}, room=client_sid)
                    else:
                        output = "❌ Ошибка: Не удалось отклонить запрос в Google Таблицах.\n"
            except ValueError:
                output = "❌ Ошибка: ID запроса должен быть числом.\n"
                emit('terminal_output', {'output': output})
                return
    else:
        output = (f"❓ Неизвестная команда: '{base_command}' или недоступна для вашей роли ({current_role}).\n"
                  "Введите 'help' для списка команд.\n")

    emit('terminal_output', {'output': output + '\n'}, room=request.sid)

if __name__ == '__main__':
    print("Запуск в режиме локальной отладки...")
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True, host='0.0.0.0', port=5000)