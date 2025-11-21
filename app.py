# ============================================================
#                   EDUCONNECT - FINAL VERSION
#                    APP.PY (CLOUDINARY READY)
# ============================================================

import os
import uuid
import sqlite3
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, send_from_directory, g, abort
)
from werkzeug.utils import secure_filename

# ==== REPORTLAB IMPORTS FOR PDF REPORTS ====
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

# ==== CLOUDINARY IMPORTS ====
import cloudinary
from cloudinary import uploader, utils

from urllib.parse import unquote

import psycopg2
import psycopg2.extras

# ============================================================
#                     APP INITIALIZATION
# ============================================================

app = Flask(__name__)
app.secret_key = "supersecretkey_educonnect_2025"

# ============================================================
#                CLOUDINARY CONFIGURATION
# ============================================================

CLOUDINARY_URL = os.getenv("CLOUDINARY_URL")
USE_CLOUDINARY = bool(CLOUDINARY_URL)

if USE_CLOUDINARY:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)


# ============================================================
#               PERSISTENT DISK STORAGE (LOCAL DEV)
# ============================================================

# For Render this is ephemeral, but still useful for:
# - local development
# - generated PDF reports
BASE_DIR = "/opt/render/project/src/data"

# Sub-folders for uploads (used when Cloudinary is OFF or for reports/avatars)
UPLOAD_ROOT = os.path.join(BASE_DIR, "uploads")
PAPERS_FOLDER = os.path.join(UPLOAD_ROOT, "papers")
SOLUTIONS_FOLDER = os.path.join(UPLOAD_ROOT, "solutions")
AVATAR_FOLDER = os.path.join(UPLOAD_ROOT, "avatars")
REPORTS_FOLDER = os.path.join(UPLOAD_ROOT, "reports")

# Database path
DB_PATH = os.path.join(BASE_DIR, "database.db")

for folder in [
    BASE_DIR,
    UPLOAD_ROOT,
    PAPERS_FOLDER,
    SOLUTIONS_FOLDER,
    AVATAR_FOLDER,
    REPORTS_FOLDER,
]:
    os.makedirs(folder, exist_ok=True)


# Allowed file extensions
ALLOWED_PAPER_EXT = {"pdf"}
ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png"}


# ============================================================
#                 DEFAULT USERS (ONLY ONCE)
# ============================================================

DEFAULT_USERS = [
    ("admin", "Ujjwal9512", "teacher", "Admin"),
    ("Rakhi", "Rakhi@9523", "student", "Rakhi"),
    ("student02", "student02", "student", "Student Two"),
    ("student03", "student03", "student", "Student Three"),
]


# ============================================================
#                    DATABASE HELPERS (POSTGRES)
# ============================================================

