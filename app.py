import os
import re
import sqlite3
import secrets
from datetime import datetime
from pathlib import Path
from functools import wraps

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from rag import answer_question, index_all_sources, extract_pdf_text

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = DATA_DIR / "college.db"
ALLOWED_EXTENSIONS = {"pdf", "txt", "md"}

DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024  # 12 MB
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "0") == "1"


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS faqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            question_en TEXT NOT NULL,
            question_ml TEXT NOT NULL DEFAULT '',
            answer_en TEXT NOT NULL,
            answer_ml TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'Sample college data',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            published_on TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'Admin notice'
        );
        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            subject TEXT NOT NULL,
            filename TEXT NOT NULL,
            uploaded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            content TEXT NOT NULL,
            uploaded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chat_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            language TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)

        if conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0:
            username = os.environ.get("ADMIN_USERNAME", "admin")
            password = os.environ.get("ADMIN_PASSWORD", "ChangeMe123!")
            conn.execute(
                "INSERT INTO admins(username,password_hash,created_at) VALUES(?,?,?)",
                (username, generate_password_hash(password), datetime.now().isoformat(timespec="seconds"))
            )

        if conn.execute("SELECT COUNT(*) FROM faqs").fetchone()[0] == 0:
            now = datetime.now().isoformat(timespec="seconds")
            sample_faqs = [
                ("courses", "What course is this assistant for?", "ഈ അസിസ്റ്റന്റ് ഏത് കോഴ്സിനുള്ളതാണ്?",
                 "This demo includes sample information for BCA Web Technology. Replace the sample records with verified information from your college.",
                 "ഈ ഡെമോയിൽ BCA Web Technology സംബന്ധിച്ച മാതൃകാ വിവരങ്ങളുണ്ട്. നിങ്ങളുടെ കോളേജിലെ സ്ഥിരീകരിച്ച വിവരങ്ങൾ ഉപയോഗിച്ച് മാതൃകാ വിവരങ്ങൾ മാറ്റുക.", "Demo data"),
                ("office", "Where can I ask about official college matters?", "കോളേജിന്റെ ഔദ്യോഗിക കാര്യങ്ങൾ എവിടെ ചോദിക്കാം?",
                 "Please contact your department office or college administration for official confirmation. This demo does not contain verified contact numbers.",
                 "ഔദ്യോഗിക സ്ഥിരീകരണത്തിനായി നിങ്ങളുടെ ഡിപ്പാർട്ട്മെന്റ് ഓഫീസിനെയോ കോളേജ് അഡ്മിനിസ്ട്രേഷനെയോ ബന്ധപ്പെടുക. ഈ ഡെമോയിൽ സ്ഥിരീകരിച്ച ഫോൺ നമ്പറുകളില്ല.", "Demo data"),
                ("exams", "Where can I find exam dates?", "പരീക്ഷാ തീയതികൾ എവിടെ ലഭിക്കും?",
                 "Check the latest official college or university examination notice. No real exam dates are included in this demo database.",
                 "ഏറ്റവും പുതിയ ഔദ്യോഗിക കോളേജ് അല്ലെങ്കിൽ സർവകലാശാല പരീക്ഷാ അറിയിപ്പ് പരിശോധിക്കുക. ഈ ഡെമോ ഡാറ്റാബേസിൽ യഥാർത്ഥ പരീക്ഷാ തീയതികൾ ഉൾപ്പെടുത്തിയിട്ടില്ല.", "Demo data"),
                ("materials", "Where can I get study materials?", "പഠനസാമഗ്രികൾ എവിടെ ലഭിക്കും?",
                 "Open the Study Materials page. An administrator can upload approved PDF, TXT, or Markdown files for students.",
                 "Study Materials പേജ് തുറക്കുക. അഡ്മിനിസ്ട്രേറ്റർക്ക് അംഗീകരിച്ച PDF, TXT അല്ലെങ്കിൽ Markdown ഫയലുകൾ അപ്‌ലോഡ് ചെയ്യാം.", "Demo data"),
                ("events", "How do I find upcoming college events?", "വരാനിരിക്കുന്ന കോളേജ് പരിപാടികൾ എങ്ങനെ അറിയാം?",
                 "Open the notices and events section and check the latest official announcement. Add verified event details through the admin dashboard.",
                 "അറിയിപ്പുകളും പരിപാടികളും വിഭാഗം തുറന്ന് ഏറ്റവും പുതിയ ഔദ്യോഗിക അറിയിപ്പ് പരിശോധിക്കുക. അഡ്മിൻ ഡാഷ്ബോർഡിലൂടെ സ്ഥിരീകരിച്ച പരിപാടി വിവരങ്ങൾ ചേർക്കുക.", "Demo data"),
                ("technology", "Which technologies power this project?", "ഈ പ്രോജക്റ്റിൽ ഉപയോഗിക്കുന്ന സാങ്കേതികവിദ്യകൾ ഏതെല്ലാം?",
                 "Python, Flask, HTML, CSS, JavaScript, SQLite, PDF text extraction, and TF-IDF retrieval are used in this demo.",
                 "ഈ ഡെമോയിൽ Python, Flask, HTML, CSS, JavaScript, SQLite, PDF ടെക്സ്റ്റ് എക്സ്ട്രാക്ഷൻ, TF-IDF retrieval എന്നിവ ഉപയോഗിക്കുന്നു.", "Project documentation"),
            ]
            conn.executemany("""INSERT INTO faqs
                (category,question_en,question_ml,answer_en,answer_ml,source,updated_at)
                VALUES(?,?,?,?,?,?,?)""", [x + (now,) for x in sample_faqs])

        if conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO notices(title,body,published_on,source) VALUES(?,?,?,?)",
                ("Demo notice: replace with official notice",
                 "This is placeholder content for demonstration only. Do not treat it as an official college announcement.",
                 datetime.now().date().isoformat(), "Demo data")
            )


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
    )
    return response


