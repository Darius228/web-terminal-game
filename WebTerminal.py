# WebTerminal.py

import os
import json
import secrets
from datetime import datetime, timedelta
from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room
import google_sheets_api

# --- Константы ---
LOG_SHEET_NAME = "Логи"

# --- ИЗМЕНЕНИЯ: Обновляем права доступа и описания команд ---
ROLE_PERMISSIONS = {
    "guest": ["help", "login", "clear", "ping"],
    "operative": ["help", "ping", "sendmsg", "contracts", "view_orders", "exit", "clear"],
    "commander": [
        "help", "ping", "sendmsg", "contracts", "contract_details", "active_contracts",
        "assign_contract", "cancel_contract", "view_users_squad", "setchannel", "exit", "clear"
    ],
    "client": ["help", "ping", "create_request", "view_my_requests", "exit", "clear"], # Убрана команда sendmsg
    "syndicate": [
        "help", "ping", "sendmsg", "resetkeys", "viewkeys", "register_user",
        "unregister_user", "view_users", "viewrequests", "acceptrequest",
        "declinerequest", "contracts", "exit", "clear"
    ]
}
COMMAND_DESCRIPTIONS = {
    "help": "Отображает список доступных команд с их описанием.",
    "login": "Выполняет вход в систему. Использование: login <UID> <ключ_доступа>",
    "clear": "Очищает окно терминала.",
    "ping": "Проверяет сетевое соединение.",
    "sendmsg": "Отправляет сообщение в канал отряда или лично. Использование: sendmsg <сообщение> | sendmsg <UID> <сообщение>",
    "contracts": "Просматривает список доступных контрактов.",
    "view_orders": "Просматривает контракты, назначенные вам (только для Оперативников).",
    "assign_contract": "Назначает контракт оперативнику. Использование: assign_contract <ID_контракта> <UID_оперативника>",
    "view_users_squad": "Просматривает список оперативников в вашем отряде (только для Командиров).",
    "setchannel": "Устанавливает новую частоту связи для вашего отряда. Использование: setchannel <частота>",
    "create_request": "Создает новый запрос для Синдиката (только для Клиентов). Использование: create_request <текст_запроса>",
    "view_my_requests": "Просматривает ваши отправленные запросы (только для Клиентов).",
    "resetkeys": "Сбрасывает ключи доступа для указанной роли. Использование: resetkeys <operative|commander|client>",
    "viewkeys": "Просматривает текущие активные ключи доступа (только для Синдиката).",
    "register_user": "Регистрирует нового пользователя. Использование: register_user <ключ> <UID> <позывной> <отряд>",
    "unregister_user": "Деактивирует зарегистрированного пользователя. Использование: unregister_user <UID>",
    "view_users": "Просматривает список всех зарегистрированных пользователей (только для Синдиката).",
    "viewrequests": "Просматривает ожидающие запросы клиентов (только для Синдиката).",
    "acceptrequest": "Принимает запрос клиента и создает контракт. Использование: acceptrequest <ID_запроса> <название_контракта> <описание_контракта> <награда>",
    "declinerequest": "Отклоняет запрос клиента. Использование: declinerequest <ID_запроса>",
    "exit": "Выходит из текущей сессии, возвращаясь к роли гостя.",
    # НОВЫЕ КОМАНДЫ
    "contract_details": "Показывает полное описание контракта. Использование: contract_details <ID_контракта>",
    "active_contracts": "Показывает список всех активных и назначенных контрактов.",
    "cancel_contract": "Отменяет назначение контракта или проваливает его. Использование: cancel_contract <ID_контракта> <active|failed>"
}
ACCESS_KEYS = {}
KEY_TO_ROLE = {}
REGISTERED_USERS = {}
CONTRACTS = []
PENDING_REQUESTS = []
SQUAD_FREQUENCIES = { "alpha": "142.7 МГц", "beta": "148.8 МГц" }
active_users = {}
active_operatives = {}

