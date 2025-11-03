# streamlit_app.py
# -*- coding: utf-8 -*-
import csv
import re
from io import BytesIO
from pathlib import Path
from datetime import datetime
import pytz
import streamlit as st
import pandas as pd

# --- Google Sheets
import gspread
from google.oauth2.service_account import Credentials
from gspread_formatting import (
    CellFormat, Color, TextFormat,
    ConditionalFormatRule, BooleanRule, BooleanCondition,
    GridRange, format_cell_range, get_conditional_format_rules
)
# =========================
# הגדרות כלליות
# =========================
st.set_page_config(page_title="שאלון לסטודנטים – תשפ״ו", layout="centered")
st.markdown("""
<style>
:root{
  --ink:#0f172a; 
  --muted:#475569; 
  --ring:rgba(99,102,241,.25); 
  --card:rgba(255,255,255,.85);
}
html, body, [class*="css"] { font-family: system-ui, "Segoe UI", Arial; }
.stApp, .main, [data-testid="stSidebar"]{ direction:rtl; text-align:right; }
[data-testid="stAppViewContainer"]{
  background:
    radial-gradient(1200px 600px at 8% 8%, #e0f7fa 0%, transparent 65%),
    radial-gradient(1000px 500px at 92% 12%, #ede7f6 0%, transparent 60%),
    radial-gradient(900px 500px at 20% 90%, #fff3e0 0%, transparent 55%);
}
.block-container{ padding-top:1.1rem; }
[data-testid="stForm"]{
  background:var(--card);
  border:1px solid #e2e8f0;
  border-radius:16px;
  padding:18px 20px;
  box-shadow:0 8px 24px rgba(2,6,23,.06);
}
[data-testid="stWidgetLabel"] p{ text-align:right; margin-bottom:.25rem; color:var(--muted); }
[data-testid="stWidgetLabel"] p::after{ content: " :"; }
input, textarea, select{ direction:rtl; text-align:right; }
</style>
""", unsafe_allow_html=True)
st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Assistant:wght@300;400;600;700&family=Noto+Sans+Hebrew:wght@400;600&display=swap" rel="stylesheet">

<style>
:root { --app-font: 'Assistant', 'Noto Sans Hebrew', 'Segoe UI', -apple-system, sans-serif; }

/* בסיס האפליקציה */
html, body, .stApp, [data-testid="stAppViewContainer"], .main {
  font-family: var(--app-font) !important;
}

/* ודא שכל הצאצאים יורשים את הפונט */
.stApp * {
  font-family: var(--app-font) !important;
}

/* רכיבי קלט/בחירה של Streamlit */
div[data-baseweb], /* select/radio/checkbox */
.stTextInput input,
.stTextArea textarea,
.stSelectbox div,
.stMultiSelect div,
.stRadio,
.stCheckbox,
.stButton > button {
  font-family: var(--app-font) !important;
}

/* טבלאות DataFrame/Arrow */
div[data-testid="stDataFrame"] div {
  font-family: var(--app-font) !important;
}

