# -*- coding: utf-8 -*-
import os, csv, re
from io import BytesIO
from pathlib import Path
from datetime import datetime
import pytz
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
from dotenv import load_dotenv

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials
from gspread_formatting import (
    CellFormat, Color, TextFormat,
    ConditionalFormatRule, BooleanRule, BooleanCondition,
    GridRange, format_cell_range, get_conditional_format_rules
)

# ---------- קונפיג ----------
load_dotenv()
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("FLASK_SECRET", "devkey")

DATA_DIR   = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR = DATA_DIR / "backups"; BACKUP_DIR.mkdir(parents=True, exist_ok=True)
CSV_FILE     = DATA_DIR / "שאלון_שיבוץ.csv"
CSV_LOG_FILE = DATA_DIR / "שאלון_שיבוץ_log.csv"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "rawan_0304")

SITES = [
    "כפר הילדים חורפיש","אנוש כרמיאל","הפוך על הפוך צפת","שירות מבחן לנוער עכו","כלא חרמון",
    "בית חולים זיו","שירותי רווחה קריית שמונה","מרכז יום לגיל השלישי","מועדונית נוער בצפת","מרפאת בריאות הנפש צפת"
]
RANK_COUNT = 3

COLUMNS_ORDER = [
    "תאריך שליחה","שם פרטי","שם משפחה","תעודת זהות","מין","שיוך חברתי",
    "שפת אם","שפות נוספות","טלפון","כתובת","אימייל",
    "שנת לימודים","מסלול לימודים",
    "הכשרה קודמת","הכשרה קודמת מקום ותחום","הכשרה קודמת מדריך ומיקום","הכשרה קודמת בן זוג",
    "תחומים מועדפים","תחום מוביל","בקשה מיוחדת",
    "ממוצע","התאמות","התאמות פרטים",
    "מוטיבציה 1","מוטיבציה 2","מוטיבציה 3",
] + [f"מקום הכשרה {i}" for i in range(1, RANK_COUNT+1)] \
  + [f"דירוג_{s}" for s in SITES] + ["אישור הגעה להכשרה"]

