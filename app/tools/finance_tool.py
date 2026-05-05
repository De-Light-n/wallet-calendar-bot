"""Finance tool – records transactions to a per-user Google Sheets ledger."""
from __future__ import annotations

import datetime
import logging
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import OAuthToken, User
from app.tools.google_utils import execute_with_retry, is_spreadsheet_missing

logger = logging.getLogger(__name__)

ALLOWED_TRANSACTION_TYPES = {"expense": "Expense", "income": "Income"}

ALLOWED_CATEGORIES: dict[str, set[str]] = {
    "Expense": {
        "Food & Dining",
        "Transportation",
        "Groceries",
        "Entertainment",
        "Health",
        "Shopping",
        "Other",
    },
    "Income": {
        "Salary",
        "Freelance",
        "Gifts",
    },
}


def _resolve_user(
    db: Session,
    *,
    user_id: int | None = None,
    telegram_id: int | None = None,
) -> User | None:
    """Resolve a user by internal ID or legacy telegram ID."""
    if user_id is not None:
        return db.query(User).filter(User.id == user_id).first()
    if telegram_id is not None:
        return db.query(User).filter(User.telegram_id == telegram_id).first()
    return None


def _get_google_credentials(
    db: Session,
    *,
    user_id: int | None = None,
    telegram_id: int | None = None,
) -> Credentials | None:
    """Build OAuth credentials for Google APIs using the stored user token."""
    user = _resolve_user(db, user_id=user_id, telegram_id=telegram_id)
    if not user:
        logger.warning(
            "Google credentials unavailable: user not found (user_id=%s, telegram_id=%s)",
            user_id,
            telegram_id,
        )
        return None
    if not user.oauth_token:
        logger.warning(
            "Google credentials unavailable: user id=%s has no OAuth token (not connected)",
            user.id,
        )
        return None

    token: OAuthToken = user.oauth_token
    logger.info(
        "Built Google credentials for user id=%s (scopes=%s, has_refresh_token=%s)",
        user.id,
        token.scopes,
        bool(token.refresh_token),
    )
    return Credentials(
        token=token.access_token,
        refresh_token=token.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=token.scopes.split() if token.scopes else [],
    )


def _normalize_transaction_type(transaction_type: str) -> str | None:
    return ALLOWED_TRANSACTION_TYPES.get(transaction_type.strip().lower())


# ──────────────────────────────────────────────────────────────────────────────
# Spreadsheet provisioning (built from scratch, no Drive copy required)
# ──────────────────────────────────────────────────────────────────────────────

# Google Sheets stores dates as days since 1899-12-30 (matches Excel). With
# valueRenderOption=UNFORMATTED_VALUE + dateTimeRenderOption=SERIAL_NUMBER we
# get this number back regardless of the spreadsheet's locale, instead of a
# locale-specific string like "04.05.2026" that breaks naive prefix parsing.
_SHEETS_DATE_EPOCH = datetime.date(1899, 12, 30)


