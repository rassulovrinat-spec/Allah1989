"""
Универсальный парсер прайс-листов: Excel (.xlsx/.xls) и PDF.
Умеет находить данные в любых таблицах — ищет строку заголовков автоматически,
поддерживает кириллические и латинские названия колонок,
обрабатывает нестандартные числовые форматы цен.
"""
import re
from io import BytesIO


# ── Публичный API ──────────────────────────────────────────────────────────────

def parse_price_file(file_bytes: bytes, filename: str = "") -> list:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "xlsx"
    if ext == "pdf":
        return _parse_pdf(file_bytes)
    return _parse_excel(file_bytes)


# ── Excel ──────────────────────────────────────────────────────────────────────

def _parse_excel(file_bytes: bytes) -> list:
    import openpyxl
    wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)

    all_items = []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        items = _extract_from_rows(rows)
        all_items.extend(items)

    if not all_items:
        raise ValueError(
            "Не удалось распознать прайс-лист. "
            "Убедитесь что файл содержит колонку с ценами (число > 0)."
        )
    return all_items


# ── PDF ────────────────────────────────────────────────────────────────────────

def _parse_pdf(file_bytes: bytes) -> list:
    import pdfplumber
    all_items = []

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                # pdfplumber возвращает списки строк
                rows = [tuple(c if c is not None else "" for c in r) for r in table]
                items = _extract_from_rows(rows)
                all_items.extend(items)

        # Если таблиц нет — пробуем извлечь текстом построчно
        if not all_items:
            for page in pdf.pages:
                text_rows = _pdf_text_to_rows(page)
                if text_rows:
                    items = _extract_from_rows(text_rows)
                    all_items.extend(items)

    # Дедупликация
    seen = set()
    unique = []
    for item in all_items:
        key = (item["article"], item["name"], item["base_price"])
        if key not in seen:
            seen.add(key)
            unique.append(item)

    if not unique:
        raise ValueError(
            "Не удалось извлечь данные из PDF. "
            "Убедитесь что PDF содержит таблицы с ценами."
        )
    return unique


def _pdf_text_to_rows(page) -> list:
    """Превращает текстовые строки PDF в псевдо-таблицу."""
    text = page.extract_text() or ""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    rows = []
    for line in lines:
        # Разбиваем по множественным пробелам или табуляции
        parts = re.split(r"\s{2,}|\t", line)
        if len(parts) >= 2:
            rows.append(tuple(parts))
    return rows


# ── Универсальная логика поиска данных ────────────────────────────────────────

def _extract_from_rows(rows: list) -> list:
    """
    Находит строку заголовков, определяет колонки, извлекает товары.
    Работает с любой таблицей.
    """
    if not rows:
        return []

    # Ищем строку с заголовками (первая строка где хотя бы одна ячейка — ключевое слово)
    header_idx = _find_header_row(rows)
    if header_idx is None:
        # Нет явных заголовков — попробуем угадать по первой строке с ценой
        header_idx = 0

    headers = [_norm(c) for c in rows[header_idx]]

    # Определяем индексы колонок
    price_col    = _find_col(headers, PRICE_KW)
    article_col  = _find_col(headers, ARTICLE_KW)
    name_col     = _find_col(headers, NAME_KW)
    category_col = _find_col(headers, CATEGORY_KW)
    dims_col     = _find_col(headers, DIMS_KW)

    # Если name не найден — берём первый нечисловой столбец
    if name_col is None:
        for i, h in enumerate(headers):
            if h and not _as_price(h):
                name_col = i
                break

    # Если price не найден по заголовку — ищем первый столбец с числами в данных
    if price_col is None:
        price_col = _detect_price_col(rows, header_idx + 1)

    if price_col is None:
        return []

    items = []
    for row in rows[header_idx + 1:]:
        if not any(_norm(c) for c in row):
            continue

        raw_price = _cell(row, price_col)
        base = _as_price(raw_price)
        if base is None or base <= 0:
            continue

        name = _cell(row, name_col)
        if not name or _as_price(name) is not None:
            # Если имя — число, скорее всего это строка-разделитель
            continue

        # Пропускаем строки-заголовки внутри таблицы
        if _is_section_header(name, base):
            continue

        article  = _cell(row, article_col)
        category = _cell(row, category_col)
        dims     = _cell(row, dims_col)

        full_name = f"{name} ({dims})" if dims and dims not in name else name

        items.append({
            "article":      article,
            "name":         full_name,
            "category":     category,
            "base_price":   base,
            "markup_price": round(base * 1.3, 2),
        })

    return items


