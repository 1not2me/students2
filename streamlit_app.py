# streamlit_app.py
# -*- coding: utf-8 -*-
import csv
import re
from io import BytesIO
from pathlib import Path
from datetime import datetime

import streamlit as st
import pandas as pd

# =========================
# הגדרות כלליות
# =========================
st.set_page_config(page_title="שאלון לסטודנטים – תשפ״ו", layout="centered")

# ====== עיצוב — לפי ה-CSS שביקשת ======
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

# =========================
# נתיבים/סודות + התמדה ארוכת טווח
# =========================
DATA_DIR   = Path("data")
BACKUP_DIR = DATA_DIR / "backups"
DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

CSV_FILE      = DATA_DIR / "שאלון_שיבוץ.csv"         # קובץ ראשי (מצטבר, לעולם לא מתאפס)
CSV_LOG_FILE  = DATA_DIR / "שאלון_שיבוץ_log.csv"     # יומן הוספות (Append-Only)
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "rawan_0304")  # מומלץ לשים ב-secrets

# תמיכה בפרמטר admin=1 ב-URL
is_admin_mode = st.query_params.get("admin", ["0"])[0] == "1"
# =========================
# פונקציות עזר (קבצים/ולידציה/ייצוא)
# =========================
def load_csv_safely(path: Path) -> pd.DataFrame:
    """קריאה חסינה של CSV במספר קידודים, עם דילוג על שורות פגומות במקרה הצורך."""
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

def save_master_dataframe(df: pd.DataFrame) -> None:
    """
    שמירה אטומית של הקובץ הראשי + גיבוי מתוארך.
    לעולם לא מוחקים נתונים קיימים – תמיד מצרפים.
    """
    tmp = CSV_FILE.with_suffix(".tmp.csv")
    df.to_csv(
        tmp,
        index=False,
        encoding="utf-8-sig",
        quoting=csv.QUOTE_MINIMAL,
        escapechar="\\",
        lineterminator="\n",
    )
    tmp.replace(CSV_FILE)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"שאלון_שיבוץ_{ts}.csv"
    df.to_csv(
        backup_path,
        index=False,
        encoding="utf-8-sig",
        quoting=csv.QUOTE_MINIMAL,
        escapechar="\\",
        lineterminator="\n",
    )

def append_to_log(row_df: pd.DataFrame) -> None:
    """יומן Append-Only — מוסיפים שורות בלבד."""
    file_exists = CSV_LOG_FILE.exists()
    row_df.to_csv(
        CSV_LOG_FILE,
        mode="a",
        header=not file_exists,
        index=False,
        encoding="utf-8-sig",
        quoting=csv.QUOTE_MINIMAL,
        escapechar="\\",
        lineterminator="\n",
    )

def df_to_excel_bytes(df: pd.DataFrame, sheet: str = "Sheet1") -> bytes:
    """המרת DataFrame ל-Excel בזיכרון עם התאמת רוחב עמודות."""
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
def valid_phone(v: str) -> bool:  return bool(re.match(r"^0\d{1,2}-?\d{6,7}$", v.strip()))   # 050-1234567 / 04-8123456
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

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📦 קובץ ראשי (מצטבר, לעולם לא נמחק)")
            st.write(f"סה\"כ רשומות: **{len(df_master)}**")
        with col2:
            st.subheader("🧾 קובץ יומן (Append-Only)")
            st.write(f"סה\"כ רשומות ביומן: **{len(df_log)}**")

        st.markdown("### הקובץ הראשי")
        if not df_master.empty:
            st.dataframe(df_master, use_container_width=True)
            st.download_button(
                "📊 הורד Excel – קובץ ראשי",
                data=df_to_excel_bytes(df_master, sheet="Master"),
                file_name="שאלון_שיבוץ_master.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_master_xlsx"
            )
        else:
            st.info("⚠ עדיין אין נתונים בקובץ הראשי.")

        st.markdown("---")
        st.markdown("### קובץ היומן (Append-Only)")
        if not df_log.empty:
            st.dataframe(df_log, use_container_width=True)
            st.download_button(
                "📊 הורד Excel – יומן הוספות",
                data=df_to_excel_bytes(df_log, sheet="Log"),
                file_name="שאלון_שיבוץ_log.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_log_xlsx"
            )
        else:
            st.info("⚠ עדיין אין נתונים ביומן.")

        with st.expander("🗂️ גיבויים (קריאה בלבד)"):
            backups = sorted(BACKUP_DIR.glob("שאלון_שיבוץ_*.csv"))
            if backups:
                st.write(f"נמצאו {len(backups)} גיבויים בתיקייה: `{BACKUP_DIR}`")
                st.write("\n".join(b.name for b in backups[-12:]))
            else:
                st.caption("אין עדיין גיבויים.")
    else:
        if pwd:
            st.error("סיסמה שגויה")
    st.stop()

