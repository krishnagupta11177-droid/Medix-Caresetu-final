import csv
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask, jsonify, redirect, render_template, request,
    session, url_for, flash, abort, send_from_directory,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

try:
    import health_assistant as ha
except Exception:
    ha = None

try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
except Exception:
    pass
# ============================================================
# OCR ENGINE (EasyOCR primary, Tesseract fallback)
# ============================================================
OCR_READER = None

def ocr_extract(image_path):
    global OCR_READER
    easy_err = tess_err = ""
    try:
        import easyocr
        if OCR_READER is None:
            OCR_READER = easyocr.Reader(["en", "hi"], gpu=False, verbose=False)
        lines = OCR_READER.readtext(image_path, detail=0)
        return "\n".join(lines), "EasyOCR"
    except Exception as e:
        easy_err = str(e)
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang="eng+hin")
        return text.strip(), "Tesseract"
    except Exception as e:
        tess_err = str(e)
    raise RuntimeError(
        f"EasyOCR failed: {easy_err} | Tesseract failed: {tess_err}. "
        "Run: pip install easyocr (same environment as app.py), then restart."
    )

# ============================================================
# APP + PATHS
# ============================================================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

USERS_CSV_FILE = os.path.join(app.root_path, "users.csv")
PATIENTS_CSV_FILE = os.path.join(app.root_path, "patients.csv")
SEARCH_HISTORY_FILE = os.path.join(app.root_path, "search_history.csv")
DOCUMENT_REQUESTS_FILE = os.path.join(app.root_path, "document_requests.csv")
UPLOAD_PENDING_DIR = os.path.join(app.root_path, "uploads", "pending")
UPLOAD_APPROVED_DIR = os.path.join(app.root_path, "uploads", "approved")
os.makedirs(UPLOAD_PENDING_DIR, exist_ok=True)
os.makedirs(UPLOAD_APPROVED_DIR, exist_ok=True)

USERS_CSV_FIELDS = ["username", "name", "role", "linked_patient_id",
                    "medical_emergency", "password_hash", "last_login"]
PATIENT_CSV_FIELDS = ["patient_id", "name", "age", "gender", "blood_group",
                      "diagnosis", "medical_history", "medications", "allergies",
                      "medical_emergency", "aadhaar_no", "last_updated"]
SEARCH_HISTORY_FIELDS = ["timestamp", "searched_by", "role", "query_id", "result_found"]
DOCUMENT_REQUEST_FIELDS = ["request_id", "timestamp", "username", "patient_id",
                           "original_filename", "stored_path", "note",
                           "extracted_text", "status", "reviewed_by",
                           "reviewed_role", "review_note"]
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}

DEMO_USERS = {
    "admin": {"password": "123", "name": "Admin User", "role": "admin", "linked_patient_id": "", "medical_emergency": "Emergency Contact: ABC, Phone: 9876543210"},
    "dr_sharma": {"password": "pass_sharma_123", "name": "Dr. Rajesh Sharma", "role": "doctor", "linked_patient_id": "", "medical_emergency": "Blood Group: O+, Contact: 9811223344"},
    "dr_neha": {"password": "pass_neha_123", "name": "Dr. Neha Gupta", "role": "doctor", "linked_patient_id": "", "medical_emergency": "Emergency Contact: Vikas, Phone: 9844556677"},
    "staff": {"password": "staff123", "name": "Staff User", "role": "staff", "linked_patient_id": "", "medical_emergency": "Emergency Contact: PQR, Phone: 9988776655"},
}

