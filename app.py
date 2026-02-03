from flask import Flask, render_template, request, redirect, session
from flask import send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import smtplib
import os
from werkzeug.utils import secure_filename
from email.message import EmailMessage
import requests

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
FROM_EMAIL = "noreply@sasankmouli.com"  # default works


app = Flask(__name__)

app.secret_key = "DheerajSanghiMoodleDoodle2"



UPLOAD_FOLDER = "uploads"
LECTURE_FOLDER = os.path.join(UPLOAD_FOLDER, "lectures")
ASSIGNMENT_FOLDER = os.path.join(UPLOAD_FOLDER, "assignments")

os.makedirs(LECTURE_FOLDER, exist_ok=True)
os.makedirs(ASSIGNMENT_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


DB = "courses.db"

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_PASS = os.getenv("ADMIN_PASS")

INSTRUCTOR_USERNAME = os.getenv("INSTRUCTOR_USERNAME")
INSTRUCTOR_PASSWORD_HASH = os.getenv("INSTRUCTOR_PASSWORD_HASH")

def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        sslmode="require"
    )



def get_enrolled_emails(course_id):
    conn = get_db()
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT DISTINCT email FROM enrollments WHERE course_id=?",
        (course_id,)
    ).fetchall()
    conn.close()

    return [r[0] for r in rows]


def send_email(to_email, subject, body):
    try:
        if not RESEND_API_KEY:
            print("Resend not configured; skipping email.")
            return

        response = requests.post(
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
            timeout=10
        )

        if response.status_code >= 400:
            print("Resend error:", response.text)
        else:
            print(f"Email sent to {to_email}")

    except Exception as e:
        print("Email exception:", e)


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
    conn.close()



@app.route("/")
def index():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM courses")
    courses = cur.fetchall()
    conn.close()
    return render_template("index.html", courses=courses)