# =========================
# רשימת שירותים לדירוג — 10 פריטים
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
RANK_COUNT = len(SITES)  # 10

# =========================
# טופס — טאבים
# =========================
st.title("📋 שאלון שיבוץ סטודנטים – שנת הכשרה תשפ״ו")
st.caption("מלאו/מלאי את כל הסעיפים. השדות המסומנים ב-* הינם חובה.")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "סעיף 1: פרטים אישיים", "סעיף 2: העדפת שיבוץ",
    "סעיף 3: נתונים אקדמיים", "סעיף 4: התאמות",
    "סעיף 5: מוטיבציה", "סעיף 6: סיכום ושליחה"
])

# --- סעיף 1 ---
with tab1:
    st.subheader("פרטים אישיים של הסטודנט/ית")
    first_name = st.text_input("שם פרטי *")
    last_name  = st.text_input("שם משפחה *")
    nat_id     = st.text_input("מספר תעודת זהות *")
    gender = st.radio("מין *", ["זכר","נקבה"], horizontal=True)
    social_affil = st.selectbox("שיוך חברתי *", ["יהודי/ה","מוסלמי/ת","נוצרי/ה","דרוזי/ת"])
    mother_tongue = st.selectbox("שפת אם *", ["עברית","ערבית","רוסית","אחר..."])
    other_mt = st.text_input("ציין/ני שפת אם אחרת *") if mother_tongue == "אחר..." else ""
    extra_langs = st.multiselect(
        "ציין/י שפות נוספות (ברמת שיחה) *",
        ["עברית","ערבית","רוסית","אמהרית","אנגלית","ספרדית","אחר..."],
        placeholder="בחר/י שפות נוספות"
    )
    extra_langs_other = st.text_input("ציין/י שפה נוספת (אחר) *") if "אחר..." in extra_langs else ""
    phone   = st.text_input("מספר טלפון נייד * (למשל 050-1234567)")
    address = st.text_input("כתובת מלאה (כולל יישוב) *")
    email   = st.text_input("כתובת דוא״ל *")
    study_year = st.selectbox("שנת הלימודים *", [
        "תואר ראשון - שנה א'", "תואר ראשון - שנה ב'", "תואר ראשון - שנה ג'",
        "הסבה א'", "הסבה ב'", "אחר..."
    ])
    study_year_other = st.text_input("ציין/י שנה/מסלול אחר *") if study_year == "אחר..." else ""
    track = st.text_input("מסלול לימודים / תואר *")
    mobility = st.selectbox("אופן ההגעה להתמחות (ניידות) *", [
        "אוכל להיעזר ברכב / ברשותי רכב",
        "אוכל להגיע בתחבורה ציבורית",
        "אחר..."
    ])
    mobility_other = st.text_input("פרט/י אחר לגבי ניידות *") if mobility == "אחר..." else ""