DEMO_PATIENTS = [
    {"patient_id": "PAT-1001", "name": "Sunita Rao", "age": "54", "gender": "Female", "blood_group": "O+", "diagnosis": "Type 2 Diabetes / Routine Checkup", "medical_history": "Type 2 diabetes since 2018.", "medications": "Metformin 500mg twice daily", "allergies": "No known drug allergies", "medical_emergency": "Contact: Suresh (Son), Phone: 9871122334", "aadhaar_no": "[Aadhaar Redacted]"},
    {"patient_id": "PAT-1002", "name": "Vikram Malhotra", "age": "46", "gender": "Male", "blood_group": "AB+", "diagnosis": "Hypertension & Lipid Profile Review", "medical_history": "Hypertension since 2020.", "medications": "Telmisartan 40mg once daily", "allergies": "None reported", "medical_emergency": "Contact: Meena (Wife), Phone: 9819988776", "aadhaar_no": "[Aadhaar Redacted]"},
    {"patient_id": "PAT-1003", "name": "Kavita Joshi", "age": "32", "gender": "Female", "blood_group": "A-", "diagnosis": "Severe Drug Reaction (Sulfa Group)", "medical_history": "Sulfa reaction in 2023.", "medications": "Levocetirizine 5mg SOS", "allergies": "Sulfa group drugs", "medical_emergency": "Contact: Rakesh (Spouse), Phone: 9765432109", "aadhaar_no": "[Aadhaar Redacted]"},
    {"patient_id": "PAT-1004", "name": "Arjun Nair", "age": "28", "gender": "Male", "blood_group": "B+", "diagnosis": "Acute Asthma Exacerbation", "medical_history": "Childhood asthma.", "medications": "Salbutamol inhaler PRN", "allergies": "Dust allergy", "medical_emergency": "Contact: Dr. Iyer, Phone: 9823019283", "aadhaar_no": "[Aadhaar Redacted]"},
    {"patient_id": "PAT-1005", "name": "Fatima Sheikh", "age": "61", "gender": "Female", "blood_group": "O-", "diagnosis": "Post-Operative Orthopedic Rehabilitation", "medical_history": "Knee replacement 6 weeks ago.", "medications": "Calcium + Vitamin D", "allergies": "Penicillin rash", "medical_emergency": "Contact: Tariq (Brother), Phone: 9890123456", "aadhaar_no": "[Aadhaar Redacted]"},
    {"patient_id": "PAT-1006", "name": "Rahul Verma", "age": "37", "gender": "Male", "blood_group": "B+", "diagnosis": "Anxiety Disorder", "medical_history": "Anxiety with panic episodes since 2022.", "medications": "Escitalopram 10mg daily", "allergies": "None reported", "medical_emergency": "Contact: Anjali (Spouse), Phone: 9812345670", "aadhaar_no": "[Aadhaar Redacted]"},
    {"patient_id": "PAT-1007", "name": "Meena Iyer", "age": "45", "gender": "Female", "blood_group": "A+", "diagnosis": "Hypothyroidism", "medical_history": "Hypothyroidism since 2019.", "medications": "Levothyroxine 75mcg daily", "allergies": "No known drug allergies", "medical_emergency": "Contact: Ravi (Husband), Phone: 9822334455", "aadhaar_no": "[Aadhaar Redacted]"},
    {"patient_id": "PAT-1008", "name": "Sameer Khan", "age": "58", "gender": "Male", "blood_group": "O+", "diagnosis": "CKD Stage 2 with Hypertension", "medical_history": "CKD stage 2, mild proteinuria.", "medications": "Telmisartan 40mg daily", "allergies": "NSAID sensitivity", "medical_emergency": "Contact: Farah (Daughter), Phone: 9890011223", "aadhaar_no": "[Aadhaar Redacted]"},
    {"patient_id": "PAT-1009", "name": "Priya Patel", "age": "24", "gender": "Female", "blood_group": "O-", "diagnosis": "Iron Deficiency Anemia", "medical_history": "Low ferritin with fatigue.", "medications": "Oral iron + Vitamin C", "allergies": "Latex allergy", "medical_emergency": "Contact: Kiran (Mother), Phone: 9765001122", "aadhaar_no": "[Aadhaar Redacted]"},
    {"patient_id": "PAT-1010", "name": "Ramesh Kulkarni", "age": "67", "gender": "Male", "blood_group": "AB-", "diagnosis": "Coronary Artery Disease Post Stent", "medical_history": "Angioplasty with stent in 2023.", "medications": "Aspirin 75mg, Atorvastatin 40mg", "allergies": "No known drug allergies", "medical_emergency": "Contact: Sunita (Wife), Phone: 9823456781", "aadhaar_no": "[Aadhaar Redacted]"},
    {"patient_id": "PAT-1011", "name": "Neha Bhatt", "age": "31", "gender": "Female", "blood_group": "B-", "diagnosis": "PCOS with Insulin Resistance", "medical_history": "Irregular cycles, insulin resistance.", "medications": "Metformin 500mg twice daily", "allergies": "Sulfa drugs rash", "medical_emergency": "Contact: Devang (Brother), Phone: 9900887766", "aadhaar_no": "[Aadhaar Redacted]"},
]