def _find_header_row(rows: list):
    """Ищет строку, в которой есть ключевые слова заголовков."""
    all_kw = set(PRICE_KW + NAME_KW + ARTICLE_KW + CATEGORY_KW + DIMS_KW)
    for i, row in enumerate(rows):
        cells = [_norm(c) for c in row]
        hits = sum(1 for c in cells if any(kw in c for kw in all_kw))
        if hits >= 2:
            return i
    # Второй проход — достаточно одного ключевого слова
    for i, row in enumerate(rows):
        cells = [_norm(c) for c in row]
        if any(any(kw in c for kw in all_kw) for c in cells):
            return i
    return None


def _detect_price_col(rows: list, start: int) -> int:
    """Определяет колонку с ценами по содержимому данных."""
    col_prices = {}
    for row in rows[start:start + 20]:
        for i, cell in enumerate(row):
            v = _as_price(str(cell or ""))
            if v and v > 0:
                col_prices[i] = col_prices.get(i, 0) + 1
    if not col_prices:
        return None
    return max(col_prices, key=col_prices.get)


def _is_section_header(name: str, price: float) -> bool:
    """Проверяет не является ли строка заголовком раздела."""
    # Если цена подозрительно круглая и имя короткое — возможно раздел
    if len(name) < 3:
        return True
    return False


# ── Вспомогательные функции ───────────────────────────────────────────────────

PRICE_KW    = ["цена", "price", "стоимость", "прайс", "оптовая", "руб", "rub", "розн", "опт"]
ARTICLE_KW  = ["артикул", "арт.", "арт ", "код", "article", "sku", "id", "№"]
NAME_KW     = ["наименование", "название", "товар", "модель", "продукт", "name", "product", "item", "description"]
CATEGORY_KW = ["категория", "раздел", "группа", "тип", "вид", "category", "type", "section"]
DIMS_KW     = ["размер", "габарит", "dimension", "ш×", "ш x", "ш*", "дхш", "дхв", "длина", "ширина", "высота", "wxh", "lxw"]


def _norm(val) -> str:
    """Нормализует значение ячейки для сравнения."""
    if val is None:
        return ""
    return str(val).strip().lower()


def _cell(row, col) -> str:
    """Безопасно извлекает строковое значение ячейки."""
    if col is None or col >= len(row):
        return ""
    v = row[col]
    return str(v).strip() if v is not None else ""


def _find_col(headers: list, keywords: list):
    """Находит индекс колонки по ключевым словам."""
    for i, h in enumerate(headers):
        for kw in keywords:
            if kw in h:
                return i
    return None


_PRICE_CLEAN = re.compile(r"[^\d.,]")
_PRICE_RANGE = re.compile(r"(\d[\d\s.,]+)\s*[-–—]\s*\d")  # диапазон "1000 - 2000"


def _as_price(val: str):
    """
    Парсит цену из строки любого формата:
    45000, 45 000, 45.000, 45,000.00, 45 000 руб., 45000.00р и т.д.
    Возвращает float или None.
    """
    if not val:
        return None
    s = str(val).strip()

    # Диапазон — берём первое значение
    m = _PRICE_RANGE.search(s)
    if m:
        s = m.group(1)

    # Убираем всё кроме цифр, точки и запятой
    s = _PRICE_CLEAN.sub("", s)
    if not s:
        return None

    # Убираем пробелы (разделители тысяч)
    s = s.replace(" ", "")

    # Определяем десятичный разделитель
    if "," in s and "." in s:
        # Формат: 1.234,56 или 1,234.56
        if s.index(",") > s.index("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # Запятая как десятичный: 45000,50
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")

    try:
        return float(s)
    except ValueError:
        return None


# Обратная совместимость
def parse_excel(file_bytes: bytes) -> list:
    return _parse_excel(file_bytes)