# small wrapper so db.execute(...).fetchone() keeps working
class DBWrapper:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        return cur  # you can still do .fetchone(), .fetchall()

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def get_db():
    """
    Returns a DBWrapper around a psycopg2 connection.
    Uses DATABASE_URL from environment (Supabase).
    """
    if "db" not in g:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set in environment variables")

        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        g.db = DBWrapper(conn)
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()

    # MAIN TABLE STRUCTURE — Postgres-friendly schema
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            name TEXT NOT NULL,
            profile_pic TEXT
        );
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,    -- local path OR Cloudinary public_id
            uploaded_by TEXT NOT NULL,
            uploaded_at TEXT NOT NULL
        );
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS solutions (
            id SERIAL PRIMARY KEY,
            paper_id INTEGER NOT NULL REFERENCES papers(id),
            student_username TEXT NOT NULL,
            filename TEXT NOT NULL,    -- local path OR Cloudinary public_id
            submitted_at TEXT NOT NULL,
            marks REAL,
            submission_group TEXT,
            total_questions INTEGER,
            attempted INTEGER,
            correct INTEGER,
            incorrect INTEGER,
            total_marks INTEGER,
            obtained_marks REAL,
            passing_marks REAL,
            result_status TEXT
        );
    """)

    # INSERT DEFAULT USERS IF EMPTY
    row = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    count = row["c"] if row else 0

    if count == 0:
        for u, p, r, n in DEFAULT_USERS:
            db.execute(
                """
                INSERT INTO users (username, password, role, name)
                VALUES (%s, %s, %s, %s)
                """,
                (u, p, r, n),
            )

    db.commit()


# 🚀 Important: ensure DB exists even on Render (gunicorn import)
with app.app_context():
    init_db()

# ============================================================
#                         AUTH HELPERS
# ============================================================

def login_required(role=None):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            if "username" not in session:
                return redirect(url_for("login"))

            if role and session.get("role") != role:
                flash("Access denied.", "danger")
                return redirect(url_for("login"))

            return fn(*args, **kwargs)
        wrapper.__name__ = fn.__name__
        return wrapper
    return decorator


def get_current_user():
    if "username" not in session:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE username=?",
                      (session["username"],)).fetchone()


# ============================================================
#                    ROUTES — LOGIN / LOGOUT
# ============================================================

@app.route("/")
def home():
    return redirect(url_for("login"))


# -------------------------- LOGIN ----------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "").strip()
        role = request.form.get("role")

        db = get_db()
        db.execute("""
            SELECT * FROM users
            WHERE LOWER(username) = LOWER(%s)
              AND password = %s
              AND role = %s
        """, (username, password, role))
        user = db.fetchone()

        if user:
            session["username"] = user["username"]
            session["role"] = user["role"]

            flash("Login successful!", "success")

            if user["role"] == "teacher":
                return redirect(url_for("teacher_dashboard"))
            else:
                return redirect(url_for("student_dashboard"))

        flash("Invalid username or password", "danger")

    return render_template("login.html")

# -------------------------- LOGOUT ---------------------------
@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully", "info")
    return redirect(url_for("login"))


# ============================================================
#            TEACHER DASHBOARD — BASE STRUCTURE
# ============================================================

@app.route("/teacher/dashboard")
@login_required(role="teacher")
def teacher_dashboard():
    user = get_current_user()
    db = get_db()

    # All papers
    db.execute("SELECT * FROM papers ORDER BY id DESC;")
    papers_rows = db.fetchall()
    papers = [dict(r) for r in papers_rows]
    papers_by_id = {p["id"]: p for p in papers}

    # All raw solution rows
    db.execute("SELECT * FROM solutions ORDER BY submitted_at DESC;")
    raw_solutions = [dict(r) for r in db.fetchall()]

    # ---------- GROUP BY submission_group ----------
    group_map = {}
    for r in raw_solutions:
        gid = r.get("submission_group") or f"legacy_{r['id']}"
        r["submission_group"] = gid

        if gid not in group_map:
            group_map[gid] = {
                "group_id": gid,
                "paper_id": r["paper_id"],
                "student_username": r["student_username"],
                "submitted_at": r["submitted_at"],
                "marks": r.get("obtained_marks"),
                "files": [],
            }

        group_map[gid]["files"].append(r["filename"])

    grouped_submissions = list(group_map.values())

    # submissions that still need grading (obtained_marks is None)
    ungraded_submissions = [
        g for g in grouped_submissions
        if g["marks"] is None
    ]

    # ---------- TOP STATS ----------
    total_papers = len(papers)
    total_solutions = len(grouped_submissions)

    db.execute("""
        SELECT AVG(obtained_marks) AS a
        FROM solutions
        WHERE obtained_marks IS NOT NULL;
    """)
    avg = db.fetchone()
    avg_marks = round(avg["a"], 2) if avg and avg["a"] is not None else 0

    db.execute("SELECT username, name FROM users WHERE role = 'student';")
    students = db.fetchall()
    total_students = len(students)

    student_stats = []
    for s in students:
        uname = s["username"]

        db.execute("""
            SELECT COUNT(DISTINCT submission_group) AS c
            FROM solutions
            WHERE student_username = %s
              AND obtained_marks IS NOT NULL;
        """, (uname,))
        count_row = db.fetchone()
        c = count_row["c"] if count_row and count_row["c"] is not None else 0

        db.execute("""
            SELECT AVG(obtained_marks) AS a
            FROM solutions
            WHERE student_username = %s
              AND obtained_marks IS NOT NULL;
        """, (uname,))
        avg_row = db.fetchone()
        a = avg_row["a"] if avg_row and avg_row["a"] is not None else None

        student_stats.append({
            "username": uname,
            "name": s["name"],
            "count": c,
            "avg": round(a, 2) if a is not None else 0
        })

    best_student = max(student_stats, key=lambda x: x["avg"]) if student_stats else None

    # ---------- GROUPED SOLUTIONS BY STUDENT ----------
    grouped_solutions = {}
    for gsub in grouped_submissions:
        uname = gsub["student_username"]
        if uname not in grouped_solutions:
            db.execute("SELECT name FROM users WHERE username = %s;", (uname,))
            name_row = db.fetchone()
            grouped_solutions[uname] = {
                "username": uname,
                "name": name_row["name"] if name_row else uname,
                "count": 0,
                "solutions": [],
            }

        paper = papers_by_id.get(gsub["paper_id"])
        grouped_solutions[uname]["count"] += 1
        grouped_solutions[uname]["solutions"].append({
            "paper_title": paper["title"] if paper else "Unknown",
            "submitted_at": gsub["submitted_at"],
            "marks": gsub["marks"],
            "group_id": gsub["group_id"],
        })

    # ----- EXTRA STATS FOR TOP CARDS -----
    answered_paper_ids = {g["paper_id"] for g in grouped_submissions}
    total_answered_papers = len(answered_paper_ids)
    total_not_answered_papers = max(total_papers - total_answered_papers, 0)

    graded_submissions = [g for g in grouped_submissions if g["marks"] is not None]
    total_graded_solutions = len(graded_submissions)
    total_not_graded_solutions = max(total_solutions - total_graded_solutions, 0)

    grouped_solutions = list(grouped_solutions.values())

    return render_template(
        "teacher_dashboard.html",
        user=user,
        papers=papers,
        solutions=ungraded_submissions,
        total_papers=total_papers,
        total_solutions=total_solutions,
        avg_marks=avg_marks,
        total_students=total_students,
        student_stats=student_stats,
        best_student=best_student,
        grouped_solutions=grouped_solutions,
        total_answered_papers=total_answered_papers,
        total_not_answered_papers=total_not_answered_papers,
        total_graded_solutions=total_graded_solutions,
        total_not_graded_solutions=total_not_graded_solutions,
    )

# ============================================================
#               TEACHER — UPLOAD SAMPLE PAPER (Cloudinary RAW)
# ============================================================

@app.route("/upload_paper", methods=["POST"])
@login_required(role="teacher")
def upload_paper():
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    file = request.files.get("file")

    if not title:
        flash("Please enter a paper title.", "warning")
        return redirect(url_for("teacher_dashboard"))

    if not file or not file.filename:
        flash("Please choose a PDF file.", "warning")
        return redirect(url_for("teacher_dashboard"))

    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext != "pdf":
        flash("Only PDF files are allowed.", "danger")
        return redirect(url_for("teacher_dashboard"))

    # 🔹 If using Cloudinary, you’re already uploading there in this function.
    # Here we assume `filename` is a Cloudinary public_id or URL set above.
    filename = secure_filename(file.filename)
    filename = f"paper_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
    # If you're now using Cloudinary upload here, replace file.save(...) with uploader.upload(...)

    db = get_db()
    db.execute(
        """
        INSERT INTO papers (title, filename, uploaded_by, uploaded_at)
        VALUES (%s, %s, %s, %s);
        """,
        (title, filename, session["username"], datetime.now().strftime("%Y-%m-%d %H:%M")),
    )

    flash("Paper uploaded successfully!", "success")
    return redirect(url_for("teacher_dashboard"))

# ============================================================
#                 TEACHER — RENAME PAPER
# ============================================================

@app.route("/rename_paper", methods=["POST"])
@login_required(role="teacher")
def rename_paper():
    paper_id = request.form.get("paper_id")
    new_title = request.form.get("new_title")

    db = get_db()
    db.execute("UPDATE papers SET title = %s WHERE id = %s;", (new_title, paper_id))

    flash("Paper renamed successfully!", "success")
    return redirect(url_for("teacher_dashboard"))

# ============================================================
#                 TEACHER — DELETE PAPER
# ============================================================

@app.route("/delete_paper", methods=["POST"])
@login_required(role="teacher")
def delete_paper():
    paper_id = request.form.get("paper_id")

    db = get_db()
    db.execute("SELECT filename FROM papers WHERE id = %s;", (paper_id,))
    row = db.fetchone()

    # 🔹 If you also want to delete from Cloudinary, do it here using row["filename"]

    db.execute("DELETE FROM solutions WHERE paper_id = %s;", (paper_id,))
    db.execute("DELETE FROM papers WHERE id = %s;", (paper_id,))

    flash("Paper and all related solutions deleted!", "success")
    return redirect(url_for("teacher_dashboard"))

# ============================================================
#             STUDENT — UPLOAD SOLUTION (MULTIPLE FILES)
#        (LOCAL + CLOUDINARY SUPPORT FOR IMAGE PAGES)
# ============================================================

@app.route("/student/upload-solution", methods=["POST"])
@login_required(role="student")
def upload_solution():
    db = get_db()

    paper_id = request.form.get("paper_id")
    files = request.files.getlist("files")

    if not paper_id:
        flash("Please select a paper.", "warning")
        return redirect(url_for("student_dashboard"))

    # One-time submission check
    db.execute("""
        SELECT COUNT(*) AS c
        FROM solutions
        WHERE student_username = %s AND paper_id = %s;
    """, (session["username"], paper_id))
    existing = db.fetchone()["c"]

    if existing > 0:
        flash("You have already submitted a solution for this paper. You cannot submit again.", "warning")
        return redirect(url_for("student_dashboard"))

    if not files or all(not f.filename for f in files):
        flash("Please select at least one JPG/PNG file.", "warning")
        return redirect(url_for("student_dashboard"))

    group_id = str(uuid.uuid4())
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    for f in files:
        if not f.filename:
            continue

        ext = f.filename.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_IMAGE_EXT:
            flash("Only JPG/PNG files are allowed.", "warning")
            return redirect(url_for("student_dashboard"))

        safe = secure_filename(f.filename)
        fname = f"sol_{datetime.now().strftime('%Y%m%d%H%M%S')}_{safe}"

        # If using Cloudinary for solution images, upload here and set fname = public_id

        db.execute("""
            INSERT INTO solutions
              (paper_id, student_username, filename, submitted_at, submission_group)
            VALUES (%s, %s, %s, %s, %s);
        """, (paper_id, session["username"], fname, now_str, group_id))

    flash("Solution submitted successfully!", "success")
    return redirect(url_for("student_dashboard"))

# ============================================================
#                 TEACHER — VIEW SUBMISSION
#            (Supports NEXT / PREVIOUS Image Navigation)
# ============================================================

@app.route("/teacher/view-submission/<group_id>")
@login_required(role="teacher")
def view_submission(group_id):
    db = get_db()

    db.execute(
        "SELECT * FROM solutions WHERE submission_group = %s ORDER BY id;",
        (group_id,),
    )
    rows = db.fetchall()

    if not rows:
        abort(404)

    first = rows[0]
    files = [r["filename"] for r in rows]

    db.execute("SELECT title FROM papers WHERE id = %s;", (first["paper_id"],))
    paper = db.fetchone()

    db.execute(
        "SELECT name, username FROM users WHERE username = %s;",
        (first["student_username"],),
    )
    student = db.fetchone()

    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1
    if page > len(files):
        page = len(files)

    current_file = files[page - 1]

    return render_template(
        "view_submission.html",
        group_id=group_id,
        files=files,
        current_file=current_file,
        page=page,
        total=len(files),
        paper=paper,
        student=student,
    )

# ============================================================
#                 DIRECT SOLUTION FILE VIEWER
# ============================================================

@app.route("/view_solution/<path:filename>")
def view_solution(filename):
    # If it's a Cloudinary URL, just redirect
    if filename.startswith("http"):
        return redirect(filename)

    # Otherwise serve from local folder
    return send_from_directory(SOLUTIONS_FOLDER, filename)



# ============================================================
#                    TEACHER — GRADE SOLUTION
# ============================================================

@app.route("/grade_solution", methods=["POST"])
@login_required(role="teacher")
def grade_solution():
    db = get_db()
    group_id = request.form.get("group_id")

    def to_int(name):
        val = request.form.get(name)
        try:
            return int(val) if val else 0
        except ValueError:
            return 0

    def to_float(name):
        val = request.form.get(name)
        try:
            return float(val) if val else 0.0
        except ValueError:
            return 0.0

    total_questions = to_int("total_questions")
    attempted       = to_int("attempted")
    correct         = to_int("correct")
    incorrect       = to_int("incorrect")
    total_marks     = to_float("total_marks")
    obtained_marks  = to_float("obtained_marks")
    passing_marks   = to_float("passing_marks")

    status = "PASS" if obtained_marks >= passing_marks else "FAIL"

    db.execute("""
        UPDATE solutions
        SET total_questions = %s,
            attempted       = %s,
            correct         = %s,
            incorrect       = %s,
            total_marks     = %s,
            obtained_marks  = %s,
            passing_marks   = %s,
            result_status   = %s
        WHERE submission_group = %s;
    """, (
        total_questions,
        attempted,
        correct,
        incorrect,
        total_marks,
        obtained_marks,
        passing_marks,
        status,
        group_id,
    ))

    flash("Marks saved for this submission.", "success")
    return redirect(url_for("teacher_dashboard") + "#grading")


# ============================================================
#            STUDENT DASHBOARD (Modern Hybrid UI)
# ============================================================

@app.route("/student/dashboard")
@login_required(role="student")
def student_dashboard():
    db = get_db()
    user = get_current_user()

    db.execute("SELECT id, title, filename, uploaded_at FROM papers ORDER BY id DESC;")
    papers = db.fetchall()

    db.execute("""
        SELECT
            s.submission_group,
            s.paper_id,
            MIN(s.submitted_at)           AS submitted_at,
            MAX(s.obtained_marks)         AS obtained_marks,
            MAX(s.result_status)          AS result_status
        FROM solutions s
        WHERE s.student_username = %s
        GROUP BY s.submission_group, s.paper_id
        ORDER BY submitted_at DESC;
    """, (session["username"],))
    solutions_rows = db.fetchall()

    submitted_ids = {row["paper_id"] for row in solutions_rows}
    available_papers = [p for p in papers if p["id"] not in submitted_ids]
    has_papers_left = len(available_papers) > 0

    return render_template(
        "student_dashboard.html",
        user=user,
        papers=papers,
        solutions=solutions_rows,
        submitted_ids=submitted_ids,
        available_papers=available_papers,
        has_papers_left=has_papers_left,
    )



# ============================================================
#                STUDENT — VIEW RESULTS LIST
# ============================================================

@app.route("/student/results")
@login_required(role="student")
def student_results():
    db = get_db()

    db.execute("""
        SELECT
            s.submission_group,
            s.paper_id,
            MIN(s.submitted_at)          AS submitted_at,
            MAX(s.total_questions)       AS total_questions,
            MAX(s.attempted)             AS attempted,
            MAX(s.correct)               AS correct,
            MAX(s.incorrect)             AS incorrect,
            MAX(s.total_marks)           AS total_marks,
            MAX(s.obtained_marks)        AS obtained_marks,
            MAX(s.passing_marks)         AS passing_marks,
            MAX(s.result_status)         AS result_status,
            p.title                      AS paper_title
        FROM solutions s
        JOIN papers p ON p.id = s.paper_id
        WHERE s.student_username = %s
        GROUP BY s.submission_group, s.paper_id, p.title
        ORDER BY submitted_at DESC;
    """, (session["username"],))
    rows = db.fetchall()

    return render_template("student_results.html", rows=rows)


# ============================================================
#                  STUDENT — PROFILE MANAGEMENT
# ============================================================

@app.route("/student/profile", methods=["GET", "POST"])
@login_required(role="student")
def student_profile():
    db = get_db()
    user = get_current_user()
    old_username = user["username"]

    if request.method == "POST":
        new_name = request.form.get("name")
        new_username = request.form.get("username")
        password = request.form.get("password")
        confirm = request.form.get("confirm_password")
        avatar = request.files.get("avatar")

        if new_name:
            db.execute(
                "UPDATE users SET name = %s WHERE username = %s;",
                (new_name, old_username),
            )

        if new_username and new_username != old_username:
            db.execute("SELECT 1 FROM users WHERE username = %s;", (new_username,))
            exists = db.fetchone()

            if exists:
                flash("Username is already taken!", "danger")
                return redirect(url_for("student_profile"))

            db.execute(
                "UPDATE users SET username = %s WHERE username = %s;",
                (new_username, old_username),
            )
            db.execute(
                "UPDATE solutions SET student_username = %s WHERE student_username = %s;",
                (new_username, old_username),
            )

            session["username"] = new_username
            old_username = new_username

        if password:
            if password != confirm:
                flash("Passwords do not match!", "danger")
                return redirect(url_for("student_profile"))
            db.execute(
                "UPDATE users SET password = %s WHERE username = %s;",
                (password, old_username),
            )

        if avatar and avatar.filename:
            ext = avatar.filename.rsplit(".", 1)[-1].lower()
            if ext not in {"jpg", "jpeg", "png"}:
                flash("Invalid image file!", "danger")
                return redirect(url_for("student_profile"))

            safe = secure_filename(avatar.filename)
            fname = f"avatar_{old_username}_{uuid.uuid4().hex[:6]}.{ext}"

            # Save avatar locally or upload via Cloudinary if you want
            avatar.save(os.path.join(AVATAR_FOLDER, fname))

            db.execute(
                "UPDATE users SET profile_pic = %s WHERE username = %s;",
                (fname, old_username),
            )

        flash("Profile updated successfully!", "success")
        return redirect(url_for("student_profile"))

    db.execute(
        "SELECT username, name, profile_pic FROM users WHERE username = %s;",
        (old_username,),
    )
    row = db.fetchone()

    return render_template(
        "student_profile.html",
        profile=row,
        user=get_current_user()
    )



# ============================================================
#                 TEACHER — ANALYTICS PAGE
# ============================================================

@app.route("/teacher/analytics")
@login_required(role="teacher")
def teacher_analytics():
    db = get_db()

    db.execute("""
        SELECT u.name, u.username, AVG(s.obtained_marks) AS avg
        FROM users u
        LEFT JOIN solutions s ON u.username = s.student_username
        WHERE u.role = 'student'
        GROUP BY u.username, u.name
        ORDER BY u.name;
    """)
    avg_students = db.fetchall()

    db.execute("""
        SELECT p.title, AVG(s.obtained_marks) AS avg
        FROM papers p
        LEFT JOIN solutions s ON s.paper_id = p.id
        GROUP BY p.id, p.title
        ORDER BY p.id;
    """)
    avg_papers = db.fetchall()

    return render_template(
        "teacher_analytics.html",
        avg_students=avg_students,
        avg_papers=avg_papers
    )



# ============================================================
#                PDF REPORT GENERATION (FINAL)
# ============================================================

@app.route("/download_report/<group_id>")
@login_required(role="student")
def download_report(group_id):
    db = get_db()

    db.execute("""
        SELECT * FROM solutions
        WHERE submission_group = %s
        LIMIT 1;
    """, (group_id,))
    row = db.fetchone()

    if not row:
        flash("Submission not found.", "danger")
        return redirect(url_for("student_results"))

    if row["obtained_marks"] is None:
        flash("Report will be available only after teacher grading.", "warning")
        return redirect(url_for("student_results"))

    db.execute("SELECT title FROM papers WHERE id = %s;", (row["paper_id"],))
    paper = db.fetchone()

    db.execute("SELECT name FROM users WHERE username = %s;", (row["student_username"],))
    student = db.fetchone()

    filename = f"report_{group_id}.pdf"
    path = os.path.join(REPORTS_FOLDER, filename)

    doc = SimpleDocTemplate(path, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(
        "<b><font size=22 color='#3b82f6'>EduConnect</font></b>",
        styles["Title"]
    ))
    story.append(Spacer(1, 12))

    story.append(Paragraph(
        f"<b>Report for Paper: {paper['title']}</b>",
        styles["Heading2"]
    ))
    story.append(Spacer(1, 20))

    info = [
        ["Student Name", student["name"]],
        ["Paper Name", paper["title"]],
        ["Generated On", datetime.now().strftime("%d-%m-%Y %H:%M")],
    ]

    t = Table(info, colWidths=[150, 300])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
    ]))
    story.append(t)
    story.append(Spacer(1, 20))

    result = [
        ["Total Questions", row["total_questions"]],
        ["Attempted", row["attempted"]],
        ["Correct", row["correct"]],
        ["Incorrect", row["incorrect"]],
        ["Total Marks", row["total_marks"]],
        ["Marks Obtained", row["obtained_marks"]],
        ["Passing Marks", row["passing_marks"]],
        ["Status", row["result_status"]],
    ]

    t2 = Table(result, colWidths=[200, 100])
    t2.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 12),
    ]))
    story.append(t2)
    story.append(Spacer(1, 30))

    color = "#28a745" if row["result_status"] == "PASS" else "#dc3545"
    story.append(Paragraph(
        f"<b><font size=18 color='{color}'>STATUS: {row['result_status']}</font></b>",
        styles["Heading1"]
    ))

    doc.build(story)

    return send_from_directory(REPORTS_FOLDER, filename, as_attachment=True)

# ============================================================
#                   DOWNLOAD PAPER (PDF)
# ============================================================

@app.route("/download_paper/<int:paper_id>")
def download_paper(paper_id):
    db = get_db()
    paper = db.execute(
        "SELECT title, filename FROM papers WHERE id = ?",
        (paper_id,)
    ).fetchone()

    if not paper:
        abort(404)

    stored_value = paper["filename"]

    if USE_CLOUDINARY:
        # stored_value is already a full https://... .pdf URL
        return redirect(stored_value)

    # Local mode: send from disk
    return send_from_directory(
        PAPERS_FOLDER,
        stored_value,
        as_attachment=True,
        download_name=f"{paper['title']}.pdf"
    )



# ============================================================
#                        RUN APPLICATION
# ============================================================

if __name__ == "__main__":
    with app.app_context():
        init_db()

    port = int(os.environ.get("PORT", 10000))   # Render uses PORT env var, local default 10000
    app.run(host="0.0.0.0", port=port)