# ============================================================
# CSV HELPERS
# ============================================================
def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", newline="", encoding="utf-8") as f:
        return [{(k or "").strip(): ("" if v is None else str(v).strip())
                 for k, v in row.items() if k is not None}
                for row in csv.DictReader(f)]

def _write_csv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: ("" if row.get(k) is None else str(row.get(k)).strip()) for k in fields})

def read_users(): return _read_csv(USERS_CSV_FILE)
def write_users(r): _write_csv(USERS_CSV_FILE, USERS_CSV_FIELDS, r)
def read_patients(): return _read_csv(PATIENTS_CSV_FILE)
def write_patients(r): _write_csv(PATIENTS_CSV_FILE, PATIENT_CSV_FIELDS, r)
def read_document_requests(): return _read_csv(DOCUMENT_REQUESTS_FILE)
def write_document_requests(r): _write_csv(DOCUMENT_REQUESTS_FILE, DOCUMENT_REQUEST_FIELDS, r)

def dedupe(rows, key):
    seen = {}
    for r in rows:
        k = (r.get(key) or "").strip().upper()
        if k:
            seen[k] = r
    return list(seen.values())

def ensure_patient_logins():
    users = read_users()
    by = {(u.get("username") or "").strip().upper(): u for u in users}
    for p in read_patients():
        pid = (p.get("patient_id") or "").strip().upper()
        if not pid:
            continue
        u = by.get(pid)
        if not u:
            u = {"last_login": ""}
            users.append(u)
        u.update({"username": pid, "name": p.get("name", ""), "role": "patient",
                  "linked_patient_id": pid, "medical_emergency": p.get("medical_emergency", ""),
                  "password_hash": generate_password_hash("patient123")})
    write_users(dedupe(users, "username"))

def init_csv_files():
    users = read_users()
    by = {(u.get("username") or "").strip().upper(): u for u in users}
    for uname, prof in DEMO_USERS.items():
        u = by.get(uname.upper())
        if not u:
            u = {"last_login": ""}
            users.append(u)
        u.update({"username": uname, "name": prof["name"], "role": prof["role"],
                  "linked_patient_id": prof.get("linked_patient_id", ""),
                  "medical_emergency": prof.get("medical_emergency", ""),
                  "password_hash": generate_password_hash(prof["password"])})
    write_users(dedupe(users, "username"))

    patients = read_patients()
    byp = {(p.get("patient_id") or "").strip().upper(): p for p in patients}
    for d in DEMO_PATIENTS:
        pid = d["patient_id"].upper()
        p = byp.get(pid)
        if not p:
            p = {"last_updated": now_iso()}
            patients.append(p)
        p.update(d)
        if not p.get("last_updated"):
            p["last_updated"] = now_iso()
    write_patients(dedupe(patients, "patient_id"))

    ensure_patient_logins()
    if not os.path.exists(SEARCH_HISTORY_FILE):
        _write_csv(SEARCH_HISTORY_FILE, SEARCH_HISTORY_FIELDS, [])
    if not os.path.exists(DOCUMENT_REQUESTS_FILE):
        _write_csv(DOCUMENT_REQUESTS_FILE, DOCUMENT_REQUEST_FIELDS, [])

init_csv_files()
if ha is not None and hasattr(ha, "refresh_chunks"):
    try:
        ha.refresh_chunks()
    except Exception as e:
        print("chunk refresh failed:", e)

# ============================================================
# HELPERS
# ============================================================
def login_required(view):
    @wraps(view)
    def wrapped(*a, **k):
        if "username" not in session:
            return redirect(url_for("login"))
        return view(*a, **k)
    return wrapped