/* כותרות */
h1, h2, h3, h4, h5, h6 {
  font-family: var(--app-font) !important;
}
</style>
""", unsafe_allow_html=True)
# =========================
# נתיבים/סודות + התמדה ארוכת טווח
# =========================
DATA_DIR   = Path("data")
BACKUP_DIR = DATA_DIR / "backups"
DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

CSV_FILE      = DATA_DIR / "שאלון_שיבוץ.csv"
CSV_LOG_FILE  = DATA_DIR / "שאלון_שיבוץ_log.csv"
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "rawan_0304")

query_params = st.query_params
is_admin_mode = query_params.get("admin", ["0"])[0] == "1"

# =========================
# Google Sheets הגדרות
# =========================
SHEET_ID = st.secrets["sheets"]["spreadsheet_id"]

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

try:
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    gclient = gspread.authorize(creds)
    sheet = gclient.open_by_key(SHEET_ID).sheet1
except Exception as e:
    sheet = None
    st.error(f"⚠ לא ניתן להתחבר ל־Google Sheets: {e}")

# =========================
# עמודות קבועות
# =========================
SITES = [
    "כפר הילדים חורפיש",
    "אנוש כרמיאל",
    "הפוך על הפוך צפת",
    "שירות מבחן לנוער עכו",
    "כלא חרמון",
    "בית חולים זיו",
    "שירותי רווחה קריית שמונה",
    "מרכז יום לגיל השלישי",
    "מועדונית נוער בצפת",
    "מרפאת בריאות הנפש צפת",
]
RANK_COUNT = 3

COLUMNS_ORDER = [
    "תאריך שליחה", "שם פרטי", "שם משפחה", "תעודת זהות", "מין", "שיוך חברתי",
    "שפת אם", "שפות נוספות", "טלפון", "כתובת", "אימייל",
    "שנת לימודים", "מסלול לימודים",
    "הכשרה קודמת", "הכשרה קודמת מקום ותחום",
    "הכשרה קודמת מדריך ומיקום", "הכשרה קודמת בן זוג",
    "תחומים מועדפים", "תחום מוביל", "בקשה מיוחדת",
    "ממוצע", "התאמות", "התאמות פרטים",
    "מוטיבציה 1", "מוטיבציה 2", "מוטיבציה 3",
] + [f"מקום הכשרה {i}" for i in range(1, RANK_COUNT+1)] + [f"דירוג_{s}" for s in SITES] + [
    "אישור הגעה להכשרה"
]

# =========================
# פונקציה לעיצוב Google Sheets
# =========================

def style_google_sheet(ws):
    """Apply styling to the Google Sheet."""
    
    # --- עיצוב כותרות (שורה 1) ---
    header_fmt = CellFormat(
        backgroundColor=Color(0.6, 0.4, 0.8),   # סגול בהיר
        textFormat=TextFormat(bold=True, foregroundColor=Color(1, 1, 1)),  # טקסט לבן מודגש
        horizontalAlignment='CENTER'
    )
    format_cell_range(ws, "1:1", header_fmt)

    # --- צבעי רקע מתחלפים (פסי זברה) ---
    rule = ConditionalFormatRule(
        ranges=[GridRange.from_a1_range('A2:Z1000', ws)],
        booleanRule=BooleanRule(
            condition=BooleanCondition('CUSTOM_FORMULA', ['=ISEVEN(ROW())']),
            format=CellFormat(backgroundColor=Color(0.95, 0.95, 0.95))  # אפור בהיר
        )
    )
    rules = get_conditional_format_rules(ws)
    rules.clear()
    rules.append(rule)
    rules.save()

    # --- עיצוב עמודת ת"ז (C) ---
    id_fmt = CellFormat(
        horizontalAlignment='CENTER',
        backgroundColor=Color(0.9, 0.9, 0.9)  # אפור עדין
    )
    format_cell_range(ws, "C2:C1000", id_fmt)
# =========================
# פונקציה לשמירה (כולל עיצוב)
# =========================
def save_master_dataframe(new_row: dict) -> None:
    # --- שמירה מקומית ---
    df_master = pd.DataFrame([new_row])
    if CSV_FILE.exists():
        df_master = pd.concat([pd.read_csv(CSV_FILE), df_master], ignore_index=True)
    df_master.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"שאלון_שיבוץ_{ts}.csv"
    df_master.to_csv(backup_path, index=False, encoding="utf-8-sig")

    # --- שמירה ל־ Google Sheets ---
    if sheet:
        try:
            headers = sheet.row_values(1)
            if not headers or headers != COLUMNS_ORDER:
                sheet.clear()
                sheet.append_row(COLUMNS_ORDER, value_input_option="USER_ENTERED")
                style_google_sheet(sheet)   # <<< עיצוב אוטומטי אחרי כותרות

            row_values = [new_row.get(col, "") for col in COLUMNS_ORDER]
            sheet.append_row(row_values, value_input_option="USER_ENTERED")

        except Exception as e:
            st.error(f"❌ לא ניתן לשמור ב־Google Sheets: {e}")


def append_to_log(row_df: pd.DataFrame) -> None:
    file_exists = CSV_LOG_FILE.exists()
    row_df.to_csv(CSV_LOG_FILE, mode="a", header=not file_exists,
                  index=False, encoding="utf-8-sig",
                  quoting=csv.QUOTE_MINIMAL, escapechar="\\", lineterminator="\n")
  # =========================
# פונקציות עזר
# =========================
def load_csv_safely(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    attempts = [
        dict(encoding="utf-8-sig"),
        dict(encoding="utf-8"),
        dict(encoding="utf-8-sig", engine="python", on_bad_lines="skip"),
        dict(encoding="utf-8", engine="python", on_bad_lines="skip"),
        dict(encoding="latin-1", engine="python", on_bad_lines="skip"),
    ]
    for kw in attempts:
        try:
            df = pd.read_csv(path, **kw)
            df.columns = [c.replace("\ufeff", "").strip() for c in df.columns]
            return df
        except Exception:
            continue
    return pd.DataFrame()

def df_to_excel_bytes(df: pd.DataFrame, sheet: str = "Sheet1") -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as w:
        df.to_excel(w, sheet_name=sheet, index=False)
        ws = w.sheets[sheet]
        for i, col in enumerate(df.columns):
            width = 12
            if not df.empty:
                width = min(60, max(12, int(df[col].astype(str).map(len).max()) + 4))
            ws.set_column(i, i, width)
    bio.seek(0)
    return bio.read()

def valid_email(v: str) -> bool:  return bool(re.match(r"^[^@]+@[^@]+\.[^@]+$", v.strip()))
def valid_phone(v: str) -> bool:  return bool(re.match(r"^0\d{1,2}-?\d{6,7}$", v.strip()))
def valid_id(v: str) -> bool:     return bool(re.match(r"^\d{8,9}$", v.strip()))

def show_errors(errors: list[str]):
    if not errors: return
    st.markdown("### :red[נמצאו שגיאות:]")
    for e in errors:
        st.markdown(f"- :red[{e}]")

  # =========================
# מצב מנהל
# =========================
if is_admin_mode:
    st.title("🔑 גישת מנהל – צפייה והורדות (מאסטר + יומן)")
    pwd = st.text_input("סיסמת מנהל", type="password", key="admin_pwd_input")
    if pwd == ADMIN_PASSWORD:
        st.success("התחברת בהצלחה ✅")

        df_master = load_csv_safely(CSV_FILE)
        df_log    = load_csv_safely(CSV_LOG_FILE)

        st.subheader("📦 קובץ ראשי (מאסטר)")
        if not df_master.empty:
            st.dataframe(df_master, use_container_width=True)
            st.download_button(
                "⬇ הורד Excel – קובץ ראשי",
                data=df_to_excel_bytes(df_master, sheet="Master"),
                file_name="שאלון_שיבוץ_master.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("אין עדיין נתונים בקובץ הראשי.")

        st.subheader("🧾 קובץ יומן (Append-Only)")
        if not df_log.empty:
            st.dataframe(df_log, use_container_width=True)
            st.download_button(
                "⬇ הורד Excel – קובץ יומן",
                data=df_to_excel_bytes(df_log, sheet="Log"),
                file_name="שאלון_שיבוץ_log.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("אין עדיין נתונים ביומן.")

    else:
        if pwd:
            st.error("סיסמה שגויה")
    st.stop()

# =========================
# טופס — מנוע שלבים עם כפתורים (במקום tabs)
# =========================
st.title("📋 שאלון שיבוץ סטודנטים – שנת הכשרה תשפ״ו")
st.caption("מלאו/מלאי את כל הסעיפים. השדות המסומנים ב-* הינם חובה.")

STEPS = [
    "סעיף 1: פרטים אישיים",
    "סעיף 2: העדפת שיבוץ",
    "סעיף 3: נתונים אקדמיים",
    "סעיף 4: התאמות",
    "סעיף 5: מוטיבציה",
    "סעיף 6: סיכום ושליחה"
]

if "step" not in st.session_state:
    st.session_state.step = 0
if "acks" not in st.session_state:
    st.session_state.acks = {i: False for i in range(len(STEPS)-1)}  # הצהרה בין הסעיפים 0..4

def goto(i: int):
    st.session_state.step = int(i)

def nav_bar():
    st.markdown("#### ניווט מהיר")
    cols = st.columns(len(STEPS))
    for i, lbl in enumerate(STEPS):
        with cols[i]:
            st.button(
                f"{i+1}",
                key=f"jump_{i}",
                help=lbl,
                on_click=goto, args=(i,),
                use_container_width=True
            )
    st.markdown("---")

def prev_next():
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.session_state.step > 0:
            st.button("⬅ חזרה", on_click=goto, args=(st.session_state.step - 1,), use_container_width=True)
    with c2:
        st.markdown(f"<div style='text-align:center;color:#64748b'>שלב {st.session_state.step+1} מתוך {len(STEPS)}</div>", unsafe_allow_html=True)
    with c3:
        if st.session_state.step < len(STEPS) - 1:
            disabled = not st.session_state.acks.get(st.session_state.step, True) if st.session_state.step <= 4 else False
            st.button("הבא ➡", on_click=goto, args=(st.session_state.step + 1,), disabled=disabled, use_container_width=True)

# בר עליון לניווט מהיר
nav_bar()

step = st.session_state.step
st.subheader(STEPS[step])

# ===== שלב 1: פרטים אישיים =====
if step == 0:
    st.text_input("שם פרטי *", key="first_name")
    st.text_input("שם משפחה *", key="last_name")
    st.text_input("מספר תעודת זהות *", key="nat_id")

    st.radio("מין *", ["זכר","נקבה"], horizontal=True, key="gender")
    st.selectbox("שיוך חברתי *", ["יהודי/ה","מוסלמי/ת","נוצרי/ה","דרוזי/ת"], key="social_affil")

    st.selectbox("שפת אם *", ["עברית","ערבית","רוסית","אחר..."], key="mother_tongue")
    if st.session_state.get("mother_tongue") == "אחר...":
        st.text_input("ציין/ני שפת אם אחרת *", key="other_mt")

    st.multiselect(
        "ציין/י שפות נוספות (ברמת שיחה) *",
        ["עברית","ערבית","רוסית","אמהרית","אנגלית","ספרדית","אחר..."],
        placeholder="בחר/י שפות נוספות", key="extra_langs"
    )
    if "אחר..." in (st.session_state.get("extra_langs") or []):
        st.text_input("ציין/י שפה נוספת (אחר) *", key="extra_langs_other")

    st.text_input("מספר טלפון נייד * (למשל 050-1234567)", key="phone")
    st.text_input("כתובת מלאה (כולל יישוב) *", key="address")
    st.text_input("כתובת דוא״ל *", key="email")

    st.selectbox("שנת הלימודים *", [
        "תואר ראשון - שנה א", "תואר ראשון - שנה ב", "תואר ראשון - שנה ג'",
        "תואר שני - שנה א'", "תואר שני - שנה ב", "אחר"
    ], key="study_year")
    if st.session_state.get("study_year") == "אחר":
        st.text_input("פרט/י שנת לימודים *", key="study_year_other")

    st.selectbox("מסלול הלימודים / תואר *", [
        "תואר ראשון – תוכנית רגילה",
        "תואר ראשון – הסבה",
        "תואר שני"
    ], key="track")

    st.markdown("---")
    st.session_state.acks[0] = st.checkbox("אני מצהיר/ה כי מילאתי פרטים אישיים באופן מדויק. *", key="ack_0", value=st.session_state.acks.get(0, False))
    prev_next()

# ===== שלב 2: העדפת שיבוץ =====
if step == 1:
    st.selectbox("האם עברת הכשרה מעשית בשנה קודמת? *", ["כן","לא","אחר..."], key="prev_training")
    if st.session_state.get("prev_training") in ["כן","אחר..."]:
        st.text_input("אם כן, נא ציין שם מקום ותחום ההתמחות *", key="prev_place")
        st.text_input("שם המדריך והמיקום הגיאוגרפי של ההכשרה *", key="prev_mentor")
        st.text_input("מי היה/תה בן/בת הזוג להתמחות בשנה הקודמת? *", key="prev_partner")

    all_domains = ["רווחה","מוגבלות","זקנה","ילדים ונוער","בריאות הנפש",
                   "שיקום","משפחה","נשים","בריאות","קהילה","אחר..."]
    st.multiselect("בחרו עד 3 תחומים *", all_domains, max_selections=3,
                   placeholder="בחר/י עד שלושה תחומים", key="chosen_domains")

    if "אחר..." in (st.session_state.get("chosen_domains") or []):
        st.text_input("פרט/י תחום אחר *", key="domains_other")

    st.selectbox(
        "מה התחום הכי מועדף עליך, מבין שלושתם? *",
        ["— בחר/י —"] + (st.session_state.get("chosen_domains") or []) if st.session_state.get("chosen_domains") else ["— בחר/י —"],
        key="top_domain"
    )

    # ניסוח דירוג — מודגש ובולט
    st.markdown(
        "<div style='font-weight:700; font-size:1rem; color:#0f172a;'>הדירוג אינו מחייב את מורי השיטות.</div>",
        unsafe_allow_html=True
    )
    st.markdown("**בחר/י מוסד לכל מקום הכשרה (1 = הכי רוצים, 3 = הכי פחות). הבחירה כובלת קדימה — מוסדות שנבחרו ייעלמו מהבחירות הבאות.**")

    # אתחול מצב הבחירות
    for i in range(1, RANK_COUNT + 1):
        st.session_state.setdefault(f"rank_{i}", "— בחר/י —")
        st.session_state.setdefault(f"rank_{i}_select", "— בחר/י —")

    def options_for_rank(rank_i: int) -> list:
        current = st.session_state.get(f"rank_{rank_i}", "— בחר/י —")
        chosen_before = {st.session_state.get(f"rank_{j}") for j in range(1, rank_i)}
        base = ["— בחר/י —"] + [s for s in SITES if (s not in chosen_before or s == current)]
        return base

    cols = st.columns(2)
    for i in range(1, RANK_COUNT + 1):
        with cols[(i - 1) % 2]:
            opts = options_for_rank(i)
            current = st.session_state.get(f"rank_{i}", "— בחר/י —")
            sel = st.selectbox(
                f"מקום הכשרה {i} (בחר/י מוסד) *",
                options=opts,
                index=opts.index(current) if current in opts else 0,
                key=f"rank_{i}_select_widget"
            )
            st.session_state[f"rank_{i}"] = sel
            st.session_state[f"rank_{i}_select"] = sel

    # הסרת כפילויות בזמן אמת
    used = set()
    for i in range(1, RANK_COUNT + 1):
        sel = st.session_state.get(f"rank_{i}", "— בחר/י —")
        if sel != "— בחר/י —":
            if sel in used:
                st.session_state[f"rank_{i}"] = "— בחר/י —"
                st.session_state[f"rank_{i}_select"] = "— בחר/י —"
            else:
                used.add(sel)

    st.text_area("האם קיימת בקשה מיוחדת הקשורה למיקום או תחום ההתמחות? *", height=100, key="special_request")

    st.markdown("---")
    st.session_state.acks[1] = st.checkbox("אני מצהיר/ה כי העדפתי הוזנו במלואן. *", key="ack_1", value=st.session_state.acks.get(1, False))
    prev_next()

# ===== שלב 3: נתונים אקדמיים =====
if step == 2:
    st.number_input("ממוצע ציונים *", min_value=0.0, max_value=100.0, step=0.1, key="avg_grade")
    st.markdown("---")
    st.session_state.acks[2] = st.checkbox("אני מצהיר/ה כי הממוצע שהזנתי נכון. *", key="ack_2", value=st.session_state.acks.get(2, False))
    prev_next()

# ===== שלב 4: התאמות =====
if step == 3:
    st.multiselect(
        "סוגי התאמות (ניתן לבחור כמה) *",
        ["אין","הריון","מגבלה רפואית (למשל: מחלה כרונית, אוטואימונית)",
         "רגישות למרחב רפואי (למשל: לא לשיבוץ בבית חולים)",
         "אלרגיה חמורה","נכות",
         "רקע משפחתי רגיש (למשל: בן משפחה עם פגיעה נפשית)","אחר..."],
        placeholder="בחר/י אפשרויות התאמה", key="adjustments"
    )
    if "אחר..." in (st.session_state.get("adjustments") or []):
        st.text_input("פרט/י התאמה אחרת *", key="adjustments_other")
    if "אין" not in (st.session_state.get("adjustments") or []):
        st.text_area("פרט: *", height=100, key="adjustments_details")

    st.markdown("---")
    st.session_state.acks[3] = st.checkbox("אני מצהיר/ה כי מסרתי מידע מדויק על התאמות. *", key="ack_3", value=st.session_state.acks.get(3, False))
    prev_next()


# ===== שלב 5: מוטיבציה =====
if step == 4:
    likert = ["בכלל לא מסכים/ה","1","2","3","4","מסכים/ה מאוד"]
    st.radio("1) מוכן/ה להשקיע מאמץ נוסף להגיע למקום המועדף *", likert, horizontal=True, key="m1")
    st.radio("2) ההכשרה המעשית חשובה לי כהזדמנות משמעותית להתפתחות *", likert, horizontal=True, key="m2")
    st.radio("3) אהיה מחויב/ת להגיע בזמן ולהתמיד גם בתנאים מאתגרים *", likert, horizontal=True, key="m3")
    st.markdown("---")
    st.session_state.acks[4] = st.checkbox("אני מצהיר/ה כי עניתי בכנות על שאלות המוטיבציה. *", key="ack_4", value=st.session_state.acks.get(4, False))
    prev_next()

# ===== שלב 6: סיכום ושליחה =====
submitted = False
if step == 5:
    st.markdown("בדקו את התקציר. אם יש טעות – חזרו לשלבים המתאימים עם הכפתורים למעלה, תקנו וחזרו לכאן. לאחר אישור ולחיצה על **שליחה** המידע יישמר.")

    # מיפוי מקום הכשרה->מוסד + מוסד->דירוג
    rank_to_site = {i: st.session_state.get(f"rank_{i}", "— בחר/י —") for i in range(1, RANK_COUNT + 1)}
    site_to_rank = {s: None for s in SITES}
    for i, s in rank_to_site.items():
        if s and s != "— בחר/י —":
            site_to_rank[s] = i

    st.markdown("### 📍 העדפות שיבוץ (1=הכי רוצים)")
    summary_pairs = [f"{rank_to_site[i]} – {i}" if rank_to_site[i] != "— בחר/י —" else f"(לא נבחר) – {i}"
                     for i in range(1, RANK_COUNT + 1)]
    st.table(pd.DataFrame({"דירוג": summary_pairs}))

    st.markdown("### 🧑‍💻 פרטים אישיים")
    st.table(pd.DataFrame([{
        "שם פרטי": st.session_state.get("first_name",""), "שם משפחה": st.session_state.get("last_name",""), "ת״ז": st.session_state.get("nat_id",""), "מין": st.session_state.get("gender",""),
        "שיוך חברתי": st.session_state.get("social_affil",""),
        "שפת אם": (st.session_state.get("other_mt","") if st.session_state.get("mother_tongue") == "אחר..." else st.session_state.get("mother_tongue","")),
        "שפות נוספות": "; ".join([x for x in st.session_state.get("extra_langs",[]) if x != "אחר..."] + ([st.session_state.get("extra_langs_other","")] if "אחר..." in st.session_state.get("extra_langs",[]) else [])),
        "טלפון": st.session_state.get("phone",""), "כתובת": st.session_state.get("address",""), "אימייל": st.session_state.get("email",""),
        "שנת לימודים": (st.session_state.get("study_year_other","") if st.session_state.get("study_year") == "אחר" else st.session_state.get("study_year","")),
        "מסלול לימודים": st.session_state.get("track",""),
    }]).T.rename(columns={0: "ערך"}))

    st.markdown("### 🎓 נתונים אקדמיים")
    st.table(pd.DataFrame([{"ממוצע ציונים": st.session_state.get("avg_grade","")}]).T.rename(columns={0: "ערך"}))

    st.markdown("### 🧪 התאמות")
    st.table(pd.DataFrame([{
        "התאמות": "; ".join([a for a in st.session_state.get("adjustments",[]) if a != "אחר..."] + ([st.session_state.get("adjustments_other","")] if "אחר..." in st.session_state.get("adjustments",[]) else [])),
        "פירוט התאמות": st.session_state.get("adjustments_details",""),
    }]).T.rename(columns={0: "ערך"}))

    st.markdown("### 🔥 מוטיבציה")
    st.table(pd.DataFrame([{"מוכנות להשקיע מאמץ": st.session_state.get("m1",""), "חשיבות ההכשרה": st.session_state.get("m2",""), "מחויבות והתמדה": st.session_state.get("m3","")}]).T.rename(columns={0: "ערך"}))

    st.markdown("---")
    arrival_confirm = st.checkbox("אני מצהיר/ה שאגיע בכל דרך להכשרה המעשית שתיקבע לי. *", key="arrival_confirm")
    confirm = st.checkbox("אני מאשר/ת כי המידע שמסרתי נכון ומדויק, וידוע לי שאין התחייבות להתאמה מלאה לבחירותיי. *", key="confirm")
    submitted = st.button("שליחה ✉️")

# ===== התאמה לזרימת הוולידציה והשמירה המקורית (משתנים לוקאליים) =====
# ממפים מ-session_state לשמות המקוריים שלך, כדי לא לשנות ולידציה/שמירה קיימות
first_name       = st.session_state.get("first_name","")
last_name        = st.session_state.get("last_name","")
nat_id           = st.session_state.get("nat_id","")
gender           = st.session_state.get("gender","")
social_affil     = st.session_state.get("social_affil","")
mother_tongue    = st.session_state.get("mother_tongue","")
other_mt         = st.session_state.get("other_mt","")
extra_langs      = st.session_state.get("extra_langs",[])
extra_langs_other= st.session_state.get("extra_langs_other","")
phone            = st.session_state.get("phone","")
address          = st.session_state.get("address","")
email            = st.session_state.get("email","")
study_year       = st.session_state.get("study_year","")
study_year_other = st.session_state.get("study_year_other","")
track            = st.session_state.get("track","")

prev_training    = st.session_state.get("prev_training","לא")
prev_place       = st.session_state.get("prev_place","")
prev_mentor      = st.session_state.get("prev_mentor","")
prev_partner     = st.session_state.get("prev_partner","")

chosen_domains   = st.session_state.get("chosen_domains",[])
domains_other    = st.session_state.get("domains_other","")
top_domain       = st.session_state.get("top_domain","— בחר/י —")

special_request  = st.session_state.get("special_request","")
avg_grade        = st.session_state.get("avg_grade", None)
adjustments      = st.session_state.get("adjustments",[])
adjustments_other= st.session_state.get("adjustments_other","")
adjustments_details = st.session_state.get("adjustments_details","")

m1               = st.session_state.get("m1","")
m2               = st.session_state.get("m2","")
m3               = st.session_state.get("m3","")

arrival_confirm  = st.session_state.get("arrival_confirm", False)
confirm          = st.session_state.get("confirm", False)

# ===== ולידציה ושמירה — מיחזור הבלוק שלך =====
if submitted:
    errors = []

    # סעיף 1 — פרטים אישיים
    if not first_name.strip():
        errors.append("סעיף 1: יש למלא שם פרטי.")
    if not last_name.strip():
        errors.append("סעיף 1: יש למלא שם משפחה.")
    if not valid_id(nat_id):
        errors.append("סעיף 1: ת״ז חייבת להיות 8–9 ספרות.")
    if mother_tongue == "אחר..." and not other_mt.strip():
        errors.append("סעיף 1: יש לציין שפת אם (אחר).")
    if not extra_langs or ("אחר..." in extra_langs and not extra_langs_other.strip()):
        errors.append("סעיף 1: יש לבחור שפות נוספות (ואם 'אחר' – לפרט).")
    if not valid_phone(phone):
        errors.append("סעיף 1: מספר טלפון אינו תקין.")
    if not address.strip():
        errors.append("סעיף 1: יש למלא כתובת מלאה.")
    if not valid_email(email):
        errors.append("סעיף 1: כתובת דוא״ל אינה תקינה.")
    if study_year == "אחר" and not study_year_other.strip():
        errors.append("סעיף 1: יש לפרט שנת לימודים (אחר).")
    if not track.strip():
        errors.append("סעיף 1: יש למלא מסלול לימודים/תואר.")

    # סעיף 2 — העדפת שיבוץ
    rank_to_site = {i: st.session_state.get(f"rank_{i}", "— בחר/י —") for i in range(1, RANK_COUNT + 1)}
    missing = [i for i, s in rank_to_site.items() if s == "— בחר/י —"]
    if missing:
        errors.append(f"סעיף 2: יש לבחור מוסד לכל מקום הכשרה. חסר/ים: {', '.join(map(str, missing))}.")
    chosen_sites = [s for s in rank_to_site.values() if s != "— בחר/י —"]
    if len(set(chosen_sites)) != len(chosen_sites):
        errors.append("סעיף 2: קיימת כפילות בבחירת מוסדות. כל מוסד יכול להופיע פעם אחת בלבד.")

    if prev_training in ["כן","אחר..."] and not prev_place.strip():
        errors.append("סעיף 2: יש למלא מקום/תחום אם הייתה הכשרה קודמת.")
    if prev_training in ["כן","אחר..."] and not prev_mentor.strip():
        errors.append("סעיף 2: יש למלא שם מדריך ומיקום.")
    if prev_training in ["כן","אחר..."] and not prev_partner.strip():
        errors.append("סעיף 2: יש למלא בן/בת זוג להתמחות.")

    if not chosen_domains:
        errors.append("סעיף 2: יש לבחור עד 3 תחומים (לפחות אחד).")
    if "אחר..." in chosen_domains and not domains_other.strip():
        errors.append("סעיף 2: נבחר 'אחר' – יש לפרט תחום.")
    if chosen_domains and (top_domain not in chosen_domains):
        errors.append("סעיף 2: יש לבחור תחום מוביל מתוך השלושה.")
    if any("רווחה" in d for d in chosen_domains) and "שנה ג'" not in study_year:
        errors.append("סעיף 2: תחום רווחה פתוח לשיבוץ רק לסטודנטים שנה ג׳ ומעלה.")

    if not special_request.strip():
        errors.append("סעיף 2: יש לציין בקשה מיוחדת (אפשר 'אין').")

    # סעיף 3 — נתונים אקדמיים
    if avg_grade is None or avg_grade <= 0:
        errors.append("סעיף 3: יש להזין ממוצע ציונים גדול מ-0.")

    # סעיף 4 — התאמות
    adj_list = [a.strip() for a in adjustments]
    has_none = ("אין" in adj_list) and (len([a for a in adj_list if a != "אין"]) == 0)

    if not adj_list:
        errors.append("סעיף 4: יש לבחור לפחות סוג התאמה אחד (או לציין 'אין').")
    if "אחר..." in adj_list and not adjustments_other.strip():
        errors.append("סעיף 4: נבחר 'אחר' – יש לפרט התאמה.")
    if not has_none and not adjustments_details.strip():
        errors.append("סעיף 4: יש לפרט התייחסות להתאמות.")

    # סעיף 5 — מוטיבציה
    if not (m1 and m2 and m3):
        errors.append("סעיף 5: יש לענות על שלוש שאלות המוטיבציה.")

    # סעיף 6 — הצהרות
    if not arrival_confirm:
        errors.append("סעיף 6: יש לסמן את ההצהרה על הגעה להכשרה.")
    if not confirm:
        errors.append("סעיף 6: יש לאשר את הצהרת הדיוק וההתאמה.")

    # הצגת השגיאות או שמירה
    if errors:
        show_errors(errors)
    else:
        # מפות בחירה לשמירה
        site_to_rank = {s: None for s in SITES}
        for i in range(1, RANK_COUNT + 1):
            site = st.session_state.get(f"rank_{i}")
            site_to_rank[site] = i

        # בניית שורה לשמירה
        tz = pytz.timezone("Asia/Jerusalem")
        row = {
            "תאריך שליחה": datetime.now(tz).strftime("%d/%m/%Y %H:%M:%S"),
            "שם פרטי": first_name.strip(),
            "שם משפחה": last_name.strip(),
            "תעודת זהות": nat_id.strip(),
            "מין": gender,
            "שיוך חברתי": social_affil,
            "שפת אם": (other_mt.strip() if mother_tongue == "אחר..." else mother_tongue),
            "שפות נוספות": "; ".join([x for x in extra_langs if x != "אחר..."] + ([extra_langs_other.strip()] if "אחר..." in extra_langs else [])),
            "טלפון": phone.strip(),
            "כתובת": address.strip(),
            "אימייל": email.strip(),
            "שנת לימודים": (study_year_other.strip() if study_year == "אחר" else study_year),
            "מסלול לימודים": track.strip(),
            "הכשרה קודמת": prev_training,
            "הכשרה קודמת מקום ותחום": prev_place.strip(),
            "הכשרה קודמת מדריך ומיקום": prev_mentor.strip(),
            "הכשרה קודמת בן זוג": prev_partner.strip(),
            "תחומים מועדפים": "; ".join([d for d in chosen_domains if d != "אחר..."] + ([domains_other.strip()] if "אחר..." in chosen_domains else [])),
            "תחום מוביל": (top_domain if top_domain and top_domain != "— בחר/י —" else ""),
            "בקשה מיוחדת": special_request.strip(),
            "ממוצע": avg_grade,
            "התאמות": "; ".join([a for a in adjustments if a != "אחר..."] + ([adjustments_other.strip()] if "אחר..." in adjustments else [])),
            "התאמות פרטים": adjustments_details.strip(),
            "מוטיבציה 1": m1,
            "מוטיבציה 2": m2,
            "מוטיבציה 3": m3,
            "אישור הגעה להכשרה": "כן" if arrival_confirm else "לא",
        }

        # 1) שדות "מקום הכשרה i"
        for i in range(1, RANK_COUNT + 1):
            row[f"מקום הכשרה {i}"] = st.session_state.get(f"rank_{i}")
        # 2) Site -> Rank (לשימוש נוח ב-Excel)
        for s in SITES:
            row[f"דירוג_{s}"] = site_to_rank[s]

        try:
            # שמירה במאסטר + Google Sheets
            save_master_dataframe(row)

            # יומן Append-Only
            append_to_log(pd.DataFrame([row]))

            st.success("✅ הטופס נשלח ונשמר בהצלחה! תודה רבה.")
        except Exception as e:
            st.error(f"❌ שמירה נכשלה: {e}")