def _parse_sheets_date(value: Any) -> datetime.date | None:
    """Convert a Sheets cell value to datetime.date.

    Accepts a serial-number int/float (the unformatted form), an ISO string
    "YYYY-MM-DD" (raw-input legacy rows), or a uk_UA locale string
    "DD.MM.YYYY". Returns None when nothing parses.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return _SHEETS_DATE_EPOCH + datetime.timedelta(days=int(value))
        except (OverflowError, ValueError):
            return None
    if isinstance(value, str) and value:
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


_SHEET_DASHBOARD = "Dashboard"
_SHEET_TRANSACTIONS = "Transactions"
_SHEET_MONTHLY = "Monthly"
_SHEET_CATEGORIES = "Categories"

# Bumped whenever the Transactions sheet layout / dashboard formulas change.
# v1: 7 cols (Date..Description). v2: 9 cols with Base Amount + Base Currency.
SPREADSHEET_SCHEMA_VERSION = 2

_TRANSACTIONS_HEADER = [
    "Date", "Time", "Type", "Amount", "Currency", "Category", "Description",
    "Base Amount", "Base Currency",
]
_TRANSACTIONS_COL_COUNT = len(_TRANSACTIONS_HEADER)


def _spreadsheet_url(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


def _build_spreadsheet_create_body(user: User) -> dict[str, Any]:
    """Define a fresh spreadsheet with Dashboard + Transactions + Monthly + Categories."""
    user_tz = getattr(user, "timezone", None) or "Europe/Kyiv"

    def _sheet(
        title: str,
        *,
        index: int,
        rows: int,
        cols: int,
        color: tuple[float, float, float],
    ) -> dict[str, Any]:
        r, g, b = color
        return {
            "properties": {
                "title": title,
                "index": index,
                "gridProperties": {
                    "rowCount": rows,
                    "columnCount": cols,
                    "frozenRowCount": 1,
                },
                "tabColor": {"red": r, "green": g, "blue": b},
            }
        }

    # Friendly title — owner sees this in Drive. Falls back to a neutral label
    # if neither full_name nor email is available (e.g. user came in via a
    # messaging channel without web OAuth yet).
    owner_label = (user.full_name or user.email or "мій бюджет").strip()
    title = f"Wallet Ledger — {owner_label}"

    return {
        "properties": {
            "title": title,
            "locale": "uk_UA",
            "timeZone": user_tz,
        },
        "sheets": [
            _sheet(_SHEET_DASHBOARD, index=0, rows=60, cols=12, color=(0.26, 0.52, 0.96)),
            _sheet(
                _SHEET_TRANSACTIONS,
                index=1,
                rows=1000,
                cols=_TRANSACTIONS_COL_COUNT,
                color=(0.18, 0.80, 0.44),
            ),
            _sheet(_SHEET_MONTHLY, index=2, rows=20, cols=5, color=(0.96, 0.65, 0.14)),
            _sheet(_SHEET_CATEGORIES, index=3, rows=50, cols=5, color=(0.91, 0.26, 0.21)),
        ],
    }


def _dashboard_values() -> list[list[str]]:
    """Return rows for the Dashboard sheet (current + previous month + all-time).

    All sums read column H (Base Amount) so the dashboard is always in the
    user's base currency, regardless of the original transaction currency.
    Formulas use ';' as argument separator to match the spreadsheet's uk_UA locale.
    """
    cm_start = "DATE(YEAR(TODAY());MONTH(TODAY());1)"
    cm_end = "EOMONTH(TODAY();0)"
    pm_start = "DATE(YEAR(EOMONTH(TODAY();-1));MONTH(EOMONTH(TODAY();-1));1)"
    pm_end = "EOMONTH(TODAY();-1)"

    def _sumifs(start: str, end: str, ttype: str) -> str:
        return (
            f'=SUMIFS(Transactions!H:H;Transactions!C:C;"{ttype}";'
            f'Transactions!A:A;">="&{start};Transactions!A:A;"<="&{end})'
        )

    def _countifs(start: str, end: str) -> str:
        return (
            f'=COUNTIFS(Transactions!A:A;">="&{start};'
            f'Transactions!A:A;"<="&{end})'
        )

    return [
        ["💰 Wallet Dashboard"],                                        # 1
        [""],                                                           # 2
        ["📊 Поточний місяць"],                                          # 3
        ["Метрика", "Сума (base)"],                                     # 4
        ["Витрати", _sumifs(cm_start, cm_end, "Expense")],              # 5
        ["Доходи", _sumifs(cm_start, cm_end, "Income")],                # 6
        ["Баланс", "=B6-B5"],                                           # 7
        ["Кількість транзакцій", _countifs(cm_start, cm_end)],          # 8
        [""],                                                           # 9
        ["📅 Минулий місяць"],                                           # 10
        ["Метрика", "Сума (base)"],                                     # 11
        ["Витрати", _sumifs(pm_start, pm_end, "Expense")],              # 12
        ["Доходи", _sumifs(pm_start, pm_end, "Income")],                # 13
        ["Баланс", "=B13-B12"],                                         # 14
        ["Кількість транзакцій", _countifs(pm_start, pm_end)],          # 15
        [""],                                                           # 16
        ["📈 За весь час"],                                              # 17
        ["Метрика", "Сума (base)"],                                     # 18
        ["Витрати всього", '=SUMIF(Transactions!C:C;"Expense";Transactions!H:H)'],
        ["Доходи всього", '=SUMIF(Transactions!C:C;"Income";Transactions!H:H)'],
        ["Баланс всього", "=B20-B19"],                                  # 21
        ["Транзакцій всього", "=MAX(0;COUNTA(Transactions!A:A)-1)"],    # 22
    ]


def _monthly_values(months: int = 12) -> list[list[str]]:
    """Rows for the Monthly sheet, ordered oldest→newest so charts read left-to-right.

    Sums read column H (Base Amount) so totals are in the user's base currency.
    """
    rows: list[list[str]] = [["Місяць", "Витрати", "Доходи", "Баланс", "Кількість"]]
    # offset goes from (months-1) months ago down to 0 (current month)
    for sheet_row, offset in enumerate(range(months - 1, -1, -1), start=2):
        month_label = f'=TEXT(EOMONTH(TODAY();{-offset});"YYYY-MM")'
        start = f"(EOMONTH(TODAY();{-offset - 1})+1)"
        end = f"EOMONTH(TODAY();{-offset})"
        expense = (
            f'=SUMIFS(Transactions!H:H;Transactions!C:C;"Expense";'
            f'Transactions!A:A;">="&{start};Transactions!A:A;"<="&{end})'
        )
        income = (
            f'=SUMIFS(Transactions!H:H;Transactions!C:C;"Income";'
            f'Transactions!A:A;">="&{start};Transactions!A:A;"<="&{end})'
        )
        balance = f"=C{sheet_row}-B{sheet_row}"
        count = (
            f'=COUNTIFS(Transactions!A:A;">="&{start};'
            f'Transactions!A:A;"<="&{end})'
        )
        rows.append([month_label, expense, income, balance, count])
    return rows


def _categories_values() -> list[list[str]]:
    """Return rows for the Categories sheet (all-time totals per category).

    Sums read column H (Base Amount) so per-category totals are in the user's
    base currency.
    """
    rows: list[list[str]] = [["Категорія", "Тип", "Сума", "Кількість", "Середня"]]
    sheet_row = 2
    for tx_type in ("Expense", "Income"):
        for cat in sorted(ALLOWED_CATEGORIES[tx_type]):
            sum_f = (
                f'=SUMIFS(Transactions!H:H;'
                f'Transactions!C:C;"{tx_type}";'
                f'Transactions!F:F;"{cat}")'
            )
            count_f = (
                f'=COUNTIFS(Transactions!C:C;"{tx_type}";'
                f'Transactions!F:F;"{cat}")'
            )
            avg_f = f"=IFERROR(C{sheet_row}/D{sheet_row};0)"
            rows.append([cat, tx_type, sum_f, count_f, avg_f])
            sheet_row += 1
    return rows


def _format_requests(sheet_ids: dict[str, int]) -> list[dict[str, Any]]:
    """Build batchUpdate requests for cosmetic formatting across all sheets."""
    primary = {"red": 0.26, "green": 0.52, "blue": 0.96}
    header_bg = {"red": 0.85, "green": 0.92, "blue": 0.97}
    white = {"red": 1.0, "green": 1.0, "blue": 1.0}
    currency_fmt = {"type": "NUMBER", "pattern": "#,##0.00"}

    dashboard_id = sheet_ids[_SHEET_DASHBOARD]
    transactions_id = sheet_ids[_SHEET_TRANSACTIONS]
    monthly_id = sheet_ids[_SHEET_MONTHLY]
    categories_id = sheet_ids[_SHEET_CATEGORIES]

    def _range(sheet_id: int, r0: int, r1: int, c0: int, c1: int) -> dict[str, Any]:
        return {
            "sheetId": sheet_id,
            "startRowIndex": r0,
            "endRowIndex": r1,
            "startColumnIndex": c0,
            "endColumnIndex": c1,
        }

    def _repeat(rng: dict[str, Any], fmt: dict[str, Any], fields: str) -> dict[str, Any]:
        return {
            "repeatCell": {
                "range": rng,
                "cell": {"userEnteredFormat": fmt},
                "fields": f"userEnteredFormat({fields})",
            }
        }

    def _table_header(sheet_id: int, cols: int) -> dict[str, Any]:
        return _repeat(
            _range(sheet_id, 0, 1, 0, cols),
            {
                "backgroundColor": primary,
                "horizontalAlignment": "CENTER",
                "textFormat": {"foregroundColor": white, "bold": True},
            },
            "backgroundColor,horizontalAlignment,textFormat",
        )

    def _currency_col(sheet_id: int, col: int) -> dict[str, Any]:
        return _repeat(
            _range(sheet_id, 1, 1000, col, col + 1),
            {"numberFormat": currency_fmt},
            "numberFormat",
        )

    def _autosize(sheet_id: int, cols: int) -> dict[str, Any]:
        return {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": cols,
                }
            }
        }

    def _set_column_widths(sheet_id: int, widths_px: list[int]) -> list[dict[str, Any]]:
        """Set explicit pixel widths column-by-column. One request per column."""
        return [
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": idx,
                        "endIndex": idx + 1,
                    },
                    "properties": {"pixelSize": px},
                    "fields": "pixelSize",
                }
            }
            for idx, px in enumerate(widths_px)
        ]

    requests: list[dict[str, Any]] = []

    # === Dashboard: title + section headers + metric formatting ===
    requests.append({
        "mergeCells": {
            "range": _range(dashboard_id, 0, 1, 0, 6),
            "mergeType": "MERGE_ALL",
        }
    })
    requests.append(_repeat(
        _range(dashboard_id, 0, 1, 0, 6),
        {
            "backgroundColor": primary,
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
            "textFormat": {"foregroundColor": white, "bold": True, "fontSize": 18},
        },
        "backgroundColor,horizontalAlignment,verticalAlignment,textFormat",
    ))
    requests.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId": dashboard_id,
                "dimension": "ROWS",
                "startIndex": 0,
                "endIndex": 1,
            },
            "properties": {"pixelSize": 50},
            "fields": "pixelSize",
        }
    })
    # Subtitle bands (Поточний місяць / Минулий місяць / За весь час) —
    # 0-indexed rows where the subtitle title sits.
    subtitle_rows = (2, 9, 16)
    for r in subtitle_rows:
        requests.append({
            "mergeCells": {
                "range": _range(dashboard_id, r, r + 1, 0, 6),
                "mergeType": "MERGE_ALL",
            }
        })
        requests.append(_repeat(
            _range(dashboard_id, r, r + 1, 0, 6),
            {
                "backgroundColor": header_bg,
                "textFormat": {"bold": True, "fontSize": 12},
            },
            "backgroundColor,textFormat",
        ))
    # 0-indexed rows of "Метрика | Сума (base)" headers.
    metric_header_rows = (3, 10, 17)
    for hdr_row in metric_header_rows:
        requests.append(_repeat(
            _range(dashboard_id, hdr_row, hdr_row + 1, 0, 2),
            {"backgroundColor": header_bg, "textFormat": {"bold": True}},
            "backgroundColor,textFormat",
        ))
    # 0-indexed half-open ranges per metric block (inclusive start, exclusive end).
    metric_blocks = ((4, 8), (11, 15), (18, 22))
    for r0, r1 in metric_blocks:
        requests.append(_repeat(
            _range(dashboard_id, r0, r1, 0, 1),
            {"textFormat": {"bold": True}},
            "textFormat",
        ))
        requests.append(_repeat(
            _range(dashboard_id, r0, r1, 1, 2),
            {"numberFormat": currency_fmt},
            "numberFormat",
        ))
    requests.append(_autosize(dashboard_id, 6))

    # === Transactions: header, date column, amount columns (D + H) ===
    requests.append(_table_header(transactions_id, _TRANSACTIONS_COL_COUNT))
    requests.append(_repeat(
        _range(transactions_id, 1, 1000, 0, 1),
        {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}},
        "numberFormat",
    ))
    requests.append(_currency_col(transactions_id, 3))  # D: Amount
    requests.append(_currency_col(transactions_id, 7))  # H: Base Amount
    # Date | Time | Type | Amount | Currency | Category | Description | Base Amount | Base Currency
    requests.extend(_set_column_widths(
        transactions_id, [110, 90, 110, 130, 100, 170, 280, 130, 110]
    ))

    # === Monthly: header + currency on cols B/C/D ===
    requests.append(_table_header(monthly_id, 5))
    for col in (1, 2, 3):
        requests.append(_currency_col(monthly_id, col))
    # Місяць | Витрати | Доходи | Баланс | Кількість
    requests.extend(_set_column_widths(
        monthly_id, [120, 140, 140, 140, 130]
    ))

    # === Categories: header + currency on cols C/E ===
    requests.append(_table_header(categories_id, 5))
    requests.append(_currency_col(categories_id, 2))
    requests.append(_currency_col(categories_id, 4))
    # Категорія | Тип | Сума | Кількість | Середня
    requests.extend(_set_column_widths(
        categories_id, [200, 110, 140, 130, 140]
    ))

    return requests


def _chart_requests(sheet_ids: dict[str, int]) -> list[dict[str, Any]]:
    """Embed three charts on the Dashboard sheet sourced from Categories + Monthly."""
    dashboard_id = sheet_ids[_SHEET_DASHBOARD]
    monthly_id = sheet_ids[_SHEET_MONTHLY]
    categories_id = sheet_ids[_SHEET_CATEGORIES]

    expense_count = len(ALLOWED_CATEGORIES["Expense"])
    monthly_data_rows = 12

    # Categories layout: row 0 header, then expense rows, then income rows.
    expense_start = 1
    expense_end = expense_start + expense_count

    # Monthly layout: row 0 header, then `monthly_data_rows` of data.
    monthly_end = 1 + monthly_data_rows

    def _src(sheet_id: int, r0: int, r1: int, c0: int, c1: int) -> dict[str, Any]:
        return {
            "sourceRange": {
                "sources": [{
                    "sheetId": sheet_id,
                    "startRowIndex": r0,
                    "endRowIndex": r1,
                    "startColumnIndex": c0,
                    "endColumnIndex": c1,
                }]
            }
        }

    def _overlay(row_idx: int, col_idx: int, w: int, h: int) -> dict[str, Any]:
        return {
            "overlayPosition": {
                "anchorCell": {
                    "sheetId": dashboard_id,
                    "rowIndex": row_idx,
                    "columnIndex": col_idx,
                },
                "widthPixels": w,
                "heightPixels": h,
            }
        }

    pie_expense = {
        "addChart": {
            "chart": {
                "spec": {
                    "title": "Витрати по категоріях (за весь час)",
                    "pieChart": {
                        "legendPosition": "RIGHT_LEGEND",
                        "threeDimensional": False,
                        "domain": _src(categories_id, expense_start, expense_end, 0, 1),
                        "series": _src(categories_id, expense_start, expense_end, 2, 3),
                    },
                },
                "position": _overlay(row_idx=23, col_idx=0, w=480, h=340),
            }
        }
    }

    column_monthly = {
        "addChart": {
            "chart": {
                "spec": {
                    "title": "Витрати vs Доходи по місяцях",
                    "basicChart": {
                        "chartType": "COLUMN",
                        "legendPosition": "BOTTOM_LEGEND",
                        "headerCount": 1,
                        "axis": [
                            {"position": "BOTTOM_AXIS", "title": "Місяць"},
                            {"position": "LEFT_AXIS", "title": "UAH"},
                        ],
                        "domains": [{
                            "domain": _src(monthly_id, 0, monthly_end, 0, 1),
                        }],
                        "series": [
                            {
                                "series": _src(monthly_id, 0, monthly_end, 1, 2),
                                "targetAxis": "LEFT_AXIS",
                                "color": {"red": 0.91, "green": 0.30, "blue": 0.24},
                            },
                            {
                                "series": _src(monthly_id, 0, monthly_end, 2, 3),
                                "targetAxis": "LEFT_AXIS",
                                "color": {"red": 0.18, "green": 0.66, "blue": 0.36},
                            },
                        ],
                    },
                },
                "position": _overlay(row_idx=23, col_idx=6, w=640, h=340),
            }
        }
    }

    line_balance = {
        "addChart": {
            "chart": {
                "spec": {
                    "title": "Тренд балансу по місяцях",
                    "basicChart": {
                        "chartType": "LINE",
                        "legendPosition": "NO_LEGEND",
                        "headerCount": 1,
                        "axis": [
                            {"position": "BOTTOM_AXIS", "title": "Місяць"},
                            {"position": "LEFT_AXIS", "title": "Баланс, UAH"},
                        ],
                        "domains": [{
                            "domain": _src(monthly_id, 0, monthly_end, 0, 1),
                        }],
                        "series": [
                            {
                                "series": _src(monthly_id, 0, monthly_end, 3, 4),
                                "targetAxis": "LEFT_AXIS",
                                "color": {"red": 0.26, "green": 0.52, "blue": 0.96},
                                "lineStyle": {"width": 2, "type": "SOLID"},
                            }
                        ],
                    },
                },
                "position": _overlay(row_idx=42, col_idx=0, w=1140, h=320),
            }
        }
    }

    return [pie_expense, column_monthly, line_balance]


def _create_user_spreadsheet(sheets_service: Any, user: User) -> str:
    """Create a fresh spreadsheet, populate values + formulas, apply formatting."""
    create_body = _build_spreadsheet_create_body(user)
    logger.info("Creating new spreadsheet for user id=%s", user.id)
    created = execute_with_retry(
        sheets_service.spreadsheets().create(
            body=create_body,
            fields="spreadsheetId,sheets.properties",
        ),
        label="spreadsheets.create",
    )

    spreadsheet_id = created.get("spreadsheetId")
    if not spreadsheet_id:
        raise RuntimeError("spreadsheets.create returned no spreadsheetId")

    sheet_ids = {
        s["properties"]["title"]: s["properties"]["sheetId"]
        for s in created.get("sheets", [])
    }
    logger.info(
        "Created spreadsheet id=%s for user id=%s with sheets=%s",
        spreadsheet_id,
        user.id,
        list(sheet_ids.keys()),
    )

    monthly_rows = _monthly_values(12)
    categories_rows = _categories_values()
    values_body = {
        "valueInputOption": "USER_ENTERED",
        "data": [
            {
                "range": f"{_SHEET_DASHBOARD}!A1:B22",
                "values": _dashboard_values(),
            },
            {
                "range": f"{_SHEET_TRANSACTIONS}!A1:I1",
                "values": [_TRANSACTIONS_HEADER],
            },
            {
                "range": f"{_SHEET_MONTHLY}!A1:E{len(monthly_rows)}",
                "values": monthly_rows,
            },
            {
                "range": f"{_SHEET_CATEGORIES}!A1:E{len(categories_rows)}",
                "values": categories_rows,
            },
        ],
    }
    execute_with_retry(
        sheets_service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=values_body,
        ),
        label="spreadsheets.values.batchUpdate",
    )
    logger.info("Wrote initial values to spreadsheet id=%s", spreadsheet_id)

    all_requests = _format_requests(sheet_ids) + _chart_requests(sheet_ids)
    execute_with_retry(
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": all_requests},
        ),
        label="spreadsheets.batchUpdate(format+charts)",
    )
    logger.info(
        "Applied formatting + %s chart(s) to spreadsheet id=%s",
        len(_chart_requests(sheet_ids)),
        spreadsheet_id,
    )

    return spreadsheet_id


def _ensure_user_spreadsheet(
    db: Session,
    *,
    user: User,
    creds: Credentials,
) -> str:
    """Return the user's spreadsheet, creating one if it doesn't exist yet."""
    if user.google_spreadsheet_id:
        logger.info(
            "Reusing existing spreadsheet for user id=%s: spreadsheet_id=%s schema_v=%s",
            user.id,
            user.google_spreadsheet_id,
            getattr(user, "spreadsheet_schema_version", 1),
        )
        return user.google_spreadsheet_id

    sheets_service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    spreadsheet_id = _create_user_spreadsheet(sheets_service, user)

    user.google_spreadsheet_id = spreadsheet_id
    user.spreadsheet_schema_version = SPREADSHEET_SCHEMA_VERSION
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(
        "Saved spreadsheet_id=%s schema_v=%s for user id=%s",
        spreadsheet_id,
        SPREADSHEET_SCHEMA_VERSION,
        user.id,
    )
    return spreadsheet_id


def _append_transaction_row(
    sheets_service: Any,
    spreadsheet_id: str,
    row: list[Any],
    *,
    schema_version: int = SPREADSHEET_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Append a single transaction row to the user's Transactions sheet.

    Range adapts to schema_version so legacy v1 spreadsheets (7 columns) keep
    working without ever touching columns H/I.
    """
    range_a1 = "Transactions!A:I" if schema_version >= 2 else "Transactions!A:G"
    return execute_with_retry(
        sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_a1,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ),
        label="spreadsheets.values.append",
    )