@app.context_processor
def inject_globals():
    pending = 0
    if session.get("role") in ("admin", "doctor"):
        pending = len([r for r in read_document_requests() if r.get("status") == "Pending"])
    return {"nav_pending": pending}

def get_user(username):
    username = (username or "").strip().upper()
    for r in read_users():
        if (r.get("username") or "").strip().upper() == username:
            return r
    return None

def update_last_login(username):
    users = read_users()
    for u in users:
        if (u.get("username") or "").strip().upper() == (username or "").strip().upper():
            u["last_login"] = now_iso()
            break
    write_users(dedupe(users, "username"))

def allowed_file(fn):
    return "." in fn and fn.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_patient_id():
    mx = 1000
    for p in read_patients():
        m = re.search(r"(\d+)", p.get("patient_id", ""))
        if m:
            mx = max(mx, int(m.group(1)))
    return f"PAT-{mx + 1}"

def log_search(by, role, q, found):
    with open(SEARCH_HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=SEARCH_HISTORY_FIELDS).writerow(
            {"timestamp": now_iso(), "searched_by": by, "role": role,
             "query_id": q, "result_found": "Yes" if found else "No"})

def find_patient(pid):
    pid = (pid or "").strip().upper()
    for r in read_patients():
        if (r.get("patient_id") or "").strip().upper() == pid:
            return r
    return None

def find_patient_by_name(name):
    name = (name or "").strip().upper()
    for r in read_patients():
        if (r.get("name") or "").strip().upper() == name:
            return r
    return None

def extract_patient(message):
    m = re.search(r"PAT-\d+", message or "", re.IGNORECASE)
    if m:
        p = find_patient(m.group(0))
        if p:
            return p
    up = (message or "").upper()
    for r in read_patients():
        n = (r.get("name") or "").strip().upper()
        if n and n in up:
            return r
    return None

def patient_chat_response(message, searched_by, role, language="en"):
    patient = extract_patient(message)
    if not patient:
        return None
    log_search(searched_by, role, patient.get("patient_id", ""), True)
    if role == "doctor":
        if language == "hi":
            return (f"रोगी सारांश - {patient.get('name')} ({patient.get('patient_id')}):\n\n"
                    f"- आयु/लिंग: {patient.get('age')} / {patient.get('gender')}\n"
                    f"- ब्लड ग्रुप: {patient.get('blood_group')}\n"
                    f"- निदान: {patient.get('diagnosis')}\n"
                    f"- मेडिकल इतिहास: {patient.get('medical_history', '') or '-'}\n"
                    f"- दवाएं: {patient.get('medications', '') or '-'}\n"
                    f"- एलर्जी: {patient.get('allergies', '') or '-'}\n\n"
                    "कृपया डॉक्टर से पुष्टि करें।")
        return (f"Patient summary - {patient.get('name')} ({patient.get('patient_id')}):\n\n"
                f"- Age/Gender: {patient.get('age')} / {patient.get('gender')}\n"
                f"- Blood Group: {patient.get('blood_group')}\n"
                f"- Diagnosis: {patient.get('diagnosis')}\n"
                f"- Medical History: {patient.get('medical_history', '') or '-'}\n"
                f"- Medications: {patient.get('medications', '') or '-'}\n"
                f"- Allergies: {patient.get('allergies', '') or '-'}\n\n"
                "Please verify with the treating clinician.")
    if language == "hi":
        return "यह रिकॉर्ड मौजूद है, लेकिन विवरण आपके अधिकार क्षेत्र में प्रतिबंधित हैं।"
    return "This record exists, but details are restricted for your role."

def build_document_summary(doc, max_lines=8, max_chars=700):
    text = (doc.get("extracted_text") or "").strip()
    if not text or text.startswith("["):
        return "No readable text was extracted from this document. Open the full file to review it."
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    picked, total = [], 0
    for ln in lines:
        if total + len(ln) > max_chars or len(picked) >= max_lines:
            break
        picked.append(ln)
        total += len(ln) + 1
    summary = "\n".join(picked)
    if len(picked) < len(lines):
        summary += "\n… (open the document to read the full text)"
    return summary