# ---------- ADD COURSE ----------
@app.route("/add", methods=["GET", "POST"])
def add_course():
    if not session.get("instructor"):
        return redirect("/login")

    if request.method == "POST":
        title = request.form["title"]
        instructor = request.form["instructor"]
        description = request.form["description"]
        submission_url = request.form["submission_url"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO courses (title, instructor, description, submission_url)
            VALUES (?,?,?,?)
            """,
            (title, instructor, description, submission_url)
        )
        conn.commit()
        conn.close()

        return redirect("/")

    return render_template("add_course.html")



# ---------- ENROLL ----------
@app.route("/enroll/<int:course_id>", methods=["GET", "POST"])
def enroll(course_id):
    # 🚫 Must be logged in as student
    if not session.get("student_id"):
        return redirect("/student/login")

    conn = get_db()
    cur = conn.cursor()

    # Get student email
    student = cur.execute(
        "SELECT email, name FROM students WHERE id=?",
        (session["student_id"],)
    ).fetchone()

    if not student:
        conn.close()
        return redirect("/student/login")

    email, name = student

    # Prevent duplicate enrollment
    already = cur.execute("""
        SELECT 1 FROM enrollments
        WHERE email=? AND course_id=?
    """, (email, course_id)).fetchone()

    if already:
        conn.close()
        return redirect(f"/course/{course_id}")

    # Enroll
    cur.execute(
        "INSERT INTO enrollments (student_name, email, course_id) VALUES (?,?,?)",
        (name, email, course_id)
    )

    # Get course name for email
    course = cur.execute(
        "SELECT title FROM courses WHERE id=?",
        (course_id,)
    ).fetchone()

    conn.commit()
    conn.close()

    course_name = course[0] if course else "your course"

    send_email(
        email,
        "Enrollment Confirmed",
        f"Hi {name},\n\n"
        f"You are now enrolled in:\n"
        f"📘 {course_name}\n\n"
        f"Good luck!"
    )

    # ✅ Redirect to course page
    return redirect(f"/course/{course_id}")


# ---------- DELETE COURSE ----------
@app.route("/delete/<int:course_id>", methods=["POST"])
def delete_course(course_id):
    if not session.get("instructor"):
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM courses WHERE id=?", (course_id,))
    conn.commit()
    conn.close()

    return redirect("/")


# ---------- ADD ASSIGNMENT ----------
@app.route("/add_assignment/<int:course_id>", methods=["GET", "POST"])
def add_assignment(course_id):
    if not instructor_required():
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
            "INSERT INTO assignments (title, filename, due_date, course_id) VALUES (?,?,?,?)",
            (title, filename, due_date, course_id)
        )
        conn.commit()
        conn.close()

        emails = get_enrolled_emails(course_id)
        for email in emails:
            send_email(
                email,
                "New Assignment Posted",
                f"A new assignment \"{title}\" has been posted.\n\n"
                f"Due date: {due_date}\n\n"
                f"Log in to the portal to view details."
            )

        return redirect(f"/course/{course_id}")

    return render_template("add_assignment.html", course_id=course_id)



# ---------- ADD LECTURES ----------
@app.route("/add_lecture/<int:course_id>", methods=["GET", "POST"])
def add_lecture(course_id):
    if not instructor_required():
        return redirect("/login")
    if request.method == "POST":
        title = request.form["title"]
        file = request.files["file"]

        filename = secure_filename(file.filename)
        file.save(os.path.join(LECTURE_FOLDER, filename))

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO lectures (title, filename, course_id) VALUES (?,?,?)",
            (title, filename, course_id)
        )
        conn.commit()
        conn.close()

        # 📧 Notify students
        emails = get_enrolled_emails(course_id)
        for email in emails:
            send_email(
                email,
                "New Lecture Added",
                f"A new lecture \"{title}\" has been added to your course.\n\n"
                f"Log in to the portal to view it."
            )

        return redirect(f"/course/{course_id}")

    return render_template("add_lecture.html", course_id=course_id)


@app.route("/download/lecture/<filename>")
def download_lecture(filename):
    return send_from_directory(LECTURE_FOLDER, filename)

@app.route("/download/assignment/<filename>")
def download_assignment(filename):
    return send_from_directory(ASSIGNMENT_FOLDER, filename)


@app.route("/login", methods=["GET", "POST"])
def instructor_login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username == INSTRUCTOR_USERNAME and check_password_hash(INSTRUCTOR_PASSWORD_HASH, password):
            session["instructor"] = True
            return redirect("/instructor/dashboard")
        else:
            return "Invalid credentials", 401

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("instructor", None)
    return redirect("/")


@app.route("/course/<int:course_id>")
def course_page(course_id):
    conn = get_db()
    cur = conn.cursor()

    # Fetch course
    course = cur.execute(
        "SELECT * FROM courses WHERE id=?",
        (course_id,)
    ).fetchone()

    if not course:
        conn.close()
        return "Course not found", 404

    # ✅ Instructor can always access
    if session.get("instructor"):
        allowed = True

    # ✅ Student access check
    elif session.get("student_id"):
        enrolled = cur.execute("""
            SELECT 1 FROM enrollments
            WHERE course_id=?
              AND email = (
                  SELECT email FROM students WHERE id=?
              )
        """, (course_id, session["student_id"])).fetchone()

        allowed = enrolled is not None

    else:
        allowed = False

    # ❌ Not allowed → redirect
    if not allowed:
        conn.close()
        return "You are not enrolled in this course.", 403


    # Fetch resources
    lectures = cur.execute(
        "SELECT * FROM lectures WHERE course_id=?",
        (course_id,)
    ).fetchall()

    assignments = cur.execute(
        "SELECT * FROM assignments WHERE course_id=?",
        (course_id,)
    ).fetchall()

    conn.close()

    return render_template(
        "course_page.html",
        course=course,
        lectures=lectures,
        assignments=assignments
    )

@app.route("/student/register", methods=["GET", "POST"])
def student_register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])

        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO students (name, email, password) VALUES (?,?,?)",
                (name, email, password)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return "Email already registered"

        # Log student in immediately
        student_id = cur.execute(
            "SELECT id FROM students WHERE email=?",
            (email,)
        ).fetchone()[0]

        conn.close()

        session["student_id"] = student_id
        session["student_name"] = name

        return redirect("/student/dashboard")

    return render_template("student_register.html")

@app.route("/student/login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = get_db()
        cur = conn.cursor()
        student = cur.execute(
            "SELECT id, name, password FROM students WHERE email=?",
            (email,)
        ).fetchone()
        conn.close()

        if student and check_password_hash(student[2], password):
            session["student_id"] = student[0]
            session["student_name"] = student[1]
            return redirect("/student/dashboard")

        return "Invalid login"

    return render_template("student_login.html")

@app.route("/student/dashboard")
def student_dashboard():
    if not session.get("student_id"):
        return redirect("/student/login")

    conn = get_db()
    cur = conn.cursor()

    courses = cur.execute("""
        SELECT courses.id, courses.title, courses.instructor
        FROM courses
        JOIN enrollments ON courses.id = enrollments.course_id
        WHERE enrollments.email = (
            SELECT email FROM students WHERE id=?
        )
    """, (session["student_id"],)).fetchall()

    conn.close()

    return render_template(
        "student_dashboard.html",
        courses=courses
    )


@app.route("/student/logout")
def student_logout():
    session.pop("student_id", None)
    session.pop("student_name", None)
    return redirect("/")



@app.route("/instructor/dashboard")
def instructor_dashboard():
    if not session.get("instructor"):
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    courses = cur.execute("SELECT * FROM courses").fetchall()
    conn.close()

    return render_template(
        "instructor_dashboard.html",
        courses=courses
    )



def instructor_required():
    return session.get("instructor") is True


if __name__ == "__main__":
    init_db()
    app.run()


with app.app_context():
    init_db()