# --- סעיף 2 ---
with tab2:
    st.subheader("העדפת שיבוץ")

    prev_training = st.selectbox("האם עברת הכשרה מעשית בשנה קודמת? *", ["כן","לא","אחר..."])
    prev_place = prev_mentor = prev_partner = ""
    if prev_training in ["כן","אחר..."]:
        prev_place  = st.text_input("אם כן, נא ציין שם מקום ותחום ההתמחות *")
        prev_mentor = st.text_input("שם המדריך והמיקום הגיאוגרפי של ההכשרה *")
        prev_partner= st.text_input("מי היה/תה בן/בת הזוג להתמחות בשנה הקודמת? *")

    all_domains = ["קהילה","מוגבלות","זקנה","ילדים ונוער","בריאות הנפש","שיקום","משפחה","נשים","בריאות","תָקוֹן","אחר..."]
    chosen_domains = st.multiselect("בחרו עד 3 תחומים *", all_domains, max_selections=3, placeholder="בחר/י עד שלושה תחומים")
    domains_other = st.text_input("פרט/י תחום אחר *") if "אחר..." in chosen_domains else ""
    top_domain = st.selectbox(
        "מה התחום הכי מועדף עליך, מבין שלושתם? *",
        ["— בחר/י —"] + chosen_domains if chosen_domains else ["— בחר/י —"]
    )

    st.markdown("**בחר/י מוסד לכל מדרגה דירוג (1 = הכי רוצים, 10 = הכי פחות). הבחירה כובלת קדימה — מוסדות שנבחרו ייעלמו מהמדרגות הבאות.**")

    # אתחול מצב הבחירות
    for i in range(1, RANK_COUNT + 1):
        st.session_state.setdefault(f"rank_{i}", "— בחר/י —")

    def options_for_rank(rank_i: int) -> list:
        """
        מחזיר רשימת אפשרויות למדרגה i:
        רק מוסדות שטרם נבחרו במדרגות 1..i-1, ועוד הבחירה הנוכחית (אם קיימת),
        כך שהכפילות נמנעת כיוונית (קדימה) בלבד.
        """
        current = st.session_state.get(f"rank_{rank_i}", "— בחר/י —")
        chosen_before = {
            st.session_state.get(f"rank_{j}")
            for j in range(1, rank_i)  # רק מדרגות קודמות
        }
        # בונים רשימה: "— בחר/י —" + כל מוסד שלא נבחר לפני, או שהוא הבחירה הנוכחית
        base = ["— בחר/י —"] + [s for s in SITES if (s not in chosen_before or s == current)]
        # שומרים על סדר SITES:
        ordered = ["— בחר/י —"] + [s for s in SITES if s in base]
        return ordered

    # רנדרינג של המדרגות עם סינון קדימה
    cols = st.columns(2)
    for i in range(1, RANK_COUNT + 1):
        with cols[(i - 1) % 2]:
            opts = options_for_rank(i)
            current = st.session_state.get(f"rank_{i}", "— בחר/י —")
            st.session_state[f"rank_{i}"] = st.selectbox(
                f"מדרגה {i} (בחר/י מוסד)*",
                options=opts,
                index=opts.index(current) if current in opts else 0,
                key=f"rank_{i}_select"
            )
            # מאחדים תחת מפתח קבוע
            st.session_state[f"rank_{i}"] = st.session_state[f"rank_{i}_select"]

    # נורמליזציה: אם שינית מדרגה מוקדמת והתנגשת עם בחירה מאוחרת — ננקה את המאוחרת
    used = set()
    for i in range(1, RANK_COUNT + 1):
        sel = st.session_state.get(f"rank_{i}", "— בחר/י —")
        if sel != "— בחר/י —":
            if sel in used:
                # בחירה כפולה שהתגלתה בגלל שינוי מוקדם -> איפוס המאוחרת
                st.session_state[f"rank_{i}"] = "— בחר/י —"
                st.session_state[f"rank_{i}_select"] = "— בחר/י —"
            else:
                used.add(sel)

    special_request = st.text_area("האם קיימת בקשה מיוחדת הקשורה למיקום או תחום ההתמחות? *", height=100)

# --- סעיף 3 ---
with tab3:
    st.subheader("נתונים אקדמיים")
    avg_grade = st.number_input("ממוצע ציונים *", min_value=0.0, max_value=100.0, step=0.1)

# --- סעיף 4 ---
with tab4:
    st.subheader("התאמות רפואיות, אישיות וחברתיות")
    adjustments = st.multiselect(
        "סוגי התאמות (ניתן לבחור כמה) *",
        ["הריון","מגבלה רפואית (למשל: מחלה כרונית, אוטואימונית)","רגישות למרחב רפואי (למשל: לא לשיבוץ בבית חולים)",
         "אלרגיה חמורה","נכות","רקע משפחתי רגיש (למשל: בן משפחה עם פגיעה נפשית)","אחר..."],
        placeholder="בחר/י אפשרויות התאמה"
    )
    adjustments_other = st.text_input("פרט/י התאמה אחרת *") if "אחר..." in adjustments else ""
    adjustments_details = st.text_area("פרט: *", height=100)

# --- סעיף 5 ---
with tab5:
    st.subheader("מוטיבציה")
    likert = ["בכלל לא מסכים/ה","1","2","3","4","מסכים/ה מאוד"]
    m1 = st.radio("1) מוכן/ה להשקיע מאמץ נוסף להגיע למקום המועדף *", likert, horizontal=True)
    m2 = st.radio("2) ההכשרה המעשית חשובה לי כהזדמנות משמעותית להתפתחות *", likert, horizontal=True)
    m3 = st.radio("3) אהיה מחויב/ת להגיע בזמן ולהתמיד גם בתנאים מאתגרים *", likert, horizontal=True)