# ============================================================
# AUTH
# ============================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = get_user(username)
        if user and check_password_hash(user.get("password_hash", ""), password):
            session.clear()
            session["username"] = user.get("username")
            session["role"] = user.get("role", "staff")
            session["linked_patient_id"] = user.get("linked_patient_id", "")
            update_last_login(username)
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Invalid username or password")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ============================================================
# DASHBOARD / SEARCH / RECORDS
# ============================================================
@app.route("/")
@login_required
def dashboard():
    role = session.get("role")
    patients = read_patients()
    users = read_users()
    docs = read_document_requests()
    stats, recent = [], []
    if role == "admin":
        stats = [
            {"icon": "users", "tone": "brand", "label": "Total Patients", "value": len(patients)},
            {"icon": "steth", "tone": "sky", "label": "Doctors", "value": len([u for u in users if u.get("role") == "doctor"])},
            {"icon": "file", "tone": "warn", "label": "Pending Approvals", "value": len([d for d in docs if d.get("status") == "Pending"])},
            {"icon": "shield", "tone": "success", "label": "Total Users", "value": len(users)},
        ]
        recent = patients[:5]
    elif role == "doctor":
        stats = [
            {"icon": "users", "tone": "brand", "label": "Patients On Record", "value": len(patients)},
            {"icon": "file", "tone": "warn", "label": "Pending Approvals", "value": len([d for d in docs if d.get("status") == "Pending"])},
            {"icon": "book", "tone": "sky", "label": "Knowledge Sources", "value": len({c.get("source") for c in ha.CHUNKS}) if ha else 0},
            {"icon": "activity", "tone": "success", "label": "Knowledge Chunks", "value": len(ha.CHUNKS) if ha else 0},
        ]
        recent = patients[:5]
    elif role == "patient":
        mine = [d for d in docs if (d.get("username") or "").upper() == (session.get("username") or "").upper()]
        me = find_patient(session.get("linked_patient_id"))
        stats = [
            {"icon": "file", "tone": "brand", "label": "My Documents", "value": len(mine)},
            {"icon": "clock", "tone": "warn", "label": "Pending Review", "value": len([d for d in mine if d.get("status") == "Pending"])},
            {"icon": "check", "tone": "success", "label": "Approved", "value": len([d for d in mine if d.get("status") == "Approved"])},
            {"icon": "heart", "tone": "sky", "label": "Blood Group", "value": (me.get("blood_group") if me else "-") or "-"},
        ]
    return render_template("index.html", stats=stats, recent=recent, role=role)

@app.route("/search", methods=["GET", "POST"])
@login_required
def search():
    role = session.get("role", "")
    if role == "patient":
        return redirect(url_for("my_record"))
    if request.method == "POST":
        q = (request.form.get("patient_query") or "").strip().upper()
        patient = find_patient(q) or find_patient_by_name(q)
        log_search(session.get("username"), role, q, bool(patient))
        if patient:
            return redirect(url_for("patient_record", patient_id=patient.get("patient_id")))
        return render_template("search.html", role=role, error="Patient record not found.")
    return render_template("search.html", role=role)

@app.route("/my-record")
@login_required
def my_record():
    pid = session.get("linked_patient_id", "")
    if not pid:
        return redirect(url_for("dashboard"))
    return redirect(url_for("patient_record", patient_id=pid))

@app.route("/patient-record/<patient_id>")
@login_required
def patient_record(patient_id):
    role = session.get("role", "")
    patient = find_patient(patient_id)
    if not patient:
        return redirect(url_for("search"))
    if role == "patient":
        if (session.get("linked_patient_id") or "").upper() != patient.get("patient_id", "").upper():
            abort(403)
    elif role not in ("doctor", "admin"):
        abort(403)
    docs = [d for d in read_document_requests()
            if (d.get("patient_id") or "").upper() == patient.get("patient_id", "").upper()]
    if role == "patient":
        docs = [d for d in docs if (d.get("username") or "").upper() == (session.get("username") or "").upper()]
    docs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    approved_docs = []
    for d in docs:
        if d.get("status") == "Approved":
            d = dict(d)
            d["summary"] = build_document_summary(d)
            approved_docs.append(d)

    return render_template("patient_record.html", patient=patient, role=role,
                           docs=docs, approved_docs=approved_docs)