async def reset_user_spreadsheet(
    db: Session,
    *,
    user_id: int,
) -> dict[str, Any]:
    """Drop the user's existing spreadsheet_id and provision a fresh one.

    The previous spreadsheet remains in the user's Drive — we never delete user
    data; they can remove it manually if they don't need it.
    """
    user = _resolve_user(db, user_id=user_id)
    if not user:
        return {"status": "error", "error": "User not found."}

    creds = _get_google_credentials(db, user_id=user.id)
    if not creds:
        return {
            "status": "error",
            "error": "Google account is not connected. Please authorize Google access first.",
        }

    old_id = user.google_spreadsheet_id
    logger.info(
        "reset_user_spreadsheet: user id=%s discarding old spreadsheet_id=%s",
        user.id,
        old_id,
    )
    user.google_spreadsheet_id = None
    db.add(user)
    db.commit()

    try:
        sheets_service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        new_id = _create_user_spreadsheet(sheets_service, user)
    except Exception as exc:
        logger.exception(
            "reset_user_spreadsheet: failed to create new spreadsheet for user id=%s: %s",
            user.id,
            exc,
        )
        # Restore the old id so we don't leave the user without anything to write to.
        user.google_spreadsheet_id = old_id
        db.add(user)
        db.commit()
        return {"status": "error", "error": str(exc)}

    user.google_spreadsheet_id = new_id
    user.spreadsheet_schema_version = SPREADSHEET_SCHEMA_VERSION
    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "status": "ok",
        "old_spreadsheet_id": old_id,
        "spreadsheet_id": new_id,
        "spreadsheet_url": _spreadsheet_url(new_id),
        "schema_version": SPREADSHEET_SCHEMA_VERSION,
    }