# --- סעיף 6 (סיכום ושליחה) ---
with tab6:
    st.subheader("סיכום ושליחה")
    st.markdown("בדקו את התקציר. אם יש טעות – חזרו לטאב המתאים, תקנו וחזרו לכאן. לאחר אישור ולחיצה על **שליחה** המידע יישמר.")

    # מיפוי מדרגה->מוסד + מוסד->מדרגה
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
        "שם פרטי": first_name, "שם משפחה": last_name, "ת״ז": nat_id, "מין": gender,
        "שיוך חברתי": social_affil,
        "שפת אם": (other_mt if mother_tongue == "אחר..." else mother_tongue),
        "שפות נוספות": "; ".join([x for x in extra_langs if x != "אחר..."] + ([extra_langs_other] if "אחר..." in extra_langs else [])),
        "טלפון": phone, "כתובת": address, "אימייל": email,
        "שנת לימודים": (study_year_other if study_year == "אחר..." else study_year),
        "מסלול לימודים": track,
        "ניידות": (mobility_other if mobility == "אחר..." else mobility),
    }]).T.rename(columns={0: "ערך"}))

    st.markdown("### 🎓 נתונים אקדמיים")
    st.table(pd.DataFrame([{"ממוצע ציונים": avg_grade}]).T.rename(columns={0: "ערך"}))

    st.markdown("### 🧪 התאמות")
    st.table(pd.DataFrame([{
        "התאמות": "; ".join([a for a in adjustments if a != "אחר..."] + ([adjustments_other] if "אחר..." in adjustments else [])),
        "פירוט התאמות": adjustments_details,
    }]).T.rename(columns={0: "ערך"}))

    st.markdown("### 🔥 מוטיבציה")
    st.table(pd.DataFrame([{"מוכנות להשקיע מאמץ": m1, "חשיבות ההכשרה": m2, "מחויבות והתמדה": m3}]).T.rename(columns={0: "ערך"}))

    st.markdown("---")
    confirm = st.checkbox("אני מאשר/ת כי המידע שמסרתי נכון ומדויק, וידוע לי שאין התחייבות להתאמה מלאה לבחירותיי. *")
    submitted = st.button("שליחה ✉️")