# ============================================================
# ADMIN: ADD PATIENT / ADD DOCTOR
# ============================================================
@app.route("/patients/add", methods=["GET", "POST"])
@login_required
def add_patient():
    if session.get("role") != "admin":
        abort(403)
    if request.method == "POST":
        pid = (request.form.get("patient_id") or "").strip().upper() or generate_patient_id()
        if find_patient(pid):
            flash("Patient ID already exists.")
            return redirect(url_for("add_patient"))
        fields = ["name", "age", "gender", "blood_group", "diagnosis", "medical_history",
                  "medications", "allergies", "medical_emergency", "aadhaar_no"]
        row = {f: (request.form.get(f) or "").strip() for f in fields}
        if not row["name"]:
            flash("Patient name is required.")
            return redirect(url_for("add_patient"))
        row["patient_id"] = pid
        row["last_updated"] = now_iso()
        patients = read_patients()
        patients.append(row)
        write_patients(dedupe(patients, "patient_id"))
        if request.form.get("create_login") == "on":
            uname = (request.form.get("username") or pid).strip()
            pwd = (request.form.get("password") or "patient123").strip()
            if not get_user(uname):
                users = read_users()
                users.append({"username": uname, "name": row["name"], "role": "patient",
                              "linked_patient_id": pid, "medical_emergency": row.get("medical_emergency", ""),
                              "password_hash": generate_password_hash(pwd), "last_login": ""})
                write_users(dedupe(users, "username"))
                flash("Patient record and patient login created.")
        ensure_patient_logins()
        return redirect(url_for("patient_record", patient_id=pid))
    return render_template("add_patient.html")

@app.route("/admin/doctors", methods=["GET", "POST"])
@login_required
def admin_doctors():
    if session.get("role") != "admin":
        abort(403)
    if request.method == "POST":
        uname = (request.form.get("username") or "").strip()
        name = (request.form.get("name") or "").strip()
        pwd = (request.form.get("password") or "").strip()
        if not uname or not name or len(pwd) < 6:
            flash("Username, name and a password of 6+ characters are required.")
        elif get_user(uname):
            flash("Username already exists.")
        else:
            users = read_users()
            users.append({"username": uname, "name": name, "role": "doctor", "linked_patient_id": "",
                          "medical_emergency": (request.form.get("medical_emergency") or "").strip(),
                          "password_hash": generate_password_hash(pwd), "last_login": ""})
            write_users(dedupe(users, "username"))
            flash(f"Doctor account '{uname}' created.")
            return redirect(url_for("admin_doctors"))
    doctors = sorted([u for u in read_users() if (u.get("role") or "").lower() == "doctor"],
                     key=lambda x: (x.get("username") or "").lower())
    return render_template("admin_doctors.html", doctors=doctors)

# ============================================================
# PATIENT UPLOAD + AI OCR
# ============================================================
@app.route("/upload-document", methods=["POST"])
@login_required
def upload_document():
    if session.get("role") != "patient":
        abort(403)
    pid = (session.get("linked_patient_id") or session.get("username") or "UNKNOWN").strip().upper()
    file = request.files.get("document")
    if not file or file.filename == "" or not allowed_file(file.filename):
        flash("Please select a valid PDF/PNG/JPG file.")
        return redirect(url_for("patient_record", patient_id=pid))

    safe = secure_filename(file.filename) or "document"
    stored = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{pid}_{uuid.uuid4().hex[:8]}_{safe}"
    path = os.path.join(UPLOAD_PENDING_DIR, stored)
    file.save(path)

    extracted_text = ""
    ocr_status = "Skipped (PDF)"
    if safe.lower().endswith((".png", ".jpg", ".jpeg")):
        try:
            extracted_text, backend = ocr_extract(path)
            ocr_status = f"Success ({backend})"
        except RuntimeError as e:
            print("OCR ERROR:", e)
            extracted_text = f"[OCR unavailable: {e}]"
            ocr_status = "Unavailable"
    else:
        extracted_text = "[PDF uploaded. Text extraction not applied.]"

    rows = read_document_requests()
    rows.append({"request_id": uuid.uuid4().hex, "timestamp": now_iso(),
                 "username": session.get("username"), "patient_id": pid,
                 "original_filename": file.filename, "stored_path": path,
                 "note": (request.form.get("note") or "").strip(),
                 "extracted_text": extracted_text, "status": "Pending",
                 "reviewed_by": "", "reviewed_role": "", "review_note": ""})
    write_document_requests(rows)
    flash(f"Prescription scanned ({ocr_status}) and sent for approval.")
    return redirect(url_for("patient_record", patient_id=pid))

