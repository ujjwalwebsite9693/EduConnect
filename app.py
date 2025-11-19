# ============================================================
#                   EDUCONNECT - FINAL VERSION
#                    APP.PY (PART 1 OF 5)
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


# ============================================================
#                     APP INITIALIZATION
# ============================================================

app = Flask(__name__)
app.secret_key = "supersecretkey_educonnect_2025"

# ============================================================
#               PERSISTENT DISK STORAGE (RENDER)
# ============================================================

# Base directory for all permanent data
BASE_DIR = "/opt/render/project/src/data"

# Sub-folders for uploads
UPLOAD_ROOT = os.path.join(BASE_DIR, "uploads")
PAPERS_FOLDER = os.path.join(UPLOAD_ROOT, "papers")
SOLUTIONS_FOLDER = os.path.join(UPLOAD_ROOT, "solutions")
AVATAR_FOLDER = os.path.join(UPLOAD_ROOT, "avatars")
REPORTS_FOLDER = os.path.join(UPLOAD_ROOT, "reports")

# Database path (also on disk)
DB_PATH = os.path.join(BASE_DIR, "database.db")

# Ensure folders exist
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
#                    DATABASE HELPERS
# ============================================================

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()

    # MAIN TABLE STRUCTURE
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            name TEXT NOT NULL,
            profile_pic TEXT
        );

        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,
            uploaded_by TEXT NOT NULL,
            uploaded_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS solutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL,
            student_username TEXT NOT NULL,
            filename TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            marks REAL,
            submission_group TEXT,
            total_questions INTEGER,
            attempted INTEGER,
            correct INTEGER,
            incorrect INTEGER,
            total_marks INTEGER,
            obtained_marks INTEGER,
            passing_marks INTEGER,
            result_status TEXT,
            FOREIGN KEY (paper_id) REFERENCES papers (id)
        );
    """)

    # AUTO-ADD missing columns (SAFE MIGRATION)
    cols = {c["name"] for c in db.execute("PRAGMA table_info(solutions)")}

    needed = {
        "submission_group": "TEXT",
        "total_questions": "INTEGER",
        "attempted": "INTEGER",
        "correct": "INTEGER",
        "incorrect": "INTEGER",
        "total_marks": "INTEGER",
        "obtained_marks": "INTEGER",
        "passing_marks": "INTEGER",
        "result_status": "TEXT"
    }

    for col, ctype in needed.items():
        if col not in cols:
            db.execute(f"ALTER TABLE solutions ADD COLUMN {col} {ctype}")

    # INSERT DEFAULT USERS IF EMPTY
    count = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    if count == 0:
        for u, p, r, n in DEFAULT_USERS:
            db.execute(
                "INSERT INTO users (username, password, role, name) VALUES (?, ?, ?, ?)",
                (u, p, r, n)
            )

    db.commit()


# =======================================================
# 🚀 AUTO-RUN DATABASE INITIALIZATION (RENDER FIX)
# =======================================================

# Render does NOT execute `if __name__ == "__main__"` during deployment,
# so we MUST force DB creation at import time.
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
        user = db.execute("""
            SELECT * FROM users
            WHERE LOWER(username)=LOWER(?) AND password=? AND role=?
        """, (username, password, role)).fetchone()

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
    papers_rows = db.execute(
        "SELECT * FROM papers ORDER BY id DESC"
    ).fetchall()
    papers = [dict(r) for r in papers_rows]
    papers_by_id = {p["id"]: p for p in papers}

    # All raw solution rows
    raw_solutions = [dict(r) for r in db.execute(
        "SELECT * FROM solutions ORDER BY submitted_at DESC"
    ).fetchall()]

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
    total_solutions = len(grouped_submissions)  # all submissions (graded + ungraded)

    avg = db.execute(
        "SELECT AVG(obtained_marks) AS a FROM solutions WHERE obtained_marks IS NOT NULL"
    ).fetchone()
    avg_marks = round(avg["a"], 2) if avg and avg["a"] is not None else 0

    students = db.execute(
        "SELECT username, name FROM users WHERE role='student'"
    ).fetchall()
    total_students = len(students)

    student_stats = []
    for s in students:
        uname = s["username"]
        count_row = db.execute(
            """
            SELECT COUNT(DISTINCT submission_group) AS c
            FROM solutions
            WHERE student_username = ? AND obtained_marks IS NOT NULL
            """,
            (uname,),
        ).fetchone()
        c = count_row["c"] if count_row else 0

        avg_row = db.execute(
            """
            SELECT AVG(obtained_marks) AS a
            FROM solutions
            WHERE student_username = ? AND obtained_marks IS NOT NULL
            """,
            (uname,),
        ).fetchone()
        a = avg_row["a"] if avg_row else None

        student_stats.append({
            "username": uname,
            "name": s["name"],
            "count": c,
            "avg": round(a, 2) if a is not None else 0
        })

    best_student = max(student_stats, key=lambda x: x["avg"]) if student_stats else None

    # ---------- GROUPED SOLUTIONS BY STUDENT (for accordion tab) ----------
    grouped_solutions = {}
    for g in grouped_submissions:
        uname = g["student_username"]
        if uname not in grouped_solutions:
            name_row = db.execute(
                "SELECT name FROM users WHERE username=?",
                (uname,),
            ).fetchone()
            grouped_solutions[uname] = {
                "username": uname,
                "name": name_row["name"] if name_row else uname,
                "count": 0,
                "solutions": [],
            }

        paper = papers_by_id.get(g["paper_id"])
        grouped_solutions[uname]["count"] += 1
        grouped_solutions[uname]["solutions"].append({
            "paper_title": paper["title"] if paper else "Unknown",
            "submitted_at": g["submitted_at"],
            "marks": g["marks"],
            "group_id": g["group_id"],
        })


        # ----- EXTRA STATS FOR TOP CARDS -----
    # papers that have at least one submission
    answered_paper_ids = {g["paper_id"] for g in grouped_submissions}
    total_answered_papers = len(answered_paper_ids)
    total_not_answered_papers = max(total_papers - total_answered_papers, 0)

    # graded vs not graded submissions
    graded_submissions = [g for g in grouped_submissions if g["marks"] is not None]
    total_graded_solutions = len(graded_submissions)
    total_not_graded_solutions = max(total_solutions - total_graded_solutions, 0)

    grouped_solutions = list(grouped_solutions.values())

    return render_template(
    "teacher_dashboard.html",
    user=user,
    papers=papers,
    solutions=ungraded_submissions,   # 👈 ONLY ones that still need marks
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
#               TEACHER — UPLOAD SAMPLE PAPER
# ============================================================

@app.route("/upload_paper", methods=["POST"])
@login_required(role="teacher")
def upload_paper():
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()  # optional, store if you want
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

    # Save file
    filename = secure_filename(file.filename)
    filename = f"paper_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
    file.save(os.path.join(PAPERS_FOLDER, filename))

    db = get_db()
    db.execute(
        "INSERT INTO papers (title, filename, uploaded_by, uploaded_at) VALUES (?, ?, ?, ?)",
        (title, filename, session["username"], datetime.now().strftime("%Y-%m-%d %H:%M")),
    )
    db.commit()

    flash("Paper uploaded successfully!", "success")
    # ✅ VERY IMPORTANT: redirect to dashboard, NOT to /upload_paper
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
    db.execute("UPDATE papers SET title=? WHERE id=?", (new_title, paper_id))
    db.commit()

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
    row = db.execute("SELECT filename FROM papers WHERE id=?", (paper_id,)).fetchone()

    if row:
        filepath = os.path.join(PAPERS_FOLDER, row["filename"])
        if os.path.exists(filepath):
            os.remove(filepath)

    # Delete all solutions belonging to this paper
    sol = db.execute("SELECT filename FROM solutions WHERE paper_id=?", (paper_id,)).fetchall()
    for s in sol:
        f = os.path.join(SOLUTIONS_FOLDER, s["filename"])
        if os.path.exists(f):
            os.remove(f)

    db.execute("DELETE FROM solutions WHERE paper_id=?", (paper_id,))
    db.execute("DELETE FROM papers WHERE id=?", (paper_id,))
    db.commit()

    flash("Paper and all related solutions deleted!", "success")
    return redirect(url_for("teacher_dashboard"))


# ============================================================
#             STUDENT — UPLOAD SOLUTION (MULTIPLE FILES)
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

    # ---------- ONE-TIME SUBMISSION CHECK ----------
    existing = db.execute(
        """
        SELECT COUNT(*) AS c
        FROM solutions
        WHERE student_username = ? AND paper_id = ?
        """,
        (session["username"], paper_id),
    ).fetchone()["c"]

    if existing > 0:
        flash("You have already submitted a solution for this paper. You cannot submit again.", "warning")
        return redirect(url_for("student_dashboard"))

    # ---------- VALIDATE FILES ----------
    if not files or all(not f.filename for f in files):
        flash("Please select at least one JPG/PNG file.", "warning")
        return redirect(url_for("student_dashboard"))

    group_id = str(uuid.uuid4())  # ONE GROUP for this submission
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

        f.save(os.path.join(SOLUTIONS_FOLDER, fname))

        # Every page goes into the same submission_group
        db.execute(
            """
            INSERT INTO solutions
              (paper_id, student_username, filename, submitted_at, submission_group)
            VALUES (?, ?, ?, ?, ?)
            """,
            (paper_id, session["username"], fname, now_str, group_id),
        )

    db.commit()
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

    # All pages in this submission group
    rows = db.execute(
        "SELECT * FROM solutions WHERE submission_group = ? ORDER BY id",
        (group_id,),
    ).fetchall()

    if not rows:
        abort(404)

    first = rows[0]
    files = [r["filename"] for r in rows]

    # Paper + student info
    paper = db.execute(
        "SELECT title FROM papers WHERE id = ?",
        (first["paper_id"],),
    ).fetchone()
    student = db.execute(
        "SELECT name, username FROM users WHERE username = ?",
        (first["student_username"],),
    ).fetchone()

    # 1-based page index
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

@app.route("/view_solution/<filename>")
def view_solution(filename):
    return send_from_directory(SOLUTIONS_FOLDER, filename)

# ============================================================
#                    TEACHER — GRADE SOLUTION
# ============================================================

@app.route("/grade_solution", methods=["POST"])
@login_required(role="teacher")
def grade_solution():
    db = get_db()

    group_id = request.form.get("group_id")

    # Safely parse numeric fields (default 0 if empty)
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

    # PASS / FAIL based on marks
    status = "PASS" if obtained_marks >= passing_marks else "FAIL"

    # 🔴 IMPORTANT: update obtained_marks for ALL rows in this submission_group
    db.execute(
        """
        UPDATE solutions
        SET total_questions = ?,
            attempted       = ?,
            correct         = ?,
            incorrect       = ?,
            total_marks     = ?,
            obtained_marks  = ?,
            passing_marks   = ?,
            result_status   = ?
        WHERE submission_group = ?
        """,
        (
            total_questions,
            attempted,
            correct,
            incorrect,
            total_marks,
            obtained_marks,
            passing_marks,
            status,
            group_id,
        ),
    )

    db.commit()
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

    # All papers
    papers = db.execute(
        "SELECT id, title, filename, uploaded_at FROM papers ORDER BY id DESC"
    ).fetchall()

    # All submissions by this student (grouped by submission_group)
    solutions_rows = db.execute(
        """
        SELECT
            s.submission_group,
            s.paper_id,
            MIN(s.submitted_at)           AS submitted_at,
            MAX(s.obtained_marks)         AS obtained_marks,
            MAX(s.result_status)          AS result_status
        FROM solutions s
        WHERE s.student_username = ?
        GROUP BY s.submission_group, s.paper_id
        ORDER BY submitted_at DESC
        """,
        (session["username"],),
    ).fetchall()

    # Paper ids already submitted by this student
    submitted_ids = {row["paper_id"] for row in solutions_rows}

    # Papers still available for this student
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

    rows = db.execute("""
        SELECT s.*, p.title AS paper_title
        FROM solutions s
        JOIN papers p ON p.id = s.paper_id
        WHERE s.student_username=?
        GROUP BY s.submission_group
        ORDER BY submitted_at DESC
    """, (session["username"],)).fetchall()

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

        # --- Update name ---
        if new_name:
            db.execute("""
                UPDATE users SET name=? WHERE username=?
            """, (new_name, old_username))

        # --- Update username safely (no duplicates) ---
        if new_username and new_username != old_username:

            exists = db.execute("""
                SELECT 1 FROM users WHERE username=?
            """, (new_username,)).fetchone()

            if exists:
                flash("Username is already taken!", "danger")
                return redirect(url_for("student_profile"))

            # Update in users table
            db.execute("""
                UPDATE users SET username=? WHERE username=?
            """, (new_username, old_username))

            # Update in solutions table
            db.execute("""
                UPDATE solutions SET student_username=?
                WHERE student_username=?
            """, (new_username, old_username))

            session["username"] = new_username
            old_username = new_username

        # --- Update password ---
        if password:
            if password != confirm:
                flash("Passwords do not match!", "danger")
                return redirect(url_for("student_profile"))
            db.execute("""
                UPDATE users SET password=? WHERE username=?
            """, (password, old_username))

        # --- Update profile picture ---
        if avatar and avatar.filename:
            ext = avatar.filename.rsplit(".", 1)[-1].lower()
            if ext not in {"jpg", "jpeg", "png"}:
                flash("Invalid image file!", "danger")
                return redirect(url_for("student_profile"))

            safe = secure_filename(avatar.filename)
            fname = f"avatar_{old_username}_{uuid.uuid4().hex[:6]}.{ext}"

            avatar.save(os.path.join(AVATAR_FOLDER, fname))

            db.execute("""
                UPDATE users SET profile_pic=? WHERE username=?
            """, (fname, old_username))

        db.commit()
        flash("Profile updated successfully!", "success")
        return redirect(url_for("student_profile"))

    # GET REQUEST — Load details
    row = db.execute("""
        SELECT username, name, profile_pic
        FROM users WHERE username=?
    """, (old_username,)).fetchone()

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

    avg_students = db.execute("""
        SELECT u.name, u.username, AVG(s.obtained_marks) AS avg
        FROM users u
        LEFT JOIN solutions s ON u.username = s.student_username
        WHERE u.role='student'
        GROUP BY u.username
    """).fetchall()

    avg_papers = db.execute("""
        SELECT p.title, AVG(s.obtained_marks) AS avg
        FROM papers p
        LEFT JOIN solutions s ON s.paper_id = p.id
        GROUP BY p.id
    """).fetchall()

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

    # Fetch one row only (all rows for same group share same marks & metadata)
    row = db.execute("""
        SELECT * FROM solutions
        WHERE submission_group=?
        LIMIT 1
    """, (group_id,)).fetchone()

    if not row:
        flash("Submission not found.", "danger")
        return redirect(url_for("student_results"))

    # If not graded → prevent download
    if not row["obtained_marks"]:
        flash("Report will be available only after teacher grading.", "warning")
        return redirect(url_for("student_results"))

    # Fetch paper and student details
    paper = db.execute(
        "SELECT title FROM papers WHERE id=?",
        (row["paper_id"],)
    ).fetchone()

    student = db.execute(
        "SELECT name FROM users WHERE username=?",
        (row["student_username"],)
    ).fetchone()

    # File name & path
    filename = f"report_{group_id}.pdf"
    path = os.path.join(REPORTS_FOLDER, filename)

    # ============== BUILD PDF ==============

    doc = SimpleDocTemplate(path, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    # -- Header --
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

    # -- Student Info Table --
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

    # -- Result Table --
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

    # Return as file download
    return send_from_directory(REPORTS_FOLDER, filename, as_attachment=True)


# ============================================================
#                   DOWNLOAD PAPER (PDF)
# ============================================================

@app.route("/download_paper/<filename>")
def download_paper(filename):
    return send_from_directory(PAPERS_FOLDER, filename)


# ============================================================
#                        RUN APPLICATION
# ============================================================

if __name__ == "__main__":
    with app.app_context():
        init_db()

    port = int(os.environ.get("PORT", 10000))   # Render uses PORT env var, local default 10000
    app.run(host="0.0.0.0", port=port)