# =========================
# ולידציה + שמירה
# =========================
if submitted:
    errors = []

    # סעיף 1 — בסיסי
    if not first_name.strip(): errors.append("סעיף 1: יש למלא שם פרטי.")
    if not last_name.strip():  errors.append("סעיף 1: יש למלא שם משפחה.")
    if not valid_id(nat_id):   errors.append("סעיף 1: ת״ז חייבת להיות 8–9 ספרות.")
    if mother_tongue == "אחר..." and not other_mt.strip():
        errors.append("סעיף 1: יש לציין שפת אם (אחר).")
    if not extra_langs or ("אחר..." in extra_langs and not extra_langs_other.strip()):
        errors.append("סעיף 1: יש לבחור שפות נוספות (ואם 'אחר' – לפרט).")
    if not valid_phone(phone): errors.append("סעיף 1: מספר טלפון אינו תקין.")
    if not address.strip():    errors.append("סעיף 1: יש למלא כתובת מלאה.")
    if not valid_email(email): errors.append("סעיף 1: כתובת דוא״ל אינה תקינה.")
    if study_year == "אחר..." and not study_year_other.strip():
        errors.append("סעיף 1: יש לפרט שנת לימודים (אחר).")
    if not track.strip(): errors.append("סעיף 1: יש למלא מסלול לימודים/תואר.")
    if mobility == "אחר..." and not mobility_other.strip():
        errors.append("סעיף 1: יש לפרט ניידות (אחר).")

    # סעיף 2 — דירוג חובה 1..10 ללא כפילויות
    rank_to_site = {i: st.session_state.get(f"rank_{i}", "— בחר/י —") for i in range(1, RANK_COUNT + 1)}
    missing = [i for i, s in rank_to_site.items() if s == "— בחר/י —"]
    if missing:
        errors.append(f"סעיף 2: יש לבחור מוסד לכל מדרגה. חסר/ים: {', '.join(map(str, missing))}.")
    chosen_sites = [s for s in rank_to_site.values() if s != "— בחר/י —"]
    if len(set(chosen_sites)) != len(chosen_sites):
        errors.append("סעיף 2: קיימת כפילות בבחירת מוסדות. כל מוסד יכול להופיע פעם אחת בלבד.")

    if prev_training in ["כן","אחר..."]:
        if not prev_place.strip():  errors.append("סעיף 2: יש למלא מקום/תחום אם הייתה הכשרה קודמת.")
        if not prev_mentor.strip(): errors.append("סעיף 2: יש למלא שם מדריך ומיקום.")
        if not prev_partner.strip():errors.append("ಸעיף 2: יש למלא בן/בת זוג להתמחות.")

    if not chosen_domains:
        errors.append("סעיף 2: יש לבחור עד 3 תחומים (לפחות אחד).")
    if "אחר..." in chosen_domains and not domains_other.strip():
        errors.append("סעיף 2: נבחר 'אחר' – יש לפרט תחום.")
    if chosen_domains and (top_domain not in chosen_domains):
        errors.append("סעיף 2: יש לבחור תחום מוביל מתוך השלושה.")

    if not special_request.strip():
        errors.append("סעיף 2: יש לציין בקשה מיוחדת (אפשר 'אין').")

    # סעיף 3
    if avg_grade is None or avg_grade <= 0:
        errors.append("סעיף 3: יש להזין ממוצע ציונים גדול מ-0.")

    # סעיף 4
    if not adjustments:
        errors.append("סעיף 4: יש לבחור לפחות סוג התאמה אחד (או לציין 'אין').")
    if "אחר..." in adjustments and not adjustments_other.strip():
        errors.append("סעיף 4: נבחר 'אחר' – יש לפרט התאמה.")
    if not adjustments_details.strip():
        errors.append("סעיף 4: יש לפרט התייחסות להתאמות (אפשר 'אין').")

    # סעיף 5
    if not (m1 and m2 and m3):
        errors.append("סעיף 5: יש לענות על שלוש שאלות המוטיבציה.")

    # סעיף 6
    if not confirm:
        errors.append("סעיף 6: יש לאשר את ההצהרה.")

    if errors:
        show_errors(errors)
    else:
        # מפות דירוג לשמירה
        site_to_rank = {s: None for s in SITES}
        for i in range(1, RANK_COUNT + 1):
            site = st.session_state.get(f"rank_{i}")
            site_to_rank[site] = i

        # בניית שורה לשמירה (שימי לב: אין שבירת מחרוזות בעברית)
        row = {
            "תאריך_שליחה": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "שם_פרטי": first_name.strip(),
            "שם_משפחה": last_name.strip(),
            "תעודת_זהות": nat_id.strip(),
            "מין": gender,
            "שיוך_חברתי": social_affil,
            "שפת_אם": (other_mt.strip() if mother_tongue == "אחר..." else mother_tongue),
            "שפות_נוספות": "; ".join([x for x in extra_langs if x != "אחר..."] + ([extra_langs_other.strip()] if "אחר..." in extra_langs else [])),
            "טלפון": phone.strip(),
            "כתובת": address.strip(),
            "אימייל": email.strip(),
            "שנת_לימודים": (study_year_other.strip() if study_year == "אחר..." else study_year),
            "מסלול_לימודים": track.strip(),
            "ניידות": (mobility_other.strip() if mobility == "אחר..." else mobility),
            "הכשרה_קודמת": prev_training,
            "הכשרה_קודמת_מקום_ותחום": prev_place.strip(),
            "הכשרה_קודמת_מדריך_ומיקום": prev_mentor.strip(),
            "הכשרה_קודמת_בן_זוג": prev_partner.strip(),
            "תחומים_מועדפים": "; ".join([d for d in chosen_domains if d != "אחר..."] + ([domains_other.strip()] if "אחר..." in chosen_domains else [])),
            "תחום_מוביל": (top_domain if top_domain and top_domain != "— בחר/י —" else ""),
            "בקשה_מיוחדת": special_request.strip(),
            "ממוצע": avg_grade,
            "התאמות": "; ".join([a for a in adjustments if a != "אחר..."] + ([adjustments_other.strip()] if "אחר..." in adjustments else [])),
            "התאמות_פרטים": adjustments_details.strip(),
            "מוטיבציה_1": m1,
            "מוטיבציה_2": m2,
            "מוטיבציה_3": m3,
        }

        # הוספת שדות דירוג:
        # 1) Rank_i -> Site (מוסד שנבחר לכל מדרגה)
        for i in range(1, RANK_COUNT + 1):
            row[f"דירוג_מדרגה_{i}_מוסד"] = st.session_state.get(f"rank_{i}")
        # 2) Site -> Rank (לשימוש נוח ב-Excel)
        for s in SITES:
            row[f"דירוג_{s}"] = site_to_rank[s]

        try:
            # 1) מאסטר מצטבר (Load+Concat) – לא מתאפס לעולם
            df_master = load_csv_safely(CSV_FILE)
            df_master = pd.concat([df_master, pd.DataFrame([row])], ignore_index=True)
            save_master_dataframe(df_master)

            # 2) יומן Append-Only
            append_to_log(pd.DataFrame([row]))

            st.success("✅ הטופס נשלח ונשמר בהצלחה! תודה רבה.")
        except Exception as e:
            st.error(f"❌ שמירה נכשלה: {e}")