@app.route("/rescan-ocr/<request_id>")
@login_required
def rescan_ocr(request_id):
    role = session.get("role")
    rows = read_document_requests()
    target = None
    for r in rows:
        if r.get("request_id") == request_id:
            target = r
            break
    if not target:
        abort(404)
    if role == "patient":
        if target.get("username") != session.get("username"):
            abort(403)
    elif role not in ("admin", "doctor"):
        abort(403)
    path = target.get("stored_path", "")
    if not path or not os.path.exists(path):
        flash("Original file not found for re-scan.")
        return redirect(request.referrer or url_for("dashboard"))
    if not path.lower().endswith((".png", ".jpg", ".jpeg")):
        flash("Re-scan works only for image files (PNG/JPG).")
        return redirect(request.referrer or url_for("dashboard"))
    try:
        text, backend = ocr_extract(path)
        target["extracted_text"] = text
        flash(f"OCR re-scan complete ({backend}). Summary updated.")
    except RuntimeError as e:
        target["extracted_text"] = f"[OCR unavailable: {e}]"
        flash(f"OCR re-scan failed: {e}")
    write_document_requests(rows)
    return redirect(request.referrer or url_for("dashboard"))

# ============================================================
# SHARED APPROVALS (ADMIN + DOCTOR) — REJECTION REQUIRES REASON
# ============================================================
@app.route("/approvals")
@login_required
def approvals():
    role = session.get("role")
    if role not in ("admin", "doctor"):
        abort(403)
    rows = read_document_requests()
    sf = request.args.get("status", "all")
    if sf in ("Pending", "Approved", "Rejected"):
        rows = [r for r in rows if r.get("status") == sf]
    rows.sort(key=lambda x: (x.get("status") != "Pending", x.get("timestamp", "")))
    return render_template("approvals.html", rows=rows, status_filter=sf, role=role)

@app.route("/approvals/<request_id>/review", methods=["POST"])
@login_required
def review_document_request(request_id):
    role = session.get("role")
    if role not in ("admin", "doctor"):
        abort(403)

    status = request.form.get("status")
    review_note = (request.form.get("review_note") or "").strip()

    if status not in ("Approved", "Rejected"):
        abort(400)

    # MANDATORY reason on rejection (server-side enforcement)
    if status == "Rejected" and not review_note:
        flash("A reason is required to reject a document. Please provide the rejection reason.")
        return redirect(url_for("approvals"))

    rows = read_document_requests()
    target = None
    for r in rows:
        if r.get("request_id") == request_id:
            target = r
            if r.get("status") != "Pending":
                flash("Already reviewed.")
                return redirect(url_for("approvals"))
            r["status"] = status
            r["reviewed_by"] = session.get("username")
            r["reviewed_role"] = role
            r["review_note"] = review_note
            if status == "Approved":
                old = r.get("stored_path", "")
                if old and os.path.exists(old):
                    new = os.path.join(UPLOAD_APPROVED_DIR, os.path.basename(old))
                    if os.path.exists(new):
                        new = os.path.join(UPLOAD_APPROVED_DIR, f"{uuid.uuid4().hex[:6]}_{os.path.basename(old)}")
                    shutil.move(old, new)
                    r["stored_path"] = new
            break
    if not target:
        abort(404)

    write_document_requests(rows)
    if status == "Rejected":
        flash(f"Document rejected by {role}. Reason recorded: {review_note}")
    else:
        flash(f"Document approved by {role}.")
    return redirect(url_for("approvals"))

