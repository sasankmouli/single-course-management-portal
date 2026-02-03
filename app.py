# ===============================
# Single-Course Portal – Final app.py
# ===============================

from flask import Flask, render_template, request, redirect, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import requests

# ---------------- CONFIG ----------------

DATABASE_URL = os.getenv("DATABASE_URL")
FLASK_SECRET = os.getenv("FLASK_SECRET", "change-me")

INSTRUCTOR_USERNAME = os.getenv("INSTRUCTOR_USERNAME")
INSTRUCTOR_PASSWORD_HASH = os.getenv("INSTRUCTOR_PASSWORD_HASH")

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL", "onboarding@resend.dev")

# Fixed course metadata
COURSE_ID = 1
COURSE_TITLE = "CS202 – Automata theory and logic - Spring 2026"
COURSE_INSTRUCTOR = "Sasank Mouli"
COURSE_DESCRIPTION = "Textbook: Theory of Computation by Michael Sipser"
COURSE_SUBMISSION_URL = "https://docs.google.com/forms/d/1RmmB-k_0BSgqB-yDQmKAQ4MThkwEJeEVdc7V9tvAnWI/edit?usp=drivesdk"

UPLOAD_FOLDER = "uploads"
LECTURE_FOLDER = os.path.join(UPLOAD_FOLDER, "lectures")
ASSIGNMENT_FOLDER = os.path.join(UPLOAD_FOLDER, "assignments")

os.makedirs(LECTURE_FOLDER, exist_ok=True)
os.makedirs(ASSIGNMENT_FOLDER, exist_ok=True)

# ---------------- APP ----------------

app = Flask(__name__)
app.secret_key = FLASK_SECRET
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2MB

# ---------------- DB ----------------

def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        sslmode="require",
        connect_timeout=5,
    )


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY,
        title TEXT,
        instructor TEXT,
        description TEXT,
        submission_url TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id SERIAL PRIMARY KEY,
        name TEXT,
        email TEXT UNIQUE,
        password TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS enrollments (
        id SERIAL PRIMARY KEY,
        student_name TEXT,
        email TEXT UNIQUE,
        course_id INTEGER
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS lectures (
        id SERIAL PRIMARY KEY,
        title TEXT,
        filename TEXT,
        course_id INTEGER
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS assignments (
        id SERIAL PRIMARY KEY,
        title TEXT,
        filename TEXT,
        due_date TEXT,
        course_id INTEGER
    );
    """)

    # Ensure fixed course exists
    cur.execute("SELECT id FROM courses WHERE id=%s", (COURSE_ID,))
    if not cur.fetchone():
        cur.execute(
            """
            INSERT INTO courses (id, title, instructor, description, submission_url)
            VALUES (%s,%s,%s,%s,%s)
            """,
            (
                COURSE_ID,
                COURSE_TITLE,
                COURSE_INSTRUCTOR,
                COURSE_DESCRIPTION,
                COURSE_SUBMISSION_URL,
            ),
        )

    conn.commit()
    cur.close()
    conn.close()


with app.app_context():
    init_db()

# ---------------- EMAIL ----------------

def send_email(to_email, subject, body):
    if not RESEND_API_KEY:
        return
    try:
        requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": subject,
                "text": body,
            },
            timeout=5,
        )
    except Exception:
        pass

# ---------------- ROUTES ----------------

@app.route("/")
def index():
    return redirect("/course")


@app.route("/login", methods=["GET", "POST"])
def instructor_login():
    if request.method == "POST":
        if (
            request.form["username"] == INSTRUCTOR_USERNAME
            and check_password_hash(INSTRUCTOR_PASSWORD_HASH, request.form["password"])
        ):
            session["instructor"] = True
            return redirect("/course")
        return "Invalid credentials", 401
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/course")
def course_page():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM courses WHERE id=%s", (COURSE_ID,))
    course = cur.fetchone()

    cur.execute("SELECT * FROM lectures WHERE course_id=%s", (COURSE_ID,))
    lectures = cur.fetchall()

    cur.execute("SELECT * FROM assignments WHERE course_id=%s", (COURSE_ID,))
    assignments = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "course_page.html",
        course=course,
        lectures=lectures,
        assignments=assignments,
    )


@app.route("/enroll", methods=["POST"])
def enroll():
    if not session.get("student_id"):
        return redirect("/student/login")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT name, email FROM students WHERE id=%s", (session["student_id"],))
    student = cur.fetchone()

    cur.execute("SELECT 1 FROM enrollments WHERE email=%s", (student["email"],))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO enrollments (student_name, email, course_id) VALUES (%s,%s,%s)",
            (student["name"], student["email"], COURSE_ID),
        )
        conn.commit()

        send_email(
            student["email"],
            "Enrollment Confirmed",
            f"You are enrolled in {COURSE_TITLE}.",
        )

    cur.close()
    conn.close()
    return redirect("/course")

# ---------------- INSTRUCTOR UPLOADS ----------------

@app.route("/add_lecture", methods=["GET", "POST"])
def add_lecture():
    if not session.get("instructor"):
        return redirect("/login")

    if request.method == "POST":
        title = request.form["title"]
        file = request.files["file"]

        filename = secure_filename(file.filename)
        file.save(os.path.join(LECTURE_FOLDER, filename))

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO lectures (title, filename, course_id) VALUES (%s,%s,%s)",
            (title, filename, COURSE_ID),
        )
        conn.commit()
        cur.close()
        conn.close()

        return redirect("/course")

    return render_template("add_lecture.html")


@app.route("/add_assignment", methods=["GET", "POST"])
def add_assignment():
    if not session.get("instructor"):
        return redirect("/login")

    if request.method == "POST":
        title = request.form["title"]
        due_date = request.form["due_date"]
        file = request.files["file"]

        filename = secure_filename(file.filename)
        file.save(os.path.join(ASSIGNMENT_FOLDER, filename))

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO assignments (title, filename, due_date, course_id) VALUES (%s,%s,%s,%s)",
            (title, filename, due_date, COURSE_ID),
        )
        conn.commit()
        cur.close()
        conn.close()

        return redirect("/course")

    return render_template("add_assignment.html")

# ---------------- STUDENTS ----------------

@app.route("/student/register", methods=["GET", "POST"])
def student_register():
    if request.method == "POST":
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO students (name, email, password) VALUES (%s,%s,%s)",
                (
                    request.form["name"],
                    request.form["email"],
                    generate_password_hash(request.form["password"]),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            cur.close()
            conn.close()
            return "Email already registered"

        cur.execute("SELECT id, name FROM students WHERE email=%s", (request.form["email"],))
        student = cur.fetchone()
        session["student_id"] = student["id"]
        session["student_name"] = student["name"]

        cur.close()
        conn.close()
        return redirect("/course")

    return render_template("student_register.html")


@app.route("/student/login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM students WHERE email=%s", (request.form["email"],))
        student = cur.fetchone()

        if student and check_password_hash(student["password"], request.form["password"]):
            session["student_id"] = student["id"]
            session["student_name"] = student["name"]
            cur.close()
            conn.close()
            return redirect("/course")

        cur.close()
        conn.close()
        return "Invalid login"

    return render_template("student_login.html")


@app.route("/student/logout")
def student_logout():
    session.clear()
    return redirect("/")

# ---------------- DOWNLOADS ----------------

@app.route("/download/lecture/<filename>")
def download_lecture(filename):
    return send_from_directory(LECTURE_FOLDER, filename)


@app.route("/download/assignment/<filename>")
def download_assignment(filename):
    return send_from_directory(ASSIGNMENT_FOLDER, filename)
