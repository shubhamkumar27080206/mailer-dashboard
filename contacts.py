"""Read the HR list (xlsx / xls / csv), detect columns, validate and de-duplicate emails.

Pure-Python (no pandas) so the Vercel function stays small and cold starts are fast.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from company import resolve_company

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-']+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$")
EMAIL_FIND = re.compile(r"[A-Za-z0-9._%+\-']+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")

EMAIL_NAMES = {"email", "mail", "emailid", "emailaddress", "hremail", "hrmail", "eid", "emailids"}
NAME_NAMES = {"name", "hrname", "contactname", "fullname", "contactperson", "recruiter", "recruitername"}
COMPANY_NAMES = {"company", "companyname", "organization", "organisation", "employer", "firm"}

MAX_ROWS = 5000


def _norm(col: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(col).lower())


def _clean(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none") else s


def _cell(v) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return _clean(v)


def _to_table(matrix: list[list[str]]) -> tuple[list[str], list[dict]]:
    matrix = [r for r in matrix if any(c for c in r)]
    if not matrix:
        return [], []
    header = [(c or f"Column {i + 1}").strip() for i, c in enumerate(matrix[0])]
    seen: dict[str, int] = {}
    cols = []
    for h in header:  # make duplicate headers unique
        seen[h] = seen.get(h, 0) + 1
        cols.append(h if seen[h] == 1 else f"{h} ({seen[h]})")
    rows = []
    for r in matrix[1:MAX_ROWS + 1]:
        r = list(r) + [""] * (len(cols) - len(r))
        rows.append({c: r[i] for i, c in enumerate(cols)})
    return cols, rows


def read_table(data: bytes, filename: str) -> tuple[list[str], list[dict]]:
    """Return (columns, rows) from an uploaded .xlsx / .xls / .csv. All values are strings."""
    ext = Path(filename).suffix.lower()
    if ext == ".csv":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        matrix = [[_cell(c) for c in row] for row in csv.reader(io.StringIO(text))]
    elif ext == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        matrix = [[_cell(c) for c in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
    elif ext == ".xls":
        import xlrd
        book = xlrd.open_workbook(file_contents=data)
        sh = book.sheet_by_index(0)
        matrix = [[_cell(sh.cell_value(r, c)) for c in range(sh.ncols)] for r in range(sh.nrows)]
    else:
        raise ValueError(f"Unsupported file type: {ext or '(none)'}")
    return _to_table(matrix)


def _detect(columns: list[str], wanted: set[str]) -> str | None:
    for c in columns:
        if _norm(c) in wanted:
            return c
    return None


def detect_email_column(columns: list[str], rows: list[dict]) -> str | None:
    hit = _detect(columns, EMAIL_NAMES)
    if hit:
        return hit
    for c in columns:  # any header containing "mail"
        if "mail" in _norm(c):
            return c
    best, best_n = None, 0  # fallback: column whose values contain the most "@"
    for c in columns:
        n = sum(1 for r in rows if "@" in r.get(c, ""))
        if n > best_n:
            best, best_n = c, n
    return best


def detect_name_column(columns: list[str]) -> str | None:
    return _detect(columns, NAME_NAMES)


def detect_company_column(columns: list[str]) -> str | None:
    return _detect(columns, COMPANY_NAMES)


def build_contacts(rows: list[dict], email_col: str, name_col: str | None = None,
                   company_col: str | None = None, sent: set[str] | None = None,
                   overrides: dict | None = None) -> list[dict]:
    """Return contacts: email, name, company, detected_company, status.

    status is one of: valid, invalid, duplicate, already sent. Blank rows are dropped.
    """
    sent = {s.lower() for s in (sent or set())}
    seen: set[str] = set()
    out = []
    for r in rows:
        raw = _clean(r.get(email_col))
        if not raw:
            continue
        found = EMAIL_FIND.findall(raw)
        email = (found[0] if len(found) == 1 else raw).lower()
        name = _clean(r.get(name_col)) if name_col else ""
        company = _clean(r.get(company_col)) if company_col else ""
        if not EMAIL_RE.match(email):
            status = "invalid"
        elif email in seen:
            status = "duplicate"
        elif email in sent:
            status = "already sent"
            seen.add(email)
        else:
            status = "valid"
            seen.add(email)
        detected, known = resolve_company(email, company, overrides) if status != "invalid" else ("", False)
        out.append({"email": email, "name": name, "company": company,
                    "detected_company": detected if known else "(none - personal mail)",
                    "status": status})
    return out