# ---------- Google Sheets ----------
def get_sheet():
    try:
        info = {
            "type": os.getenv("GCP_TYPE"),
            "project_id": os.getenv("GCP_PROJECT_ID"),
            "private_key_id": os.getenv("GCP_PRIVATE_KEY_ID"),
            "private_key": os.getenv("GCP_PRIVATE_KEY").encode('utf-8').decode('unicode_escape'),
            "client_email": os.getenv("GCP_CLIENT_EMAIL"),
            "client_id": os.getenv("GCP_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{os.getenv('GCP_CLIENT_EMAIL').replace('@','%40')}"
        }
        scope = ["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(info, scopes=scope)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(os.getenv("SHEET_ID"))
        return sh.sheet1
    except Exception as e:
        print("Sheets error:", e)
        return None

def style_google_sheet(ws):
    header_fmt = CellFormat(
        backgroundColor=Color(0.6,0.4,0.8),
        textFormat=TextFormat(bold=True, foregroundColor=Color(1,1,1)),
        horizontalAlignment='CENTER')
    format_cell_range(ws, "1:1", header_fmt)
    rule = ConditionalFormatRule(
        ranges=[GridRange.from_a1_range('A2:Z1000', ws)],
        booleanRule=BooleanRule(
            condition=BooleanCondition('CUSTOM_FORMULA', ['=ISEVEN(ROW())']),
            format=CellFormat(backgroundColor=Color(0.95,0.95,0.95))))
    rules = get_conditional_format_rules(ws); rules.clear(); rules.append(rule); rules.save()
    format_cell_range(ws, "C2:C1000", CellFormat(horizontalAlignment='CENTER',
                                                 backgroundColor=Color(0.9,0.9,0.9)))

def df_to_excel_bytes(df: pd.DataFrame, sheet: str="Sheet1") -> bytes:
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

# ---------- ולידציות ----------
def valid_email(v): return bool(re.match(r"^[^@]+@[^@]+\.[^@]+$", v.strip()))
def valid_phone(v): return bool(re.match(r"^0\d{1,2}-?\d{6,7}$", v.strip()))
def valid_id(v):    return bool(re.match(r"^\d{8,9}$", v.strip()))

# ---------- עמודים ----------
@app.get("/")
def form():
    return render_template("form.html", sites=SITES, rank_count=RANK_COUNT)

@app.post("/submit")
def submit():
    f = request.form
    errors = []

    # שדות חיוניים (מדגמי – הוסיפי/השלימי כפי שב-Streamlit)
    first_name = f.get("first_name","").strip()
    last_name  = f.get("last_name","").strip()
    nat_id     = f.get("nat_id","").strip()
    gender     = f.get("gender","")
    social     = f.get("social","")
    mother_t   = f.get("mother_t","")
    other_mt   = f.get("other_mt","").strip()
    extra_langs = f.getlist("extra_langs")
    extra_other = f.get("extra_other","").strip()
    phone      = f.get("phone","").strip()
    address    = f.get("address","").strip()
    email      = f.get("email","").strip()
    study_year = f.get("study_year","")
    study_other = f.get("study_other","").strip()
    track      = f.get("track","").strip()
    prev_training = f.get("prev_training","לא")
    prev_place  = f.get("prev_place","").strip()
    prev_mentor = f.get("prev_mentor","").strip()
    prev_partner= f.get("prev_partner","").strip()

    chosen_domains = f.getlist("domains")
    domains_other  = f.get("domains_other","").strip()
    top_domain     = f.get("top_domain","")
    special_req    = f.get("special_req","").strip()

    avg_grade     = f.get("avg_grade","").strip()
    adj_list      = f.getlist("adjustments")
    adj_other     = f.get("adj_other","").strip()
    adj_details   = f.get("adj_details","").strip()

    m1, m2, m3    = f.get("m1",""), f.get("m2",""), f.get("m3","")
    arrival_conf  = f.get("arrival_confirm") == "on"
    confirm_all   = f.get("confirm_all") == "on"

    # ולידציה (כמו אצלך, מקוצר כאן)
    if not first_name: errors.append("יש למלא שם פרטי.")
    if not last_name: errors.append("יש למלא שם משפחה.")
    if not valid_id(nat_id): errors.append("ת״ז חייבת להיות 8–9 ספרות.")
    if mother_t == "אחר" and not other_mt: errors.append("יש לציין שפת אם (אחר).")
    if not extra_langs or ("אחר" in extra_langs and not extra_other):
        errors.append("בחר/י שפות נוספות (ואם 'אחר' – לפרט).")
    if not valid_phone(phone): errors.append("מספר טלפון אינו תקין.")
    if not address: errors.append("יש למלא כתובת מלאה.")
    if not valid_email(email): errors.append("כתובת דוא״ל אינה תקינה.")
    if study_year == "אחר" and not study_other: errors.append("פרט/י שנת לימודים (אחר).")
    if not track: errors.append("יש למלא מסלול לימודים/תואר.")
    # דירוג מוסדות
    ranks = []
    for i in range(1, 1+RANK_COUNT):
        ranks.append(f.get(f"rank_{i}",""))
    if "" in ranks: errors.append("בחר/י מוסד לכל מקום הכשרה.")
    if len(set(ranks)) != len(ranks): errors.append("כפילות בבחירת מוסדות – כל מוסד פעם אחת בלבד.")
    if not chosen_domains: errors.append("בחר/י עד 3 תחומים (לפחות אחד).")
    if "אחר" in chosen_domains and not domains_other:
        errors.append("נבחר 'אחר' – יש לפרט תחום.")
    if chosen_domains and (top_domain not in chosen_domains):
        errors.append("בחר/י תחום מוביל מתוך השלושה.")
    if not special_req: errors.append("בקשה מיוחדת – אפשר לכתוב 'אין'.")
    try:
        avg_val = float(avg_grade)
        if avg_val <= 0: errors.append("ממוצע ציונים גדול מ-0.")
    except:
        errors.append("ממוצע ציונים לא תקין.")
    if not adj_list: errors.append("בחר/י לפחות סוג התאמה אחד (או 'אין').")
    if "אחר" in adj_list and not adj_other: errors.append("נבחר 'אחר' – יש לפרט התאמה.")
    if "אין" not in adj_list and not adj_details: errors.append("פרטי התאמות נדרשים.")
    if not (m1 and m2 and m3): errors.append("ענה/י על 3 שאלות המוטיבציה.")
    if not arrival_conf: errors.append("סמן/ני הצהרת הגעה להכשרה.")
    if not confirm_all: errors.append("אשר/י את הצהרת הדיוק וההתאמה.")

    if errors:
        for e in errors: flash(e, "error")
        return redirect(url_for("form"))

    # בניית שורה לשמירה
    tz = pytz.timezone("Asia/Jerusalem")
    site_to_rank = {s: None for s in SITES}
    for i, s in enumerate(ranks, start=1):
        site_to_rank[s] = i

    row = {
        "תאריך שליחה": datetime.now(tz).strftime("%d/%m/%Y %H:%M:%S"),
        "שם פרטי": first_name, "שם משפחה": last_name, "תעודת זהות": nat_id,
        "מין": gender, "שיוך חברתי": social,
        "שפת אם": (other_mt if mother_t == "אחר" else mother_t),
        "שפות נוספות": "; ".join([x for x in extra_langs if x != "אחר"] + ([extra_other] if "אחר" in extra_langs else [])),
        "טלפון": phone, "כתובת": address, "אימייל": email,
        "שנת לימודים": (study_other if study_year == "אחר" else study_year),
        "מסלול לימודים": track,
        "הכשרה קודמת": prev_training,
        "הכשרה קודמת מקום ותחום": prev_place,
        "הכשרה קודמת מדריך ומיקום": prev_mentor,
        "הכשרה קודמת בן זוג": prev_partner,
        "תחומים מועדפים": "; ".join([d for d in chosen_domains if d != "אחר"] + ([domains_other] if "אחר" in chosen_domains else [])),
        "תחום מוביל": (top_domain or ""),
        "בקשה מיוחדת": special_req,
        "ממוצע": avg_val,
        "התאמות": "; ".join([a for a in adj_list if a != "אחר"] + ([adj_other] if "אחר" in adj_list else [])),
        "התאמות פרטים": adj_details,
        "מוטיבציה 1": m1, "מוטיבציה 2": m2, "מוטיבציה 3": m3,
        "אישור הגעה להכשרה": "כן" if arrival_conf else "לא",
    }
    for i, val in enumerate(ranks, start=1):
        row[f"מקום הכשרה {i}"] = val
    for s in SITES:
        row[f"דירוג_{s}"] = site_to_rank[s]

    # שמירה ל-CSV Master + Backup + Log
    df_new = pd.DataFrame([row])
    if CSV_FILE.exists():
        df_master = pd.read_csv(CSV_FILE, encoding="utf-8-sig")
        df_master = pd.concat([df_master, df_new], ignore_index=True)
    else:
        df_master = df_new
    df_master.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    df_master.to_csv(BACKUP_DIR / f"שאלון_שיבוץ_{ts}.csv", index=False, encoding="utf-8-sig")
    df_new.to_csv(CSV_LOG_FILE, mode="a", header=not CSV_LOG_FILE.exists(),
                  index=False, encoding="utf-8-sig",
                  quoting=csv.QUOTE_MINIMAL, lineterminator="\n")

    # Google Sheets
    ws = get_sheet()
    if ws:
        headers = ws.row_values(1)
        if not headers or headers != COLUMNS_ORDER:
            ws.clear()
            ws.append_row(COLUMNS_ORDER, value_input_option="USER_ENTERED")
            style_google_sheet(ws)
        ws.append_row([row.get(col, "") for col in COLUMNS_ORDER], value_input_option="USER_ENTERED")

    flash("הטופס נשלח ונשמר בהצלחה! תודה 🌟", "success")
    return redirect(url_for("form"))

@app.get("/admin")
def admin():
    if not session.get("admin_ok"):
        return render_template("admin.html", need_login=True)
    # טען נתונים
    df_master = pd.read_csv(CSV_FILE, encoding="utf-8-sig") if CSV_FILE.exists() else pd.DataFrame()
    df_log    = pd.read_csv(CSV_LOG_FILE, encoding="utf-8-sig") if CSV_LOG_FILE.exists() else pd.DataFrame()
    return render_template("admin.html", need_login=False,
                           master=df_master.head(50).to_html(index=False, classes="tbl"),
                           log=df_log.head(50).to_html(index=False, classes="tbl"))

@app.post("/admin")
def admin_login():
    if request.form.get("pwd") == ADMIN_PASSWORD:
        session["admin_ok"] = True
        return redirect(url_for("admin"))
    flash("סיסמה שגויה", "error")
    return redirect(url_for("admin"))

@app.get("/download/<kind>")
def download(kind):
    if not session.get("admin_ok"): return redirect(url_for("admin"))
    if kind == "master" and CSV_FILE.exists():
        df = pd.read_csv(CSV_FILE, encoding="utf-8-sig")
        data = df_to_excel_bytes(df, sheet="Master")
        return send_file(BytesIO(data), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name="שאלון_שיבוץ_master.xlsx")
    if kind == "log" and CSV_LOG_FILE.exists():
        df = pd.read_csv(CSV_LOG_FILE, encoding="utf-8-sig")
        data = df_to_excel_bytes(df, sheet="Log")
        return send_file(BytesIO(data), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name="שאלון_שיבוץ_log.xlsx")
    flash("אין קובץ להורדה", "error"); return redirect(url_for("admin"))

if __name__ == "__main__":
    app.run(debug=True)
