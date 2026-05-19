from io import BytesIO


def parse_price_file(file_bytes: bytes, filename: str = "") -> list:
    """Parse Excel or PDF price list, return items with +30% markup."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "pdf":
        return parse_pdf(file_bytes)
    return parse_excel(file_bytes)


def parse_pdf(file_bytes: bytes) -> list:
    import pdfplumber
    items = []
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                headers = [str(c or "").strip().lower() for c in table[0]]
                price_col     = _find_col(headers, ["цена", "price", "стоимость", "прайс", "оптовая"])
                article_col   = _find_col(headers, ["артикул", "арт", "код", "article", "sku"])
                name_col      = _find_col(headers, ["наименование", "название", "товар", "модель", "name"])
                category_col  = _find_col(headers, ["категория", "раздел", "группа", "category"])
                dims_col      = _find_col(headers, ["размер", "габарит", "dimension", "ш×", "ш×г", "wxh"])

                if name_col is None and headers:
                    name_col = 0

                if price_col is None:
                    for i, val in enumerate(table[1]):
                        if val and _is_price(val):
                            price_col = i
                            break

                if price_col is None:
                    continue

                for row in table[1:]:
                    if not any(row):
                        continue
                    raw = row[price_col] if price_col < len(row) else None
                    if not raw:
                        continue
                    try:
                        base = float(str(raw).replace(",", ".").replace(" ", "").replace("\xa0", ""))
                    except ValueError:
                        continue
                    if base <= 0:
                        continue
                    name = _safe_cell(row, name_col)
                    if not name:
                        continue
                    dims = _safe_cell(row, dims_col)
                    full_name = f"{name} ({dims})" if dims and dims not in name else name
                    items.append({
                        "article":      _safe_cell(row, article_col),
                        "name":         full_name,
                        "category":     _safe_cell(row, category_col),
                        "base_price":   base,
                        "markup_price": round(base * 1.3, 2),
                    })

    if not items:
        raise ValueError("Не удалось извлечь данные из PDF. Убедитесь, что PDF содержит таблицы с ценами.")
    return items


def parse_excel(file_bytes: bytes) -> list:
    import openpyxl
    wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
    ws = wb.active

    headers = [str(cell.value or "").strip().lower() for cell in ws[1]]

    price_col    = _find_col(headers, ["цена", "price", "стоимость", "прайс", "оптовая"])
    article_col  = _find_col(headers, ["артикул", "арт", "код", "article", "sku", "id"])
    name_col     = _find_col(headers, ["наименование", "название", "товар", "модель", "name", "product"])
    category_col = _find_col(headers, ["категория", "раздел", "группа", "category", "тип"])
    dims_col     = _find_col(headers, ["размер", "габарит", "dimension", "ш×"])

    if name_col is None and headers:
        name_col = 0

    if price_col is None:
        for i in range(len(headers)):
            val = ws.cell(2, i + 1).value
            if isinstance(val, (int, float)) and val > 0:
                price_col = i
                break

    if price_col is None:
        raise ValueError("Не найдена колонка с ценой. Убедитесь, что есть колонка «Цена» или «Стоимость».")

    items = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not any(row):
            continue
        raw = row[price_col]
        if raw is None:
            continue
        try:
            base = float(str(raw).replace(",", ".").replace(" ", ""))
        except ValueError:
            continue
        if base <= 0:
            continue
        name = _safe(row, name_col)
        if not name:
            continue
        dims = _safe(row, dims_col)
        full_name = f"{name} ({dims})" if dims and dims not in name else name
        items.append({
            "article":      _safe(row, article_col),
            "name":         full_name,
            "category":     _safe(row, category_col),
            "base_price":   base,
            "markup_price": round(base * 1.3, 2),
        })

    return items


# ── keep old name for any existing imports ────────────────────────────────────
parse_excel_legacy = parse_excel


def _find_col(headers, keywords):
    for i, h in enumerate(headers):
        for kw in keywords:
            if kw in h:
                return i
    return None


def _safe(row, col):
    if col is None or col >= len(row):
        return ""
    v = row[col]
    return str(v).strip() if v is not None else ""


def _safe_cell(row, col):
    if col is None or col >= len(row):
        return ""
    v = row[col]
    return str(v).strip() if v is not None else ""


def _is_price(val):
    try:
        float(str(val).replace(",", ".").replace(" ", "").replace("\xa0", ""))
        return True
    except ValueError:
        return False
