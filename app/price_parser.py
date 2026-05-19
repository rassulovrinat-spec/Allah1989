from io import BytesIO


def parse_excel(file_bytes: bytes) -> list:
    import openpyxl
    wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
    ws = wb.active

    # Read header row
    headers = []
    for cell in ws[1]:
        headers.append(str(cell.value or "").strip().lower())

    # Detect columns
    price_col = _find_col(headers, ["цена", "price", "стоимость", "прайс", "оптовая"])
    article_col = _find_col(headers, ["артикул", "арт", "код", "article", "sku", "id"])
    name_col = _find_col(headers, ["наименование", "название", "товар", "модель", "name", "product"])
    category_col = _find_col(headers, ["категория", "раздел", "группа", "category", "тип"])

    # Fallback: use first column as name if not found
    if name_col is None and len(headers) > 0:
        name_col = 0

    # If no price column found by name, find first numeric column in row 2
    if price_col is None:
        for i in range(len(headers)):
            val = ws.cell(2, i + 1).value
            if isinstance(val, (int, float)) and val > 0:
                price_col = i
                break

    if price_col is None:
        raise ValueError("Не найдена колонка с ценой. Убедитесь, что в Excel есть колонка 'Цена' или 'Стоимость'.")

    items = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not any(row):
            continue
        raw_price = row[price_col]
        if raw_price is None:
            continue
        try:
            base_price = float(str(raw_price).replace(",", ".").replace(" ", ""))
        except ValueError:
            continue
        if base_price <= 0:
            continue

        article = _safe(row, article_col)
        name = _safe(row, name_col)
        category = _safe(row, category_col)

        if not name:
            continue

        items.append({
            "article": article,
            "name": name,
            "category": category,
            "base_price": base_price,
            "markup_price": round(base_price * 1.3, 2),
        })

    return items


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