@app.route("/")
def index():
    with db() as conn:
        notices = conn.execute("SELECT * FROM notices ORDER BY published_on DESC, id DESC LIMIT 4").fetchall()
        materials = conn.execute("SELECT * FROM materials ORDER BY id DESC LIMIT 4").fetchall()
    return render_template("index.html", notices=notices, materials=materials)


@app.route("/chat")
def chat_page():
    return render_template("chat.html")


@app.post("/api/chat")
def chat_api():
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()
    language = payload.get("language", "auto")
    if not question:
        return jsonify({"error": "Please enter a question."}), 400
    if len(question) > 1000:
        return jsonify({"error": "Please keep the question under 1,000 characters."}), 400

    result = answer_question(question, language)
    with db() as conn:
        conn.execute(
            "INSERT INTO chat_logs(question,answer,language,created_at) VALUES(?,?,?,?)",
            (question, result["answer"], result["language"], datetime.now().isoformat(timespec="seconds"))
        )
    return jsonify(result)


@app.route("/materials")
def materials_page():
    with db() as conn:
        materials = conn.execute("SELECT * FROM materials ORDER BY id DESC").fetchall()
    return render_template("materials.html", materials=materials)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    # Only files registered as study materials are exposed for download.
    with db() as conn:
        row = conn.execute("SELECT id FROM materials WHERE filename=?", (filename,)).fetchone()
    if not row:
        return "Not found", 404
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=True, download_name=filename)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with db() as conn:
            admin = conn.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            session.clear()
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            return redirect(url_for("admin_dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("admin_login.html")


@app.post("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    with db() as conn:
        faqs = conn.execute("SELECT * FROM faqs ORDER BY id DESC").fetchall()
        notices = conn.execute("SELECT * FROM notices ORDER BY id DESC").fetchall()
        materials = conn.execute("SELECT * FROM materials ORDER BY id DESC").fetchall()
        docs = conn.execute("SELECT * FROM documents ORDER BY id DESC").fetchall()
        chats = conn.execute("SELECT * FROM chat_logs ORDER BY id DESC LIMIT 12").fetchall()
    return render_template("admin.html", faqs=faqs, notices=notices, materials=materials, docs=docs, chats=chats)


@app.post("/admin/notice")
@admin_required
def add_notice():
    title = request.form.get("title", "").strip()
    body = request.form.get("body", "").strip()
    published_on = request.form.get("published_on", "").strip() or datetime.now().date().isoformat()
    if not title or not body:
        flash("Notice title and body are required.", "error")
    elif len(title) > 180 or len(body) > 5000:
        flash("Notice is too long.", "error")
    else:
        with db() as conn:
            conn.execute("INSERT INTO notices(title,body,published_on,source) VALUES(?,?,?,?)",
                         (title, body, published_on, "Admin notice"))
        flash("Notice published.", "success")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/faq")
@admin_required
def add_faq():
    fields = [request.form.get(k, "").strip() for k in
              ("category", "question_en", "question_ml", "answer_en", "answer_ml")]
    category, q_en, q_ml, a_en, a_ml = fields
    if not category or not q_en or not a_en:
        flash("Category, English question, and English answer are required.", "error")
    elif any(len(v) > 5000 for v in fields):
        flash("FAQ content is too long.", "error")
    else:
        with db() as conn:
            conn.execute("""INSERT INTO faqs(category,question_en,question_ml,answer_en,answer_ml,source,updated_at)
                VALUES(?,?,?,?,?,?,?)""",
                (category, q_en, q_ml, a_en, a_ml, "Admin FAQ", datetime.now().isoformat(timespec="seconds")))
        flash("FAQ added.", "success")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/upload")
@admin_required
def upload_document():
    file = request.files.get("file")
    title = request.form.get("title", "").strip()
    subject = request.form.get("subject", "").strip() or "General"
    if not file or not file.filename:
        flash("Choose a PDF, TXT, or Markdown file.", "error")
        return redirect(url_for("admin_dashboard"))
    if not allowed_file(file.filename):
        flash("Only PDF, TXT, and Markdown files are allowed.", "error")
        return redirect(url_for("admin_dashboard"))

    original_name = secure_filename(file.filename)
    unique_name = secrets.token_hex(8) + "_" + original_name
    path = UPLOAD_DIR / unique_name
    file.save(path)
    try:
        text = extract_pdf_text(path) if path.suffix.lower() == ".pdf" else path.read_text(encoding="utf-8", errors="replace")
        text = text[:250000]
        if not text.strip():
            raise ValueError("No text found. Scanned PDFs need OCR before upload.")
        with db() as conn:
            conn.execute("INSERT INTO documents(filename,original_name,content,uploaded_at) VALUES(?,?,?,?)",
                         (unique_name, original_name, text, datetime.now().isoformat(timespec="seconds")))
            conn.execute("INSERT INTO materials(title,subject,filename,uploaded_at) VALUES(?,?,?,?)",
                         (title or original_name, subject, unique_name, datetime.now().isoformat(timespec="seconds")))
        index_all_sources()
        flash("Document uploaded and added to the RAG knowledge base.", "success")
    except Exception as exc:
        path.unlink(missing_ok=True)
        flash(f"Could not process document: {exc}", "error")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/reindex")
@admin_required
def reindex():
    index_all_sources()
    flash("Knowledge base reindexed.", "success")
    return redirect(url_for("admin_dashboard"))


@app.errorhandler(413)
def too_large(_error):
    return "Upload too large. Maximum file size is 12 MB.", 413


init_db()
index_all_sources()

if __name__ == "__main__":
    # Debug is deliberately off by default.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
