# ==================================================
# SAFE BASELINE app.py (Render + PostgreSQL friendly)
# ==================================================

from flask import Flask, render_template, request, redirect, session
import os
import psycopg2
from psycopg2.extras import RealDictCursor

# ---------------- BASIC CONFIG ----------------

DATABASE_URL = os.getenv("DATABASE_URL")
FLASK_SECRET = os.getenv("FLASK_SECRET", "dev-secret")

# Fixed single course
COURSE_ID = 1
COURSE_TITLE = "Your Course Name"
COURSE_INSTRUCTOR = "Instructor"
COURSE_DESCRIPTION = "Course description"

# ---------------- APP ----------------

app = Flask(__name__)
app.secret_key = FLASK_SECRET

# ---------------- DATABASE ----------------

def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")

    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        connect_timeout=5
    )


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY,
            title TEXT,
            instructor TEXT,
            description TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            name TEXT,
            email TEXT UNIQUE
        );
    """)

    # Ensure fixed course exists / updates
    cur.execute(
        """
        INSERT INTO courses (id, title, instructor, description)
        VALUES (%s,%s,%s,%s)
        ON CONFLICT (id) DO UPDATE SET
            title = EXCLUDED.title,
            instructor = EXCLUDED.instructor,
            description = EXCLUDED.description
        """,
        (COURSE_ID, COURSE_TITLE, COURSE_INSTRUCTOR, COURSE_DESCRIPTION)
    )

    conn.commit()
    cur.close()
    conn.close()


with app.app_context():
    init_db()

# ---------------- CONTEXT ----------------

@app.context_processor
def inject_course():
    return {
        "course": {
            "title": COURSE_TITLE,
            "instructor": COURSE_INSTRUCTOR,
            "description": COURSE_DESCRIPTION,
        }
    }

# ---------------- ROUTES ----------------

@app.route("/")
def index():
    return redirect("/course")


@app.route("/course")
def course_page():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM courses WHERE id=%s", (COURSE_ID,))
    course = cur.fetchone()

    cur.close()
    conn.close()

    if not course:
        return "Course not found", 500

    return render_template("course_page.html", course=course)


@app.route("/student/register", methods=["GET", "POST"])
def student_register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT 1 FROM students WHERE email=%s", (email,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO students (name, email) VALUES (%s,%s)",
                (name, email)
            )
            conn.commit()

        cur.close()
        conn.close()
        return redirect("/course")

    return render_template("student_register.html")


@app.route("/health")
def health():
    try:
        conn = get_db()
        conn.close()
        return "OK"
    except Exception as e:
        return str(e), 500


# ===============================
# ADD INSTRUCTOR LOGIN (SAFE)
# ===============================

from werkzeug.security import check_password_hash

INSTRUCTOR_USERNAME = os.getenv("INSTRUCTOR_USERNAME")
INSTRUCTOR_PASSWORD_HASH = os.getenv("INSTRUCTOR_PASSWORD_HASH")

@app.route("/login", methods=["GET", "POST"])
def instructor_login():
    if request.method == "POST":
        if not INSTRUCTOR_USERNAME or not INSTRUCTOR_PASSWORD_HASH:
            return "Instructor credentials not configured", 500

        username = request.form.get("username")
        password = request.form.get("password")

        if username == INSTRUCTOR_USERNAME and check_password_hash(INSTRUCTOR_PASSWORD_HASH, password):
            session["instructor"] = True
            return redirect("/course")

        return "Invalid credentials", 401

    return render_template("login.html")


@app.route("/logout")
def instructor_logout():
    session.pop("instructor", None)
    return redirect("/course")
