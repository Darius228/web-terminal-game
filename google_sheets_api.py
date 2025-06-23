import os
import json
import gspread
from google.oauth2.service_account import Credentials

# --- Константы ---
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
SPREADSHEET_ID = os.environ.get('GOOGLE_SHEET_ID')
SERVICE_ACCOUNT_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')

# --- Глобальные переменные ---
gc = None
spreadsheet = None

def init_google_sheets():
    global gc, spreadsheet

    if not SERVICE_ACCOUNT_JSON or not SPREADSHEET_ID:
        print("❌ Переменные окружения GOOGLE_CREDENTIALS_JSON или GOOGLE_SHEET_ID не заданы.")
        return False

    try:
        creds_dict = json.loads(SERVICE_ACCOUNT_JSON)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPE)
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        print("✅ Успешное подключение к Google Таблицам.")
        return True
    except Exception as e:
        print(f"❌ Ошибка при инициализации Google Sheets: {e}")
        return False

def get_all_records(sheet_name):
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
        return worksheet.get_all_records()
    except Exception as e:
        print(f"❌ Ошибка при получении данных из листа '{sheet_name}': {e}")
        return []

def append_row(sheet_name, row_data):
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
        worksheet.append_row(row_data, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        print(f"❌ Ошибка при добавлении строки в '{sheet_name}': {e}")
        return False

def update_row_by_key(sheet_name, key_column, key_value, updated_fields):
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
        records = worksheet.get_all_records()
        headers = worksheet.row_values(1)
        for idx, row in enumerate(records, start=2):
            if str(row.get(key_column)) == str(key_value):
                for field, new_value in updated_fields.items():
                    if field in headers:
                        col_idx = headers.index(field) + 1
                        worksheet.update_cell(idx, col_idx, new_value)
                return True
        print(f"⚠️ Строка с {key_column} = {key_value} не найдена в '{sheet_name}'.")
        return False
    except Exception as e:
        print(f"❌ Ошибка при обновлении строки в '{sheet_name}': {e}")
        return False

def delete_row_by_key(sheet_name, key_column, key_value):
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
        records = worksheet.get_all_records()
        for idx, row in enumerate(records, start=2):
            if str(row.get(key_column)) == str(key_value):
                worksheet.delete_rows(idx)
                return True
        print(f"⚠️ Строка с {key_column} = {key_value} не найдена.")
        return False
    except Exception as e:
        print(f"❌ Ошибка при удалении строки из '{sheet_name}': {e}")
        return False

# --- Тестовая инициализация (опционально, только при прямом запуске) ---
if __name__ == "__main__":
    print("🧪 Локальный тест Google Sheets...")
    if init_google_sheets():
        print("✅ Sheets готов к использованию")
    else:
        print("❌ Sheets не инициализирован")
