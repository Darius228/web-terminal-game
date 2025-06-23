# google_sheets_api.py

import gspread
import os
import json # Добавляем импорт json

# Имя Google Таблицы
SPREADSHEET_NAME = 'Stalker Terminal Database'

# Глобальные переменные
gc = None
spreadsheet = None
worksheets_cache = {}

def init_google_sheets():
    """
    Инициализирует клиент gspread, используя учетные данные из переменных окружения.
    """
    global gc, spreadsheet
    try:
        # Получаем JSON-строку с учетными данными из переменной окружения
        creds_json_str = os.environ.get('GOOGLE_CREDENTIALS_JSON')
        if not creds_json_str:
            print("❌ Ошибка: Переменная окружения 'GOOGLE_CREDENTIALS_JSON' не найдена.")
            print("Инструкции по ее созданию вы найдете в руководстве по развертыванию.")
            return False

        # Преобразуем JSON-строку в словарь Python
        creds_dict = json.loads(creds_json_str)

        # Авторизация с помощью словаря с учетными данными
        gc = gspread.service_account_from_dict(creds_dict)
        
        # Открытие таблицы по имени
        spreadsheet = gc.open(SPREADSHEET_NAME)
        print(f"✅ Google Таблица '{SPREADSHEET_NAME}' успешно открыта.")
        return True
    except Exception as e:
        print(f"❌ Ошибка при инициализации Google Таблиц: {e}")
        print("Убедитесь, что переменная окружения 'GOOGLE_CREDENTIALS_JSON' содержит корректные данные.")
        print(f"Также проверьте, что сервисный аккаунт имеет доступ к таблице '{SPREADSHEET_NAME}'.")
        return False

def get_worksheet(worksheet_name):
    """
    Получает лист по имени из кеша или запрашивает его, если не найден.
    Возвращает объект листа gspread.
    """
    if worksheet_name not in worksheets_cache:
        if spreadsheet is None:
            if not init_google_sheets():
                return None
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
            worksheets_cache[worksheet_name] = worksheet
            print(f"ℹ️ Лист '{worksheet_name}' загружен.")
        except gspread.exceptions.WorksheetNotFound:
            print(f"❌ Ошибка: Лист '{worksheet_name}' не найден в таблице '{SPREADSHEET_NAME}'.")
            return None
        except Exception as e:
            print(f"❌ Ошибка при получении листа '{worksheet_name}': {e}")
            return None
    return worksheets_cache[worksheet_name]

def get_all_records(worksheet_name):
    """
    Получает все записи (строки) из указанного листа как список словарей.
    Каждый словарь представляет строку, где ключи - это заголовки столбцов.
    """
    worksheet = get_worksheet(worksheet_name)
    if worksheet:
        try:
            records = worksheet.get_all_records()
            return records
        except Exception as e:
            print(f"❌ Ошибка при чтении данных из листа '{worksheet_name}': {e}")
    return []

def append_row(worksheet_name, row_data):
    """
    Добавляет новую строку в конец указанного листа.
    `row_data` должен быть списком значений, соответствующих порядку столбцов.
    """
    worksheet = get_worksheet(worksheet_name)
    if worksheet:
        try:
            worksheet.append_row(row_data)
            return True
        except Exception as e:
            print(f"❌ Ошибка при добавлении строки в лист '{worksheet_name}': {e}")
    return False

def update_row_by_key(worksheet_name, key_column, key_value, update_data):
    """
    Находит строку по значению в ключевой колонке и обновляет указанные ячейки.
    `key_column`: Имя столбца для поиска.
    `key_value`: Значение, по которому ищем строку.
    `update_data`: Словарь {имя_столбца: новое_значение}.
    """
    worksheet = get_worksheet(worksheet_name)
    if not worksheet:
        return False

    try:
        # Получаем все данные, включая заголовки
        all_data = worksheet.get_all_values()
        if not all_data:
            return False

        headers = all_data[0] # Первая строка - это заголовки
        data_rows = all_data[1:] # Остальные строки - данные

        # Находим индекс ключевой колонки
        try:
            key_col_idx = headers.index(key_column)
        except ValueError:
            print(f"❌ Ошибка: Колонка '{key_column}' не найдена в листе '{worksheet_name}'.")
            return False

        # Находим строку по значению ключа
        row_idx_to_update = -1
        for i, row in enumerate(data_rows):
            if len(row) > key_col_idx and str(row[key_col_idx]) == str(key_value):
                row_idx_to_update = i + 2 # +1 для пропуска заголовков, +1 для индексации gspread (1-based)
                break

        if row_idx_to_update == -1:
            # print(f"ℹ️ Строка с '{key_column}'='{key_value}' не найдена для обновления в листе '{worksheet_name}'.")
            return False

        # Обновляем ячейки
        updates = []
        for col_name, new_value in update_data.items():
            try:
                col_idx = headers.index(col_name) # Индекс столбца для обновления
                # Cell (row, col) - оба 1-based
                updates.append({'range': gspread.utils.rowcol_to_a1(row_idx_to_update, col_idx + 1), 'values': [[new_value]]})
            except ValueError:
                print(f"⚠️ Предупреждение: Колонка '{col_name}' для обновления не найдена в листе '{worksheet_name}'. Пропускаем.")
                continue
        
        if updates:
            worksheet.batch_update(updates)
            return True
        return False

    except Exception as e:
        print(f"❌ Ошибка при обновлении строки в листе '{worksheet_name}': {e}")
        return False

def delete_row_by_key(worksheet_name, key_column, key_value):
    """
    Находит строку по значению в ключевой колонке и удаляет ее.
    """
    worksheet = get_worksheet(worksheet_name)
    if not worksheet:
        return False

    try:
        # Получаем все записи, чтобы найти строку
        records = worksheet.get_all_records()
        headers = worksheet.row_values(1) # Получаем заголовки

        # Находим индекс ключевой колонки
        try:
            key_col_idx = headers.index(key_column)
        except ValueError:
            print(f"❌ Ошибка: Колонка '{key_column}' не найдена в листе '{worksheet_name}'.")
            return False

        # Итерируем по записям, чтобы найти строку для удаления
        row_index_to_delete = -1 # Индекс в gspread (1-based)
        for i, record in enumerate(records):
            if str(record.get(key_column)) == str(key_value):
                row_index_to_delete = i + 2 # +1 для заголовков, +1 для 1-based индексации gspread
                break

        if row_index_to_delete != -1:
            worksheet.delete_rows(row_index_to_delete)
            return True
        else:
            # print(f"ℹ️ Строка с '{key_column}'='{key_value}' не найдена для удаления в листе '{worksheet_name}'.")
            return False
    except Exception as e:
        print(f"❌ Ошибка при удалении строки в листе '{worksheet_name}': {e}")
        return False