@app.route("/documents/<request_id>/view")
@login_required
def view_document(request_id):
    role = session.get("role")
    target = None
    for r in read_document_requests():
        if r.get("request_id") == request_id:
            target = r
            break
    if not target:
        abort(404)
    if role == "patient":
        if target.get("username") != session.get("username") or target.get("status") != "Approved":
            abort(403)
    elif role not in ("admin", "doctor"):
        abort(403)
    path = target.get("stored_path", "")
    if not path or not os.path.exists(path):
        abort(404)
    return send_from_directory(os.path.dirname(path), os.path.basename(path))

# ============================================================
# ADMIN MISC
# ============================================================
@app.route("/admin-data")
@login_required
def admin_data():
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))
    rows = [{"username": r.get("username", ""), "name": r.get("name", ""), "role": r.get("role", ""),
             "linked_patient_id": r.get("linked_patient_id", ""),
             "last_login": r.get("last_login", "") or "Not logged in"} for r in read_users()]
    return render_template("admin_data.html", rows=rows)

@app.route("/admin/refresh-knowledge")
@login_required
def refresh_knowledge():
    if session.get("role") != "admin":
        abort(403)
    if ha is not None and hasattr(ha, "refresh_chunks"):
        ha.refresh_chunks()
    flash("Knowledge base refreshed.")
    return redirect(url_for("dashboard"))

# ============================================================
# CHATBOT (EN + STRICT HI)
# ============================================================
@app.route("/chat", methods=["GET", "POST"])
def chat():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        language = (data.get("language") or "en").lower()
        if language not in ("en", "hi"):
            language = "en"
        if "username" not in session:
            return jsonify({"reply": "Please log in first.", "requires_login": True}), 401
        role = session.get("role", "")
        if role not in ("doctor", "patient"):
            return jsonify({"reply": "Chatbot access is restricted for your role."}), 403
        msg = (data.get("message") or "").strip()
        if not msg:
            return jsonify({"reply": "कृपया पहले कोई प्रश्न भेजें। 😊" if language == "hi" else "Please type a question first. 😊"})
        if msg.lower() in ("update", "अपडेट"):
            if role != "doctor":
                return jsonify({"reply": "केवल डॉक्टर नॉलेज बेस अपडेट कर सकते हैं।" if language == "hi" else "Only doctors can update the knowledge base."})
            if ha is not None and hasattr(ha, "refresh_chunks"):
                ha.refresh_chunks()
                return jsonify({"reply": "✅ नॉलेज बेस अपडेट हो गया।" if language == "hi" else "✅ Knowledge base updated."})
        if role == "patient":
            low = msg.lower()
            if (re.search(r"pat-\d+", low)
                    or re.search(r"\b(my|mera|meri|mine)\b.*\b(history|summary|record|diagnosis|condition|medication|allergy)\b", low)):
                return jsonify({"reply": "आप चैटबॉट से अपना रिकॉर्ड सारांश नहीं ले सकते। कृपया My Medical Record पेज देखें।" if language == "hi"
                                else "You cannot retrieve your medical record summary through the chatbot. Please use the My Medical Record page."})
        if role == "doctor":
            pr = patient_chat_response(msg, session.get("username"), role, language)
            if pr:
                return jsonify({"reply": pr})
        reply = None
        if ha is not None and hasattr(ha, "answer"):
            try:
                reply = ha.answer(msg, language)
            except TypeError:
                reply = ha.answer(msg)
            except Exception as e:
                print("assistant error:", e)
        if not reply:
            reply = ("क्षमा करें, मुझे इसका सटीक उत्तर नहीं मिला। कृपया अपना प्रश्न दोहराएं।"
                     if language == "hi" else
                     "Sorry, I couldn't find an exact answer. Please rephrase your question.")
        return jsonify({"reply": str(reply)})
    if "username" not in session:
        return redirect(url_for("login"))
    role = session.get("role", "")
    if role not in ("doctor", "patient"):
        return redirect(url_for("dashboard"))
    return render_template("chat.html", username=session.get("username"), role=role)

if __name__ == "__main__":
    print("Starting ClearID Clinical OS...")
    print("Open: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
