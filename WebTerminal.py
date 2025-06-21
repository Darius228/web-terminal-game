import os
import json
import secrets
from datetime import datetime
from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
socketio = SocketIO(app)

KEYS_FILE = "access_keys.json"

# --- Инициализация данных ---
contracts = [
    {"id": 1, "title": "Устранение Долга", "description": "Ликвидировать патруль Долга в Темной Долине.", "reward": "50000 RU", "status": "active", "assigned_to": None},
    {"id": 2, "title": "Поиск артефакта", "description": "Найти артефакт 'Ночная Зведа' на Свалке.", "reward": "Аномальное оружие", "status": "active", "assigned_to": None},
    {"id": 3, "title": "Зачистка логова мутантов", "description": "Очистить логово кровососов на Агропроме.", "reward": "10000 RU + еда", "status": "completed", "assigned_to": "Оперативник-1"}
]

dossiers = {}

current_channel_frequency = "142.7 МГц"
pending_requests = []
next_request_id = 1
active_operatives = {}

# --- Глобальные переменные ключей доступа ---
ACCESS_KEYS = {}
KEY_TO_ROLE = {}

def generate_access_keys():
    global ACCESS_KEYS, KEY_TO_ROLE
    ACCESS_KEYS = {
        "operative": [secrets.token_hex(4) for _ in range(4)],
        "commander": [secrets.token_hex(4)],
        "client": [secrets.token_hex(4) for _ in range(5)],
        "syndicate": ["SYNDICATE_OVERRIDE_KEY"]
    }
    KEY_TO_ROLE = {}
    for role, keys in ACCESS_KEYS.items():
        for key in keys:
            KEY_TO_ROLE[key] = role

def save_access_keys():
    with open(KEYS_FILE, 'w') as f:
        json.dump(ACCESS_KEYS, f, indent=4)

def load_access_keys():
    global ACCESS_KEYS, KEY_TO_ROLE
    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, 'r') as f:
                content = f.read().strip()
                if not content:
                    raise ValueError("Файл ключей пуст")
                ACCESS_KEYS = json.loads(content)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[WARNING] Ошибка загрузки {KEYS_FILE}: {e}. Генерируем новые ключи.")
            generate_access_keys()
            save_access_keys()
    else:
        generate_access_keys()
        save_access_keys()

    KEY_TO_ROLE = {}
    for role, keys in ACCESS_KEYS.items():
        for key in keys:
            KEY_TO_ROLE[key] = role

# Загрузка ключей при старте
load_access_keys()

ROLE_PERMISSIONS = {
    "guest": ["help", "login", "clear"],
    "operative": ["help", "login", "clear", "contracts", "sendmsg"],
    "commander": ["help", "login", "clear", "contracts", "setchannel", "ops_online"],
    "client": ["help", "login", "clear", "mycontracts", "requestorder"],
    "syndicate": ["help", "login", "clear", "contracts", "setchannel",
                  "requestorder", "viewrequests", "acceptrequest", "declinerequest",
                  "assignorder", "sendmsg", "ops_online", "exit", "resetkeys", "viewkeys"]
}

@app.route('/')
def index():
    if 'role' not in session:
        session['role'] = 'guest'
    return render_template('index.html')

@socketio.on('connect')
def on_connect():
    current_role = session.get('role', 'guest')
    print(f"Client connected: {request.sid}, role: {current_role}")
    emit('update_ui_state', {'role': current_role, 'channel_frequency': current_channel_frequency})

    if current_role == 'operative':
        display_id = f"operative_{request.sid[:4]}"
        active_operatives[request.sid] = display_id
        join_room(request.sid)
        print(f"Operative {display_id} joined room.")
    elif current_role == 'syndicate':
        join_room('syndicate_room')
        print(f"Syndicate joined syndicate_room.")

@socketio.on('disconnect')
def on_disconnect():
    print(f"Client disconnected: {request.sid}")
    if request.sid in active_operatives:
        display_id = active_operatives.pop(request.sid)
        leave_room(request.sid)
        print(f"Operative {display_id} left room.")
    if session.get('role') == 'syndicate':
        leave_room('syndicate_room')
        print("Syndicate left syndicate_room.")

