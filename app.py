# ==================================================
# SAFE BASELINE app.py (Render + PostgreSQL friendly)
# ==================================================

from flask import Flask, render_template, request, redirect, session
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import send_from_directory
from werkzeug.utils import secure_filename



# ---------------- BASIC CONFIG ----------------

DATABASE_URL = os.getenv("DATABASE_URL")
FLASK_SECRET = os.getenv("FLASK_SECRET", "dev-secret")

# Fixed single course
COURSE_ID = 1
COURSE_TITLE = "Your Course Name"
COURSE_INSTRUCTOR = "Instructor"
COURSE_DESCRIPTION = "Course description"

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL")  # e.g. course@yourdomain.edu


# ---------------- APP ----------------

app = Flask(__name__)
app.secret_key = FLASK_SECRET

UPLOAD_FOLDER = os.path.join(app.root_path, "uploads")
LECTURE_FOLDER = os.path.join(UPLOAD_FOLDER, "lectures")
ASSIGNMENT_FOLDER = os.path.join(UPLOAD_FOLDER, "assignments")

os.makedirs(LECTURE_FOLDER, exist_ok=True)
os.makedirs(ASSIGNMENT_FOLDER, exist_ok=True)


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

    cur.execute("SELECT * FROM lectures WHERE course_id=%s ORDER BY id DESC", (COURSE_ID,))
    lectures = cur.fetchall()

    cur.close()
    conn.close()

    if not course:
        return "Course not found", 500

    return render_template(
        "course_page.html",
        course=course,
        lectures=lectures,
    )


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
            send_email(
                email,
                "Registration confirmed",
                f"You’ll now receive updates for {COURSE_TITLE}."
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




UPLOAD_FOLDER = "uploads"
LECTURE_FOLDER = os.path.join(UPLOAD_FOLDER, "lectures")
os.makedirs(LECTURE_FOLDER, exist_ok=True)





@app.route("/add_lecture", methods=["GET", "POST"])
def add_lecture():
    if not session.get("instructor"):
        return redirect("/login")

    if request.method == "POST":
        title = request.form["title"]
        file = request.files["file"]

        if not file or file.filename == "":
            return "No file selected", 400

        filename = secure_filename(file.filename)
        save_path = os.path.join(LECTURE_FOLDER, filename)
        file.save(save_path)

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO lectures (title, filename, course_id) VALUES (%s,%s,%s)",
            (title, filename, COURSE_ID)
        )
        conn.commit()
        for email in get_student_emails():
            send_email(
                email,
                "New lecture uploaded",
                f"A new lecture has been added to {COURSE_TITLE}.\n\nPlease visit the course page to download it."
            )
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

        if not file or file.filename == "":
            return "No file selected", 400

        filename = secure_filename(file.filename)
        file.save(os.path.join(ASSIGNMENT_FOLDER, filename))

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO assignments (title, filename, due_date, course_id) VALUES (%s,%s,%s,%s)",
            (title, filename, due_date, COURSE_ID)
        )
        conn.commit()
        cur.close()
        conn.close()

        # 🔔 Email notification (final step)
        for email in get_student_emails():
            send_email(
                email,
                "New assignment posted",
                f"A new assignment has been posted for {COURSE_TITLE}.\n\nPlease check the course page."
            )

        return redirect("/course")

    return render_template("add_assignment.html")


@app.route("/download/lecture/<filename>")
def download_lecture(filename):
    return send_from_directory(LECTURE_FOLDER, filename, as_attachment=True)

@app.route("/download/assignment/<filename>")
def download_assignment(filename):
    return send_from_directory(
        ASSIGNMENT_FOLDER,
        filename,
        as_attachment=True
    )




@app.route("/logout")
def instructor_logout():
    session.pop("instructor", None)
    return redirect("/course")

@app.route("/admin/clear_lectures", methods=["POST"])
def clear_lectures():
    if not session.get("instructor"):
        return "Unauthorized", 403

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM lectures")
    conn.commit()
    cur.close()
    conn.close()
    return "Lectures cleared"

def send_email(to_email, subject, body):
    if not RESEND_API_KEY or not FROM_EMAIL:
        print("Email disabled (missing config)")
        return

    try:
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
            timeout=5,
        )

        if r.status_code >= 400:
            print("Email error:", r.text)

    except Exception as e:
        # CRITICAL: never crash the request
        print("Email exception:", e)


def get_student_emails():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT email FROM students")
    emails = [row["email"] for row in cur.fetchall()]

    cur.close()
    conn.close()
    return emails


