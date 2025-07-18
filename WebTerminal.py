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
ROLE_PERMISSIONS = {
    "guest": ["help", "login", "clear", "ping"],
    "operative": ["help", "ping", "sendmsg", "contracts", "view_orders", "exit", "clear", "contract_details"],
    "commander": [
        "help", "ping", "sendmsg", "contracts", "assign_contract", "view_users_squad",
        "setchannel", "exit", "clear", "contract_details", "update_contract"
    ],
    "client": ["help", "ping", "create_request", "view_my_requests", "exit", "clear"],
    "syndicate": [
        "help", "ping", "sendmsg", "resetkeys", "viewkeys", "register_user",
        "unregister_user", "view_users", "viewrequests", "acceptrequest",
        "declinerequest", "contracts", "exit", "clear", "syndicate_assign" # <-- Новая команда
    ]
}
COMMAND_DESCRIPTIONS = {
    "help": "Отображает список доступных команд.",
    "login": "Вход в систему. login <UID> <ключ>",
    "clear": "Очищает окно терминала.",
    "ping": "Проверяет соединение.",
    "sendmsg": "Отправляет сообщение. sendmsg <сообщение> | sendmsg <UID> <сообщение>",
    "contracts": "Просмотр всех активных и назначенных контрактов.",
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
    "contract_details": "Детальная информация о контракте. contract_details <ID>",
    "update_contract": "Обновить статус контракта. update_contract <ID> <fail|reset>",
    "syndicate_assign": "Назначить контракт отряду(ам). syndicate_assign <ID> <alpha|beta|alpha,beta>"
}
ACCESS_KEYS = {}
KEY_TO_ROLE = {}
REGISTERED_USERS = {}
CONTRACTS = []
PENDING_REQUESTS = []
SQUAD_FREQUENCIES = {"alpha": "142.7 МГц", "beta": "148.8 МГц"}
active_users = {}
active_operatives = {}