def log_terminal_event(event_type, user_info, message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    console_log_entry = f"[{timestamp}] [{event_type.upper()}] [Пользователь: {user_info}] {message}"
    print(console_log_entry)
    sheet_row_data = [timestamp, event_type.upper(), user_info, message]
    google_sheets_api.append_row(LOG_SHEET_NAME, sheet_row_data)

def load_access_keys():
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
    global REGISTERED_USERS, CONTRACTS, PENDING_REQUESTS
    print("Загрузка данных из Google Таблиц...")
    users_data = google_sheets_api.get_all_records('Пользователи')
    REGISTERED_USERS = {str(user.get('UID')): user for user in users_data if user.get('UID')}
    print(f"Загружено {len(REGISTERED_USERS)} пользователей.")
    CONTRACTS.clear()
    contracts_data = google_sheets_api.get_all_records('Контракты')
    for contract in contracts_data:
        try:
            contract['ID'] = int(contract.get('ID'))
            CONTRACTS.append(contract)
        except (ValueError, TypeError):
            continue
    print(f"Загружено {len(CONTRACTS)} контрактов.")
    PENDING_REQUESTS.clear()
    requests_data = google_sheets_api.get_all_records('Запросы Клиентов')
    for req in requests_data:
        try:
            req['ID Запроса'] = int(req.get('ID Запроса'))
            PENDING_REQUESTS.append(req)
        except (ValueError, TypeError):
            continue
    print(f"Загружено {len(PENDING_REQUESTS)} запросов.")

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

@socketio.on('connect')
def handle_connect():
    session.setdefault('role', 'guest')
    active_users[request.sid] = {'uid': session.get('uid'), 'callsign': session.get('callsign'), 'role': session.get('role'), 'squad': session.get('squad')}
    emit('update_ui_state', {'role': session.get('role'), 'show_ui_panel': session.get('role') != 'guest', 'squad': session.get('squad'), 'callsign': session.get('callsign'), 'channel_frequency': SQUAD_FREQUENCIES.get(session.get('squad'), '--:--')})
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
        if session['role'] in ["operative", "commander"] and session['squad'] and session['squad'].lower() != 'none':
            join_room(session['squad'])
        if session['role'] == "syndicate":
            join_room("syndicate_room")
        log_terminal_event("login_success", user_info, f"Пользователь '{session['callsign']}' успешно вошел как {session['role'].upper()}.")
        emit('terminal_output', {'output': f"✅ Добро пожаловать, {session['callsign']}! Вы вошли как {session['role'].upper()}.\n"})
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
    user_info = f"UID:{user_uid}, Callsign:{user_callsign}, Role:{current_role}"
    log_terminal_event("command_input", user_info, f"Команда: '{command}'")
    parts = command.split(" ", 1)
    base_command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    output = ""
    if base_command not in ROLE_PERMISSIONS.get(current_role, []):
        output = f"❓ Неизвестная команда: '{base_command}' или недоступна для вашей роли ({current_role}).\n"
    elif base_command == "login":
        login_parts = args.split(" ")
        if len(login_parts) == 2:
            uid, key = login_parts
            login({'uid': uid, 'key': key})
            return
        else:
            output = "ℹ️ Использование: login <UID> <ключ_доступа>\n"
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
    elif base_command == "sendmsg":
        if not args:
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
                    emit('terminal_output', {'output': f"💬 [ЛИЧНО] От {session['callsign']}: {message_text_if_private}\n"}, room=target_sid, namespace='/')
                    output = f"✅ Сообщение отправлено '{target_callsign}'.\n"
                else:
                    output = f"❌ Ошибка: Пользователь '{target_callsign}' (UID: {target_uid}) не в сети.\n"
            else:
                message_to_send = f"💬 [ОТРЯД] {session['callsign']}: {args}\n"
                room_to_send = session.get('squad')
                if current_role == "syndicate":
                    emit('terminal_output', {'output': f"📢 [ГЛОБАЛ] Синдикат {session['callsign']}: {args}\n"}, broadcast=True, namespace='/')
                    output = "✅ Глобальное сообщение отправлено.\n"
                elif room_to_send and room_to_send.lower() != 'none':
                    emit('terminal_output', {'output': message_to_send}, room=room_to_send, namespace='/')
                    output = f"✅ Сообщение отправлено в отряд {room_to_send.upper()}.\n"
                else:
                    output = "❌ Ошибка: Не указан получатель сообщения или вы не состоите в отряде для групповой рассылки.\n"
    elif base_command == "exit":
        if current_role != "guest":
            log_terminal_event("logout", user_info, "Выход из системы.")
            session.clear()
            session['role'] = 'guest'
            session['uid'] = None
            session['callsign'] = None
            session['squad'] = None
            output = "🔌 Вы вышли из системы. Роль сброшена до гостя.\n"
            socketio.emit('update_ui_state', {'role': 'guest', 'show_ui_panel': False}, room=request.sid)
        else:
            output = "ℹ️ Вы уже находитесь в режиме Гостя.\n"
    elif base_command == "contracts":
        load_data_from_sheets()
        output = "--- 📋 ДОСТУПНЫЕ КОНТРАКТЫ (НЕ НАЗНАЧЕННЫЕ) ---\n"
        found = False
        for contract in CONTRACTS:
            if str(contract.get('Статус', '')).lower() in ["active", "активен"]:
                output += (f"  ID: {contract.get('ID', 'N/A')}, Название: {contract.get('Название', 'N/A')}, "
                           f"Награда: {contract.get('Награда', 'N/A')}\n")
                found = True
        if not found:
            output += "  Нет доступных для взятия контрактов.\n"
        output += "----------------------------------------------\n"
    elif base_command == "contract_details" and current_role == "commander":
        if not args:
            output = "ℹ️ Использование: contract_details <ID_контракта>\n"
        else:
            try:
                contract_id = int(args.strip())
                load_data_from_sheets()
                target_contract = next((c for c in CONTRACTS if c.get('ID') == contract_id), None)
                if target_contract:
                    output = f"---  детальная информация: контракт #{target_contract.get('ID')} ---\n"
                    output += f"Название: {target_contract.get('Название', 'N/A')}\n"
                    output += f"Описание: {target_contract.get('Описание', 'N/A')}\n"
                    output += f"Награда: {target_contract.get('Награда', 'N/A')}\n"
                    output += f"Статус: {target_contract.get('Статус', 'N/A')}\n"
                    output += f"Назначено: {target_contract.get('Назначено', 'None')}\n"
                    output += "-------------------------------------------\n"
                else:
                    output = f"❌ Ошибка: Контракт с ID '{contract_id}' не найден.\n"
            except ValueError:
                output = "❌ Ошибка: ID контракта должен быть числом.\n"
    elif base_command == "active_contracts" and current_role == "commander":
        load_data_from_sheets()
        output = "--- 📊 ВСЕ АКТИВНЫЕ И НАЗНАЧЕННЫЕ КОНТРАКТЫ ---\n"
        found = False
        for contract in CONTRACTS:
            status = str(contract.get('Статус', '')).lower()
            if status in ["active", "активен", "назначен"]:
                assignee = contract.get('Назначено', 'None')
                output += (f"  ID: {contract.get('ID', 'N/A')}, Название: {contract.get('Название', 'N/A')}, "
                           f"Статус: {status.upper()}, Назначен: {assignee}\n")
                found = True
        if not found:
            output += "  Нет контрактов в работе.\n"
        output += "--------------------------------------------------\n"
    elif base_command == "cancel_contract" and current_role == "commander":
        cancel_parts = args.split(" ")
        if len(cancel_parts) != 2:
            output = "ℹ️ Использование: cancel_contract <ID_контракта> <active|failed>\n"
        else:
            try:
                contract_id = int(cancel_parts[0])
                new_status = cancel_parts[1].lower()
                if new_status not in ["active", "failed"]:
                    output = "❌ Ошибка: Новый статус может быть только 'active' или 'failed'.\n"
                else:
                    load_data_from_sheets()
                    target_contract = next((c for c in CONTRACTS if c.get('ID') == contract_id), None)
                    if not target_contract:
                        output = f"❌ Ошибка: Контракт с ID '{contract_id}' не найден.\n"
                    else:
                        updates = {}
                        if new_status == "active":
                            updates['Статус'] = 'активен'
                            updates['Назначено'] = 'None'
                            msg = f"назначение отменено, статус изменен на 'активен'."
                        else:
                            updates['Статус'] = 'провален'
                            msg = f"статус изменен на 'провален'."
                        if google_sheets_api.update_row_by_key('Контракты', 'ID', contract_id, updates):
                            output = f"✅ Контракт ID:{contract_id} обновлен: {msg}\n"
                            log_terminal_event("commander_action", user_info, f"Обновил контракт ID:{contract_id}, новый статус: {new_status}")
                        else:
                            output = f"❌ Ошибка: Не удалось обновить контракт в Google Таблицах.\n"
            except ValueError:
                output = "❌ Ошибка: ID контракта должен быть числом.\n"
    elif base_command == "assign_contract" and current_role == "commander":
        assign_parts = args.split(" ")
        if len(assign_parts) < 2:
            output = "ℹ️ Использование: assign_contract <ID_контракта> <UID_оперативника>\n"
        else:
            try:
                contract_id = int(assign_parts[0])
                operative_uid = assign_parts[1]
                load_data_from_sheets()
                target_contract = next((c for c in CONTRACTS if c.get('ID') == contract_id), None)
                if not target_contract:
                    output = f"❌ Ошибка: Контракт с ID '{contract_id}' не найден.\n"
                elif operative_uid not in REGISTERED_USERS or REGISTERED_USERS[operative_uid].get('Роль') != 'operative':
                    output = f"❌ Ошибка: Пользователь с UID '{operative_uid}' не найден или не является оперативником.\n"
                else:
                    operative_callsign = REGISTERED_USERS[operative_uid].get('Позывной')
                    updates = {'Назначено': operative_callsign, 'Статус': 'Назначен'}
                    if google_sheets_api.update_row_by_key('Контракты', 'ID', contract_id, updates):
                        output = f"✅ Контракт '{target_contract.get('Название')}' назначен оперативнику '{operative_callsign}'.\n"
                        log_terminal_event("commander_action", user_info, f"Назначил контракт ID:{contract_id} оперативнику {operative_uid}")
                    else:
                        output = "❌ Ошибка: Не удалось назначить контракт.\n"
            except ValueError:
                output = "❌ Ошибка: ID контракта должен быть числом.\n"
    else:
        output = f"❓ Неизвестная команда: '{base_command}'. Введите 'help' для списка команд.\n"
    emit('terminal_output', {'output': output}, room=request.sid)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)