@socketio.on('terminal_input')
def handle_terminal_input(data):
    global current_channel_frequency, next_request_id, ACCESS_KEYS, KEY_TO_ROLE
    command_full = data['command'].strip()
    command_parts = command_full.split(" ", 1)
    base_command = command_parts[0].lower()
    args = command_parts[1] if len(command_parts) > 1 else ""

    current_role = session.get('role', 'guest')
    output = ""

    if base_command not in ROLE_PERMISSIONS.get(current_role, []):
        output = (f"🚫 ОТКАЗ В ДОСТУПЕ 🚫\n"
                  f"Команда '{base_command}' недоступна для вашей роли ({current_role}).\n"
                  f"Используйте 'help' для списка доступных команд или 'login <ключ>'.\n")
        emit('terminal_output', {'output': output + '\n'})
        return

    if base_command == "help":
        output = f"📖 --- Список команд ({current_role.capitalize()}) ---\n"
        command_descriptions = {
            "help": "Показать это сообщение",
            "login": "Активировать роль с ключом доступа (login <ключ>)",
            "clear": "Очистить экран терминала",
            "contracts": "Показать доступные контракты",
            "sendmsg": "Отправить сообщение другому оперативнику (sendmsg <кому> <сообщение>)",
            "setchannel": "Изменить частоту канала связи (setchannel <частота>) (только Командир/Синдикат)",
            "mycontracts": "Показать ваши активные контракты (только Заказчик)",
            "requestorder": "Создать запрос на новый заказ (requestorder <описание>) (только Заказчик/Синдикат)",
            "viewrequests": "Показать ожидающие запросы на заказ (только Синдикат)",
            "acceptrequest": "Принять запрос на заказ (acceptrequest <id>) (только Синдикат)",
            "declinerequest": "Отклонить запрос на заказ (declinerequest <id>) (только Синдикат)",
            "assignorder": "Назначить контракт оперативнику/командиру (assignorder <id_контракта> <кто>) (только Синдикат)",
            "ops_online": "Показать количество и позывные активных оперативников (только Командир/Синдикат)",
            "resetkeys": "Сбросить и сгенерировать новые ключи (только Синдикат)",
            "viewkeys": "Показать все текущие активные ключи доступа (только Синдикат)",
            "exit": "Завершить сеанс"
        }
        for cmd in sorted(ROLE_PERMISSIONS[current_role]):
            if cmd in command_descriptions:
                output += f"🔹 Команда: {cmd}\n  Описание: {command_descriptions[cmd]}\n\n"

    elif base_command == "login":
        if not args:
            output = "ℹ️ Использование: login <ключ_доступа>\n"
        else:
            if args == ACCESS_KEYS["syndicate"][0]:
                session['role'] = "syndicate"
                join_room('syndicate_room')
                output = "👑 Доступ предоставлен. Роль: СИНДИКАТ (АДМИНИСТРАТОР).\n"
                socketio.emit('update_ui_state', {'role': session['role'], 'channel_frequency': current_channel_frequency})
            else:
                activated_role = KEY_TO_ROLE.get(args)
                if activated_role:
                    if activated_role == "syndicate":
                        output = "❌ Ошибка: Неверный ключ или тип доступа.\n"
                    else:
                        session['role'] = activated_role
                        output = f"✅ Доступ предоставлен. Роль: {activated_role.upper()}.\n"
                        socketio.emit('update_ui_state', {'role': session['role'], 'channel_frequency': current_channel_frequency})
                        if activated_role == 'operative':
                            display_id = f"operative_{request.sid[:4]}"
                            active_operatives[request.sid] = display_id
                            join_room(request.sid)
                            print(f"Operative {display_id} joined room.")
                else:
                    output = "❌ Ошибка: Неверный ключ доступа.\n"

    elif base_command == "contracts":
        output = "📋 --- Доступные Контракты ---\n"
        if not contracts:
            output += "🚫 Контракты отсутствуют.\n"
        else:
            for contract in contracts:
                assigned_to_info = f"  🧑‍💼 Назначено: {contract['assigned_to'] or 'Никому'}\n" if contract['assigned_to'] else ""
                output += (
                    f"🆔 ID: {contract['id']}\n"
                    f"  📌 Название: '{contract['title']}'\n"
                    f"  💰 Награда: {contract['reward']}\n"
                    f"  📊 Статус: {contract['status'].capitalize()}\n"
                    f"{assigned_to_info}\n"
                )

    elif base_command == "clear":
        output = "<CLEAR_TERMINAL>"

    elif base_command == "sendmsg" and current_role == "operative":
        parts = args.split(" ", 1)
        if len(parts) < 2:
            output = "ℹ️ Использование: sendmsg <кому> <сообщение> (кому: 'all' или 'operative_<id>')\n"
        else:
            target = parts[0].lower()
            message = parts[1]
            sender_display_id = active_operatives.get(request.sid, f"operative_{request.sid[:4]}")

            if target == "all":
                for sid_target in active_operatives.keys():
                    emit('terminal_output', {'output': f"[{sender_display_id.upper()} -> ВСЕМ]: {message}\n"}, room=sid_target)
                output = "💬 Сообщение отправлено всем активным оперативникам.\n"
            elif target.startswith("operative_"):
                target_sid = None
                for sid_key, display_id_val in active_operatives.items():
                    if display_id_val == target:
                        target_sid = sid_key
                        break

                if target_sid:
                    emit('terminal_output', {'output': f"[{sender_display_id.upper()} -> {target.upper()}]: {message}\n"}, room=target_sid)
                    output = f"💬 Сообщение отправлено {target.upper()}.\n"
                else:
                    output = f"❌ Ошибка: Оперативник '{target}' не найден или неактивен.\n"
            else:
                output = "❌ Неверный получатель. Используйте 'all' или 'operative_<id>'.\n"

    elif base_command == "setchannel" and current_role in ["commander", "syndicate"]:
        if not args:
            output = "ℹ️ Использование: setchannel <новая_частота> (например, 150.0 МГц)\n"
        else:
            current_channel_frequency = args.strip()
            output = f"📡 Частота канала связи изменена на: {current_channel_frequency}\n"
            socketio.emit('update_ui_state', {'role': current_role, 'channel_frequency': current_channel_frequency})

    elif base_command == "ops_online" and current_role in ["commander", "syndicate"]:
        num_online_ops = len(active_operatives)
        if num_online_ops > 0:
            output = f"🟢 --- АКТИВНЫЕ ОПЕРАТИВНИКИ ({num_online_ops}) ---\n"
            for sid, display_id in active_operatives.items():
                output += f"- {display_id} (SID: {sid[:4]})\n"
        else:
            output = "🚫 В данный момент активных оперативников нет.\n"

    elif base_command == "mycontracts" and current_role == "client":
        client_contracts = [c for c in contracts if c['status'] != 'completed']
        if client_contracts:
            output = "📋 --- Ваши Активные Контракты ---\n"
            for contract in client_contracts:
                output += (
                    f"🆔 ID: {contract['id']}\n"
                    f"  📌 Название: '{contract['title']}'\n"
                    f"  📊 Статус: {contract['status'].capitalize()}\n\n"
                )
        else:
            output = "🚫 У вас нет активных контрактов.\n"

    elif base_command == "requestorder" and current_role in ["client", "syndicate"]:
        if not args:
            output = "ℹ️ Использование: requestorder <краткое_описание_заказа>\n"
        else:
            request_id = next_request_id
            pending_requests.append({
                "id": request_id,
                "client_sid": request.sid,
                "description": args,
                "status": "pending",
                "timestamp": datetime.now().isoformat()
            })
            next_request_id += 1
            output = (
                f"📨 Запрос на заказ ID:{request_id} создан и отправлен.\n"
                f"Ожидайте решения.\n"
            )
            if current_role == "client":
                socketio.emit('terminal_output', {'output': f"[Уведомление] НОВЫЙ ЗАПРОС НА ЗАКАЗ ID:{request_id} от Заказчика ({request.sid[:4]}). Описание: '{args}'\n"}, room='syndicate_room')
            elif current_role == "syndicate":
                output = f"📨 Запрос на заказ ID:{request_id} создан Синдикатом. Описание: '{args}'\n"

    elif base_command == "viewrequests" and current_role == "syndicate":
        output = "📋 --- ОЖИДАЮЩИЕ ЗАПРОСЫ НА ЗАКАЗ ---\n"
        if not pending_requests:
            output += "🚫 Нет ожидающих запросов.\n"
        else:
            for req in pending_requests:
                output += (
                    f"🆔 ID: {req['id']}\n"
                    f"  📌 Описание: '{req['description']}'\n"
                    f"  📊 Статус: {req['status'].capitalize()}\n"
                    f"  ⏰ Время: {req['timestamp']}\n"
                    f"  🆔 От клиента SID: {req['client_sid'][:4]}\n\n"
                )

    elif base_command == "acceptrequest" and current_role == "syndicate":
        try:
            req_id = int(args.strip())
            req_found = None
            for req in pending_requests:
                if req['id'] == req_id:
                    req_found = req
                    break

            if req_found:
                pending_requests.remove(req_found)
                new_contract_id = max([c['id'] for c in contracts]) + 1 if contracts else 1
                contracts.append({
                    "id": new_contract_id,
                    "title": f"Заказ: {req_found['description'][:30]}...",
                    "description": req_found['description'],
                    "reward": "Уточняется",
                    "status": "active",
                    "assigned_to": None
                })
                output = (
                    f"✅ Запрос ID:{req_id} принят.\n"
                    f"Создан новый контракт ID:{new_contract_id}.\n"
                )
                if req_found.get('client_sid'):
                    emit('terminal_output', {'output': f"[УВЕДОМЛЕНИЕ] Ваш запрос ID:{req_id} принят. Контракт ID:{new_contract_id} создан.\n"}, room=req_found['client_sid'])
            else:
                output = f"❌ Ошибка: Запрос с ID:{req_id} не найден среди ожидающих.\n"
        except ValueError:
            output = "ℹ️ Использование: acceptrequest <ID_запроса>\n"

    elif base_command == "declinerequest" and current_role == "syndicate":
        try:
            req_id = int(args.strip())
            req_found = None
            for req in pending_requests:
                if req['id'] == req_id:
                    req_found = req
                    break

            if req_found:
                pending_requests.remove(req_found)
                output = f"⚠️ Запрос ID:{req_id} отклонен.\n"
                if req_found.get('client_sid'):
                    emit('terminal_output', {'output': f"[УВЕДОМЛЕНИЕ] Ваш запрос ID:{req_id} был отклонен.\n"}, room=req_found['client_sid'])
            else:
                output = f"❌ Ошибка: Запрос с ID:{req_id} не найден среди ожидающих.\n"
        except ValueError:
            output = "ℹ️ Использование: declinerequest <ID_запроса>\n"

    elif base_command == "assignorder" and current_role == "syndicate":
        parts = args.split(" ", 1)
        if len(parts) < 2:
            output = "ℹ️ Использование: assignorder <ID_контракта> <кому>\n"
        else:
            try:
                contract_id = int(parts[0])
                assignee = parts[1].strip()

                contract_found = None
                for c in contracts:
                    if c['id'] == contract_id:
                        contract_found = c
                        break

                if not contract_found:
                    output = f"❌ Контракт с ID:{contract_id} не найден.\n"
                else:
                    contract_found['assigned_to'] = assignee
                    output = f"✅ Контракт ID:{contract_id} назначен {assignee}.\n"
            except ValueError:
                output = "❌ Ошибка: ID контракта должен быть числом.\n"

    elif base_command == "exit":
        session['role'] = 'guest'
        output = "🔌 Вы вышли из системы. Роль сброшена до гостя.\n"
        socketio.emit('update_ui_state', {'role': 'guest', 'channel_frequency': current_channel_frequency})

    elif base_command == "resetkeys" and current_role == "syndicate":
        generate_access_keys()
        save_access_keys()
        output = "--- 🔑 Ключи доступа сброшены и сгенерированы новые: ---\n"
        for role, keys in ACCESS_KEYS.items():
            if role != "syndicate":
                output += f"{role.upper()}: {', '.join(keys)}\n"
        output += "⚠️ Старые ключи недействительны.\n"

    elif base_command == "viewkeys" and current_role == "syndicate":
        output = "--- 🔑 ТЕКУЩИЕ АКТИВНЫЕ КЛЮЧИ ДОСТУПА ---\n"
        for role, keys in ACCESS_KEYS.items():
            if role == "guest":
                continue
            output += f"{role.upper()}: {', '.join(keys)}\n"
        output += "--------------------------------------\n"

    else:
        output = (f"❓ Неизвестная команда: '{base_command}' или недоступна для вашей роли ({current_role}).\n"
                  "Введите 'help' для списка команд.\n")

    emit('terminal_output', {'output': output + '\n'})

if __name__ == '__main__':
    print("\n--- КЛЮЧИ ДОСТУПА ---")
    for role, keys in ACCESS_KEYS.items():
        print(f"{role.upper()}: {', '.join(keys)}")
    print("---------------------\n")
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)