async def record_transaction(
    db: Session,
    transaction_type: str,
    amount: float,
    currency: str = "UAH",
    category: str = "Other",
    description: str = "",
    user_id: int | None = None,
    telegram_id: int | None = None,
) -> dict[str, Any]:
    """Record an Expense/Income transaction to the user's Google Sheet."""
    logger.info(
        "record_transaction called | user_id=%s telegram_id=%s type=%s amount=%s "
        "currency=%s category=%s description=%r",
        user_id,
        telegram_id,
        transaction_type,
        amount,
        currency,
        category,
        description,
    )

    if getattr(settings, "finance_stub_mode", False):
        logger.warning(
            "FINANCE_STUB_MODE is enabled — skipping real Google Sheets write. "
            "Set FINANCE_STUB_MODE=false in .env to write to the spreadsheet."
        )
        return {"status": "ok", "stub": True}

    user = _resolve_user(db, user_id=user_id, telegram_id=telegram_id)
    if not user:
        logger.error(
            "record_transaction: user not found (user_id=%s, telegram_id=%s)",
            user_id,
            telegram_id,
        )
        return {
            "status": "error",
            "error": "User not found. Please start the bot first.",
        }

    normalized_type = _normalize_transaction_type(transaction_type)
    if not normalized_type:
        return {
            "status": "error",
            "error": "transaction_type must be either 'Expense' or 'Income'.",
        }

    if amount <= 0:
        return {
            "status": "error",
            "error": "amount must be a positive number.",
        }

    allowed = ALLOWED_CATEGORIES[normalized_type]
    if category not in allowed:
        allowed_str = ", ".join(sorted(allowed))
        return {
            "status": "error",
            "error": (
                f"Invalid category '{category}' for {normalized_type}. "
                f"Allowed categories: {allowed_str}."
            ),
        }

    creds = _get_google_credentials(
        db,
        user_id=user.id,
    )
    if not creds:
        return {
            "status": "error",
            "error": (
                "Google account is not connected. Please authorize Google access first."
            ),
        }

    try:
        spreadsheet_id = _ensure_user_spreadsheet(db, user=user, creds=creds)
    except Exception as exc:
        logger.exception(
            "Failed to ensure spreadsheet for user id=%s: %s",
            user.id,
            exc,
        )
        db.rollback()
        return {"status": "error", "error": str(exc)}

    now_utc = datetime.datetime.now(datetime.UTC)
    normalized_currency = (currency or "UAH").upper()
    base_currency = (getattr(user, "base_currency", None) or "UAH").upper()
    schema_version = int(getattr(user, "spreadsheet_schema_version", 1) or 1)

    base_amount: float | None = None
    fx_warning: str | None = None
    if schema_version >= 2:
        # Compute the user's base-currency equivalent up front so the row written
        # to Sheets contains a frozen number (column H), not a live formula.
        # That keeps historical totals stable even when rates shift later.
        from app.integrations.fx import FxError, convert as fx_convert

        try:
            base_amount = await fx_convert(
                db,
                amount=float(amount),
                from_currency=normalized_currency,
                to_currency=base_currency,
                on_date=now_utc.date(),
            )
            base_amount = round(base_amount, 2)
        except FxError as exc:
            # Don't block the write — record the original currency only and let
            # the user know base-currency aggregates may be off until rates
            # come back. Better than dropping the transaction entirely.
            fx_warning = (
                f"Не вдалося отримати курс {normalized_currency}→{base_currency}: "
                f"{exc}. Транзакція збережена, але без перерахунку у базову валюту."
            )
            logger.warning(
                "FX conversion failed | user_id=%s %s→%s amount=%s: %s",
                user.id,
                normalized_currency,
                base_currency,
                amount,
                exc,
            )

    row: list[Any] = [
        now_utc.date().isoformat(),
        now_utc.strftime("%H:%M:%S"),
        normalized_type,
        float(amount),
        normalized_currency,
        category,
        description,
    ]
    if schema_version >= 2:
        row.extend([
            base_amount if base_amount is not None else "",
            base_currency,
        ])

    logger.info(
        "Appending row to spreadsheet_id=%s (user id=%s schema_v=%s): %s",
        spreadsheet_id,
        user.id,
        schema_version,
        row,
    )
    sheets_service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    try:
        append_result = _append_transaction_row(
            sheets_service, spreadsheet_id, row, schema_version=schema_version
        )
    except Exception as exc:
        if not is_spreadsheet_missing(exc):
            logger.exception(
                "Sheets append failed for user id=%s spreadsheet_id=%s: %s",
                user.id,
                spreadsheet_id,
                exc,
            )
            return {"status": "error", "error": str(exc)}

        # Spreadsheet was deleted in Drive (or sheet/range gone) — recreate and retry once.
        logger.warning(
            "Append got 404 for user id=%s spreadsheet_id=%s — spreadsheet missing, "
            "recreating and retrying once",
            user.id,
            spreadsheet_id,
        )
        user.google_spreadsheet_id = None
        db.add(user)
        db.commit()
        db.refresh(user)
        try:
            spreadsheet_id = _ensure_user_spreadsheet(db, user=user, creds=creds)
            # Schema may have been bumped during recreate — re-read it before append.
            schema_version = int(getattr(user, "spreadsheet_schema_version", 1) or 1)
            append_result = _append_transaction_row(
                sheets_service, spreadsheet_id, row, schema_version=schema_version
            )
        except Exception as recreate_exc:
            logger.exception(
                "Sheets recreate+append failed for user id=%s: %s",
                user.id,
                recreate_exc,
            )
            return {"status": "error", "error": str(recreate_exc)}
        logger.info(
            "Recreated spreadsheet and re-appended row for user id=%s (new id=%s)",
            user.id,
            spreadsheet_id,
        )

    updated_range = append_result.get("updates", {}).get("updatedRange")
    spreadsheet_url = _spreadsheet_url(spreadsheet_id)
    logger.info(
        "Sheets append OK for user id=%s spreadsheet_id=%s updated_range=%s",
        user.id,
        spreadsheet_id,
        updated_range,
    )
    response: dict[str, Any] = {
        "status": "ok",
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_url": spreadsheet_url,
        "transaction_type": normalized_type,
        "amount": float(amount),
        "currency": normalized_currency,
        "category": category,
        "description": description,
        "updated_range": updated_range,
    }
    if base_amount is not None:
        response["base_amount"] = base_amount
        response["base_currency"] = base_currency
    if fx_warning:
        response["fx_warning"] = fx_warning
    return response