def log_terminal_event(event_type, user_info, message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    console_log_entry = f"[{timestamp}] [{event_type.upper()}] [Пользователь: {user_info}] {message}"
    print(console_log_entry)
    sheet_row_data = [timestamp, event_type.upper(), user_info, message]
    google_sheets_api.append_row(LOG_SHEET_NAME, sheet_row_data)

def load_data_from_sheets():
    global REGISTERED_USERS, CONTRACTS, PENDING_REQUESTS
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

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a_very_temporary_secret_key_for_dev_only')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
socketio = SocketIO(app)

if not google_sheets_api.init_google_sheets():
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать Google Таблицы.")
load_data_from_sheets()

@app.route('/')
def index():
    return render_template('index.html')

# WebTerminal.py

@socketio.on('connect')
def handle_connect():
    # Проверяем, есть ли у пользователя уже установленная роль и UID в сессии
    if 'uid' in session and 'role' in session and session['role'] != 'guest':
        # Если да - это переподключение существующего пользователя. Восстанавливаем его.
        current_uid = session['uid']
        current_role = session['role']
        current_callsign = session.get('callsign', 'N/A')
        current_squad = session.get('squad')

        # Восстанавливаем пользователя в нужных комнатах (для отрядов и синдиката)
        if current_role in ["operative", "commander"] and current_squad and current_squad.lower() != 'none':
            join_room(current_squad)
        if current_role == "syndicate":
            join_room("syndicate_room")

        # Обновляем информацию об активном пользователе
        active_users[request.sid] = {'uid': current_uid, 'callsign': current_callsign, 'role': current_role, 'squad': current_squad}
        
        # Логируем событие как восстановление сессии
        log_terminal_event("reconnection", f"UID:{current_uid}, Callsign:{current_callsign}", "Сессия пользователя восстановлена после переподключения.")

        # Отправляем на клиент актуальное состояние UI
        ui_data = {'role': current_role, 'callsign': current_callsign, 'squad': current_squad, 'show_ui_panel': True}
        if current_role == 'syndicate':
            ui_data['squad_frequencies'] = SQUAD_FREQUENCIES
            ui_data['channel_frequency'] = "Н/Д"
        else:
            ui_data['channel_frequency'] = SQUAD_FREQUENCIES.get(current_squad, '--:--')
        emit('update_ui_state', ui_data)
        
    else:
        # Если в сессии нет данных - это действительно новый гость
        session.setdefault('role', 'guest')
        active_users[request.sid] = {'uid': None, 'callsign': 'Guest', 'role': 'guest', 'squad': None}
        emit('update_ui_state', {'role': 'guest', 'show_ui_panel': False})
        log_terminal_event("connection", f"SID:{request.sid}", "Новое гостевое подключение.")

@socketio.on('disconnect')
def handle_disconnect():
    uid_disconnected = session.get('uid', 'N/A')
    callsign_disconnected = session.get('callsign', 'N/A')
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
        session.permanent = True # Делаем сессию постоянной
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
    log_terminal_event("login_failure", user_info, "Попытка входа не удалась.")
    emit('login_failure', {'message': "❌ Ошибка: Неверный UID или ключ доступа."}, room=request.sid)

@socketio.on('terminal_input')
def handle_terminal_input(data):
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
        output = f"❓ Неизвестная команда или недоступна для вашей роли.\n"
    elif base_command == "login":
        login_parts = args.split(" ")
        if len(login_parts) == 2:
            login({'uid': login_parts[0], 'key': login_parts[1]})
            return
        else:
            output = "ℹ️ Использование: login <UID> <ключ_доступа>\n"
    elif base_command == "help":
        output = "--- 📖 СПИСОК ДОСТУПНЫХ КОМАНД ---\n"
        for cmd in sorted(ROLE_PERMISSIONS.get(current_role, [])):
            output += f"- {cmd}: {COMMAND_DESCRIPTIONS.get(cmd, 'Нет описания.')}\n"
        output += "---------------------------------\n"
    elif base_command == "clear":
        emit('terminal_output', {'output': "<CLEAR_TERMINAL>\n"}, room=request.sid)
        return
    elif base_command == "ping":
        output = "📡 Пинг: стабильно\n"
    elif base_command == "exit":
        if current_role != "guest":
            log_terminal_event("logout", user_info, "Выход из системы.")
            session.clear()
            session['role'] = 'guest'
            output = "🔌 Вы вышли из системы.\n"
            socketio.emit('update_ui_state', {'role': 'guest', 'show_ui_panel': False}, room=request.sid)
        else:
            output = "ℹ️ Вы уже в режиме гостя.\n"
    elif base_command == "contracts":
        load_data_from_sheets()
        output = "--- 📋 ВСЕ АКТИВНЫЕ КОНТРАКТЫ ---\n"
        found = False
        user_squad = session.get('squad')
        for contract in CONTRACTS:
            status = str(contract.get('Статус', '')).lower()
            if status not in ["провален", "выполнен", "failed", "completed"]:
                assignee = contract.get('Назначено', 'None')
                assignee_display = assignee if assignee != 'None' else "Никому"
                if assignee != 'None' and current_role != 'syndicate':
                    assignee_squad = None
                    for user in REGISTERED_USERS.values():
                        if user.get('Позывной') == assignee or user.get('UID') == assignee:
                            assignee_squad = user.get('Отряд')
                            break
                    if user_squad and assignee_squad and user_squad != assignee_squad:
                        assignee_display = "(другой отряд)"
                output += f"ID: {contract.get('ID')}, Название: {contract.get('Название')}, Статус: {status.upper()}, Назначен: {assignee_display}\n"
                found = True
        if not found:
            output += "  Нет контрактов в работе.\n"
        output += "---------------------------------\n"
    elif base_command == "assign_contract" and current_role == "commander":
        assign_parts = args.split(" ")
        if len(assign_parts) != 2:
            output = "ℹ️ Использование: assign_contract <ID_контракта> <UID_исполнителя>\n"
        else:
            try:
                contract_id = int(assign_parts[0])
                operative_uid = assign_parts[1]
                load_data_from_sheets()
                target_contract = next((c for c in CONTRACTS if c.get('ID') == contract_id), None)
                if not target_contract:
                    output = f"❌ Ошибка: Контракт с ID '{contract_id}' не найден.\n"
                else:
                    is_self_assign = (operative_uid == user_uid)
                    operative_data = REGISTERED_USERS.get(operative_uid)
                    if is_self_assign:
                        operative_callsign = user_callsign
                    elif operative_data and operative_data.get('Роль') == 'operative' and operative_data.get('Отряд') == session.get('squad'):
                        operative_callsign = operative_data.get('Позывной')
                    else:
                        output = f"❌ Ошибка: UID '{operative_uid}' не является оперативником вашего отряда.\n"
                        emit('terminal_output', {'output': output + '\n'}, room=request.sid)
                        return
                    updates = {'Назначено': operative_callsign, 'Статус': 'Назначен'}
                    if google_sheets_api.update_row_by_key('Контракты', 'ID', contract_id, updates):
                        output = f"✅ Контракт ID:{contract_id} назначен исполнителю '{operative_callsign}'.\n"
                        log_terminal_event("commander_action", user_info, f"Назначил контракт {contract_id} на {operative_uid}")
                    else:
                        output = "❌ Ошибка: Не удалось обновить контракт в Google Таблицах.\n"
            except ValueError:
                output = "❌ Ошибка: ID контракта должен быть числом.\n"
    elif base_command == "create_request" and current_role == "client":
        req_parts = args.split(" ", 2)
        if len(req_parts) < 3:
            output = "ℹ️ Использование: create_request <ID_Discord> <Причина> <Текст запроса>\n"
        else:
            discord_id, reason, request_text = req_parts
            load_data_from_sheets()
            valid_ids = [req['ID Запроса'] for req in PENDING_REQUESTS if isinstance(req.get('ID Запроса'), int)]
            next_request_id = max(valid_ids) + 1 if valid_ids else 1
            request_data_row = [next_request_id, session['uid'], session['callsign'], discord_id, reason, request_text, 'Новый']
            if google_sheets_api.append_row('Запросы Клиентов', request_data_row):
                output = f"✅ Ваш запрос (ID: {next_request_id}) отправлен на рассмотрение.\n"
                log_terminal_event("client_action", user_info, f"Создан запрос ID={next_request_id}.")
                socketio.emit('terminal_output', {'output': f"🔔 НОВЫЙ ЗАПРОС ОТ КЛИЕНТА ID: {next_request_id}!\n"}, room="syndicate_room")
            else:
                output = "❌ Ошибка: Не удалось создать запрос в Google Таблицах.\n"
    elif base_command == "syndicate_assign" and current_role == "syndicate":
        assign_parts = args.split(" ")
        if len(assign_parts) != 2:
            output = "ℹ️ Использование: syndicate_assign <ID_контракта> <alpha|beta|alpha,beta>\n"
        else:
            try:
                contract_id = int(assign_parts[0])
                squads_str = assign_parts[1].lower()
                valid_squads = all(s in ["alpha", "beta"] for s in squads_str.split(','))
                if not valid_squads:
                    output = "❌ Ошибка: Неверное имя отряда. Допустимо: alpha, beta, alpha,beta.\n"
                else:
                    load_data_from_sheets()
                    target_contract = next((c for c in CONTRACTS if c.get('ID') == contract_id), None)
                    if not target_contract:
                        output = f"❌ Ошибка: Контракт с ID '{contract_id}' не найден.\n"
                    else:
                        updates = {'Назначено': squads_str, 'Статус': 'Назначен'}
                        if google_sheets_api.update_row_by_key('Контракты', 'ID', contract_id, updates):
                            output = f"✅ Контракт ID:{contract_id} назначен отряду(ам): {squads_str}.\n"
                            log_terminal_event("syndicate_action", user_info, f"Назначил контракт {contract_id} на {squads_str}")
                        else:
                            output = "❌ Ошибка: Не удалось обновить контракт в Google Таблицах.\n"
            except ValueError:
                output = "❌ Ошибка: ID контракта должен быть числом.\n"
    else:
        output += "Команда в разработке или не существует.\n"

    emit('terminal_output', {'output': output}, room=request.sid)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)