# --- Fully fixed app.py (SQLite -> PostgreSQL safe) ---

from flask import Flask, render_template, request, redirect, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

# ---------------- CONFIG ----------------

DATABASE_URL = os.getenv("DATABASE_URL")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL", "onboarding@resend.dev")

INSTRUCTOR_USERNAME = os.getenv("INSTRUCTOR_USERNAME")
INSTRUCTOR_PASSWORD_HASH = os.getenv("INSTRUCTOR_PASSWORD_HASH")

UPLOAD_FOLDER = "uploads"
LECTURE_FOLDER = os.path.join(UPLOAD_FOLDER, "lectures")
ASSIGNMENT_FOLDER = os.path.join(UPLOAD_FOLDER, "assignments")

os.makedirs(LECTURE_FOLDER, exist_ok=True)
os.makedirs(ASSIGNMENT_FOLDER, exist_ok=True)

# ---------------- APP ----------------

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "change-me")

# ---------------- DB ----------------

def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        sslmode="require"
    )


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS courses (
        id SERIAL PRIMARY KEY,
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
        email TEXT,
        course_id INTEGER REFERENCES courses(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS lectures (
        id SERIAL PRIMARY KEY,
        title TEXT,
        filename TEXT,
        course_id INTEGER REFERENCES courses(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS assignments (
        id SERIAL PRIMARY KEY,
        title TEXT,
        filename TEXT,
        due_date TEXT,
        course_id INTEGER REFERENCES courses(id)
    );
    """)

    conn.commit()
    cur.close()
    conn.close()


with app.app_context():
    init_db()

# ---------------- EMAIL ----------------

def send_email(to_email, subject, body):
    try:
        if not RESEND_API_KEY:
            print("Email disabled")
            return

        r = requests.post(
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
            timeout=10,
        )

        if r.status_code >= 400:
            print("Email error:", r.text)
    except Exception as e:
        print("Email exception:", e)

# ---------------- ROUTES ----------------

@app.route("/")
def index():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM courses ORDER BY id DESC")
    courses = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("index.html", courses=courses)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if (
            request.form["username"] == INSTRUCTOR_USERNAME
            and check_password_hash(INSTRUCTOR_PASSWORD_HASH, request.form["password"])
        ):
            session["instructor"] = True
            return redirect("/instructor/dashboard")
        return "Invalid credentials", 401
    return render_template("login.html")


@app.route("/logout")
def instructor_logout():
    session.pop("instructor", None)
    return redirect("/")


@app.route("/instructor/dashboard")
def instructor_dashboard():
    if not session.get("instructor"):
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM courses")
    courses = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("instructor_dashboard.html", courses=courses)


@app.route("/add", methods=["GET", "POST"])
def add_course():
    if not session.get("instructor"):
        return redirect("/login")

    if request.method == "POST":
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO courses (title, instructor, description, submission_url)
            VALUES (%s, %s, %s, %s)
            """,
            (
                request.form["title"],
                request.form["instructor"],
                request.form["description"],
                request.form["submission_url"],
            ),
        )

        conn.commit()
        cur.close()
        conn.close()
        return redirect("/instructor/dashboard")

    return render_template("add_course.html")


@app.route("/add_lecture/<int:course_id>", methods=["GET", "POST"])
def add_lecture(course_id):
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
            """
            INSERT INTO lectures (title, filename, course_id)
            VALUES (%s, %s, %s)
            """,
            (title, filename, course_id)
        )

        conn.commit()
        cur.close()
        conn.close()

        return redirect(f"/course/{course_id}")

    return render_template("add_lecture.html")


@app.route("/add_assignment/<int:course_id>", methods=["GET", "POST"])
def add_assignment(course_id):
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
            """
            INSERT INTO assignments (title, filename, due_date, course_id)
            VALUES (%s, %s, %s, %s)
            """,
            (title, filename, due_date, course_id)
        )

        conn.commit()
        cur.close()
        conn.close()

        return redirect(f"/course/{course_id}")

    return render_template("add_assignment.html")




@app.route("/delete/<int:course_id>", methods=["POST"])
def delete_course(course_id):
    if not session.get("instructor"):
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM courses WHERE id=%s", (course_id,))
    conn.commit()
    cur.close()
    conn.close()

    return redirect("/instructor/dashboard")


@app.route("/course/<int:course_id>")
def course_page(course_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM courses WHERE id=%s", (course_id,))
    course = cur.fetchone()
    if not course:
        cur.close()
        conn.close()
        return "Course not found", 404

    if not session.get("instructor") and not session.get("student_id"):
        return redirect("/student/login")

    cur.execute("SELECT * FROM lectures WHERE course_id=%s", (course_id,))
    lectures = cur.fetchall()

    cur.execute("SELECT * FROM assignments WHERE course_id=%s", (course_id,))
    assignments = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "course_page.html",
        course=course,
        lectures=lectures,
        assignments=assignments,
    )


@app.route("/download/lecture/<filename>")
def download_lecture(filename):
    return send_from_directory(LECTURE_FOLDER, filename)


@app.route("/download/assignment/<filename>")
def download_assignment(filename):
    return send_from_directory(ASSIGNMENT_FOLDER, filename)

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
        return redirect("/student/dashboard")

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
            return redirect("/student/dashboard")

        cur.close()
        conn.close()
        return "Invalid login"

    return render_template("student_login.html")


@app.route("/student/logout")
def student_logout():
    session.pop("student_id", None)
    session.pop("student_name", None)
    return redirect("/")


@app.route("/student/dashboard")
def student_dashboard():
    if not session.get("student_id"):
        return redirect("/student/login")

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT c.* FROM courses c
        JOIN enrollments e ON c.id = e.course_id
        WHERE e.email = (
            SELECT email FROM students WHERE id=%s
        )
        """,
        (session["student_id"],),
    )

    courses = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("student_dashboard.html", courses=courses)


@app.route("/enroll/<int:course_id>")
def enroll(course_id):
    if not session.get("student_id"):
        return redirect("/student/login")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT email, name FROM students WHERE id=%s", (session["student_id"],))
    student = cur.fetchone()

    cur.execute(
        "SELECT 1 FROM enrollments WHERE email=%s AND course_id=%s",
        (student["email"], course_id),
    )
    if cur.fetchone():
        cur.close()
        conn.close()
        return redirect(f"/course/{course_id}")

    cur.execute(
        "INSERT INTO enrollments (student_name, email, course_id) VALUES (%s,%s,%s)",
        (student["name"], student["email"], course_id),
    )

    conn.commit()
    cur.close()
    conn.close()

    send_email(
        student["email"],
        "Enrollment Confirmed",
        "You are now enrolled in the course.",
    )

    return redirect(f"/course/{course_id}")

@app.route("/admin/clear_students", methods=["POST"])
def clear_students():
    if not session.get("instructor"):
        return "Unauthorized", 403

    conn = get_db()
    cur = conn.cursor()
    cur.execute("TRUNCATE enrollments, students RESTART IDENTITY CASCADE;")
    conn.commit()
    cur.close()
    conn.close()

    return "All student data cleared"