async def list_recent_transactions(
    db: Session,
    *,
    user_id: int,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Read the last ``limit`` rows from the user's Transactions sheet.

    Reads up to 9 columns (A:I). Legacy v1 spreadsheets only have A:G — the
    extra columns are returned as None/empty so callers can still rely on the
    new fields without crashing on old data.

    Returns an empty list if the user has not yet connected Google or no
    spreadsheet has been created (i.e. they have no recorded transactions).
    """
    user = _resolve_user(db, user_id=user_id)
    if not user or not user.google_spreadsheet_id:
        return []

    creds = _get_google_credentials(db, user_id=user_id)
    if not creds:
        return []

    try:
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        result = execute_with_retry(
            service.spreadsheets().values().get(
                spreadsheetId=user.google_spreadsheet_id,
                range="Transactions!A2:I",
                # uk_UA locale uses ',' as decimal — without UNFORMATTED_VALUE
                # the API returns "350,00" which float() rejects, dropping every row.
                # SERIAL_NUMBER for dates dodges the locale "DD.MM.YYYY" issue;
                # we parse the raw serial via _parse_sheets_date below.
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="SERIAL_NUMBER",
            ),
            label="spreadsheets.values.get",
        )
    except Exception as exc:
        logger.exception(
            "list_recent_transactions failed for user_id=%s: %s",
            user_id,
            exc,
        )
        return []

    rows = result.get("values", []) or []
    rows = rows[-limit:] if limit else rows
    transactions: list[dict[str, Any]] = []
    for row in reversed(rows):
        padded = row + [""] * (_TRANSACTIONS_COL_COUNT - len(row))
        try:
            amount = float(padded[3]) if padded[3] != "" else None
        except (TypeError, ValueError):
            amount = None
        try:
            base_amount = float(padded[7]) if padded[7] != "" else None
        except (TypeError, ValueError):
            base_amount = None
        # Sheets returned a serial number for the date — convert back to ISO
        # so the frontend can render it without knowing about Sheets internals.
        date = _parse_sheets_date(padded[0])
        date_iso = date.isoformat() if date else (str(padded[0]) if padded[0] != "" else "")
        transactions.append(
            {
                "date": date_iso,
                "time": str(padded[1]) if padded[1] != "" else "",
                "type": padded[2],
                "amount": amount,
                "currency": padded[4],
                "category": padded[5],
                "description": padded[6],
                "base_amount": base_amount,
                "base_currency": padded[8] or None,
            }
        )
    return transactions


async def recalculate_base_amounts(
    db: Session,
    *,
    user_id: int,
) -> dict[str, Any]:
    """Rewrite columns H (Base Amount) + I (Base Currency) in-place.

    Used when the user changes their base_currency: instead of leaving the
    historical ledger expressed in the old base, we re-convert every row using
    the rate of *its own* date (not today's). This preserves the same
    fixed-at-write-time semantics record_transaction uses for new rows.

    Returns counts: ``{"updated": N, "skipped": N, "fx_failures": N}``.
    No-op for v1 spreadsheets — they don't have columns H/I.
    """
    user = _resolve_user(db, user_id=user_id)
    if not user or not user.google_spreadsheet_id:
        return {"status": "ok", "updated": 0, "skipped": 0, "fx_failures": 0}

    schema_version = int(getattr(user, "spreadsheet_schema_version", 1) or 1)
    if schema_version < 2:
        return {
            "status": "skipped",
            "reason": "spreadsheet_v1_has_no_base_columns",
            "updated": 0,
            "skipped": 0,
            "fx_failures": 0,
        }

    creds = _get_google_credentials(db, user_id=user_id)
    if not creds:
        return {"status": "error", "error": "Google account not connected"}

    base_currency = (getattr(user, "base_currency", None) or "UAH").upper()

    try:
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        result = execute_with_retry(
            service.spreadsheets().values().get(
                spreadsheetId=user.google_spreadsheet_id,
                range="Transactions!A2:I",
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="SERIAL_NUMBER",
            ),
            label="spreadsheets.values.get",
        )
    except Exception as exc:
        logger.exception(
            "recalculate_base_amounts: read failed | user_id=%s: %s",
            user_id,
            exc,
        )
        return {"status": "error", "error": str(exc)}

    rows = result.get("values", []) or []
    if not rows:
        return {"status": "ok", "updated": 0, "skipped": 0, "fx_failures": 0}

    from app.integrations.fx import FxError, convert as fx_convert

    updates: list[dict[str, Any]] = []
    skipped = 0
    fx_failures = 0

    for idx, row in enumerate(rows):
        padded = row + [""] * (_TRANSACTIONS_COL_COUNT - len(row))
        date_val, _time, ttype, amount_val, currency_val, *_rest = padded[:5]

        date = _parse_sheets_date(date_val)
        if date is None or ttype not in ("Expense", "Income"):
            skipped += 1
            continue

        try:
            amount = float(amount_val)
        except (TypeError, ValueError):
            skipped += 1
            continue

        currency = (str(currency_val) or "UAH").upper().strip() or "UAH"

        try:
            new_base = await fx_convert(
                db,
                amount=amount,
                from_currency=currency,
                to_currency=base_currency,
                on_date=date,
            )
            new_base = round(new_base, 2)
        except FxError as exc:
            logger.warning(
                "recalculate: FX fail | user_id=%s row=%s %s->%s on %s: %s",
                user_id,
                idx + 2,
                currency,
                base_currency,
                date,
                exc,
            )
            fx_failures += 1
            continue

        # Sheet rows are 1-indexed and row 1 is the header → idx + 2.
        sheet_row = idx + 2
        updates.append({
            "range": f"Transactions!H{sheet_row}:I{sheet_row}",
            "values": [[new_base, base_currency]],
        })

    if not updates:
        logger.info(
            "Recalculate: nothing to write | user_id=%s skipped=%s fx_failures=%s",
            user_id,
            skipped,
            fx_failures,
        )
        return {
            "status": "ok",
            "updated": 0,
            "skipped": skipped,
            "fx_failures": fx_failures,
            "base_currency": base_currency,
        }

    try:
        execute_with_retry(
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=user.google_spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": updates},
            ),
            label="spreadsheets.values.batchUpdate(recalculate)",
        )
    except Exception as exc:
        logger.exception(
            "recalculate_base_amounts: batchUpdate failed | user_id=%s: %s",
            user_id,
            exc,
        )
        return {"status": "error", "error": str(exc)}

    logger.info(
        "Recalculate done | user_id=%s base=%s updated=%s skipped=%s fx_failures=%s",
        user_id,
        base_currency,
        len(updates),
        skipped,
        fx_failures,
    )
    return {
        "status": "ok",
        "updated": len(updates),
        "skipped": skipped,
        "fx_failures": fx_failures,
        "base_currency": base_currency,
    }


async def summarize_transactions(
    db: Session,
    *,
    user_id: int,
    months: int = 12,
) -> dict[str, Any]:
    """Read all transactions and aggregate into category + monthly buckets.

    Returns a dict shaped for the frontend Finance dashboard:
      {
        "by_category": [{"category": str, "type": str, "amount": float, "count": int}, ...],
        "by_month":    [{"month": "YYYY-MM", "expense": float, "income": float, "balance": float}, ...],
        "totals":      {"expense": float, "income": float, "balance": float, "count": int},
      }

    Empty lists / zeros when the user has no spreadsheet, no oauth, or no rows.
    """
    base_currency = "UAH"
    user = _resolve_user(db, user_id=user_id)
    empty: dict[str, Any] = {
        "by_category": [],
        "by_month": [],
        "totals": {"expense": 0.0, "income": 0.0, "balance": 0.0, "count": 0},
        "base_currency": base_currency,
    }
    if not user or not user.google_spreadsheet_id:
        return empty
    base_currency = (getattr(user, "base_currency", None) or "UAH").upper()
    empty["base_currency"] = base_currency

    creds = _get_google_credentials(db, user_id=user_id)
    if not creds:
        return empty

    try:
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        result = execute_with_retry(
            service.spreadsheets().values().get(
                spreadsheetId=user.google_spreadsheet_id,
                range="Transactions!A2:I",
                # uk_UA locale uses ',' as decimal — without UNFORMATTED_VALUE
                # the API returns "350,00" which float() rejects, zeroing all charts.
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="FORMATTED_STRING",
            ),
            label="spreadsheets.values.get",
        )
    except Exception as exc:
        logger.exception(
            "summarize_transactions failed for user_id=%s: %s",
            user_id,
            exc,
        )
        return empty

    rows = result.get("values", []) or []

    cat_buckets: dict[tuple[str, str], dict[str, float]] = {}
    month_buckets: dict[str, dict[str, float]] = {}
    totals = {"expense": 0.0, "income": 0.0, "count": 0}

    today = datetime.date.today()
    # Seed last `months` months in chronological order so the chart x-axis is
    # complete even when some months have zero transactions.
    seeded_months: list[str] = []
    year, month = today.year, today.month
    for _ in range(months):
        seeded_months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    seeded_months.reverse()
    for m in seeded_months:
        month_buckets[m] = {"expense": 0.0, "income": 0.0}

    for row in rows:
        padded = row + [""] * (_TRANSACTIONS_COL_COUNT - len(row))
        date_val, _time, ttype, amount_val, _currency, category, _desc, base_amount_val, _base_cur = (
            padded[:_TRANSACTIONS_COL_COUNT]
        )
        # Prefer Base Amount (col H) so totals are always in user's base
        # currency. Legacy v1 rows have it empty — fall back to raw Amount;
        # accuracy degrades gracefully instead of silently dropping the row.
        amount: float
        try:
            if base_amount_val != "":
                amount = float(base_amount_val)
            elif amount_val != "":
                amount = float(amount_val)
            else:
                continue
        except (TypeError, ValueError):
            continue
        if ttype not in ("Expense", "Income"):
            continue
        ttype_key = "expense" if ttype == "Expense" else "income"

        # Category bucket — keyed by (category, type) so an "Other" expense
        # never merges with an "Other" income.
        cat_key = (category or "Uncategorized", ttype)
        bucket = cat_buckets.setdefault(cat_key, {"amount": 0.0, "count": 0.0})
        bucket["amount"] += amount
        bucket["count"] += 1

        # Month bucket — only count rows within the requested window. Date
        # comes back as a serial number from Sheets; _parse_sheets_date is
        # locale-agnostic so this works regardless of spreadsheet locale.
        parsed_date = _parse_sheets_date(date_val)
        if parsed_date is not None:
            month_key = parsed_date.strftime("%Y-%m")
            if month_key in month_buckets:
                month_buckets[month_key][ttype_key] += amount

        totals[ttype_key] += amount
        totals["count"] += 1

    by_category = [
        {
            "category": cat,
            "type": ttype,
            "amount": round(payload["amount"], 2),
            "count": int(payload["count"]),
        }
        for (cat, ttype), payload in sorted(
            cat_buckets.items(),
            key=lambda kv: (-kv[1]["amount"], kv[0][0]),
        )
    ]

    by_month = [
        {
            "month": m,
            "expense": round(b["expense"], 2),
            "income": round(b["income"], 2),
            "balance": round(b["income"] - b["expense"], 2),
        }
        for m, b in month_buckets.items()
    ]

    return {
        "by_category": by_category,
        "by_month": by_month,
        "totals": {
            "expense": round(totals["expense"], 2),
            "income": round(totals["income"], 2),
            "balance": round(totals["income"] - totals["expense"], 2),
            "count": int(totals["count"]),
        },
        "base_currency": base_currency,
    }


async def add_expense(
    db: Session,
    amount: float,
    currency: str = "UAH",
    category: str = "Other",
    description: str = "",
    user_id: int | None = None,
    telegram_id: int | None = None,
) -> dict[str, Any]:
    """Backward-compatible wrapper for legacy callers."""
    return await record_transaction(
        db=db,
        transaction_type="Expense",
        amount=amount,
        currency=currency,
        category=category,
        description=description,
        user_id=user_id,
        telegram_id=telegram_id,
    )
