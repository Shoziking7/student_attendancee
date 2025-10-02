from flask import Flask, render_template, request, redirect, session, flash, url_for
import sqlite3
import pickle
import cv2
import numpy as np
from datetime import datetime
import os
import base64
import uuid
from functools import wraps

app = Flask(__name__)
app.secret_key = "supersecretkey123"
app.config['UPLOAD_FOLDER'] = 'static/uploads'

DB_NAME = "attendance.db"

# Define available modules
MODULES = {
    'ALDS301': 'Algorithm Design',
    'SEP401': 'Software Engineering',
    'DBS501': 'Database Systems',
    'NWC601': 'Network Computing'
}

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ---------- AUTHENTICATION DECORATORS ----------
def lecturer_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "lecturer" not in session:
            flash("Lecturer access required", "warning")
            return redirect("/lecturer_login")
        return f(*args, **kwargs)
    return decorated_function

def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "student" not in session:
            flash("Student login required", "warning")
            return redirect("/student_login")
        return f(*args, **kwargs)
    return decorated_function

# ---------- DATABASE SETUP ----------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    
    # Lecturers table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lecturers (
            staff_id TEXT PRIMARY KEY, 
            password TEXT,
            name TEXT
        )
    """)
    
    # Students table (now with login credentials)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT UNIQUE NOT NULL, 
            name TEXT NOT NULL, 
            mobile TEXT NOT NULL, 
            password TEXT NOT NULL,
            photo_path TEXT,
            face_encoding BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Attendance table with module support
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            student_id TEXT, 
            date TEXT, 
            time TEXT, 
            module_code TEXT,
            FOREIGN KEY (student_id) REFERENCES students (student_id)
        )
    """)
    
    # Add default lecturer and a sample student
    cur.execute("INSERT OR IGNORE INTO lecturers VALUES (?, ?, ?)", 
                ("admin", "1234", "Administrator"))
    
    # Sample student (you can remove this later)
    cur.execute("INSERT OR IGNORE INTO students (student_id, name, mobile, password) VALUES (?, ?, ?, ?)", 
                ("S001", "Sample Student", "1234567890", "student123"))
    
    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# ---------- SIMPLE FACE RECOGNITION (Alternative approach) ----------
def extract_face_features(image_path):
    """Extract simple facial features using OpenCV"""
    try:
        # Read image
        img = cv2.imread(image_path)
        if img is None:
            return None
            
        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Resize to standard size
        gray = cv2.resize(gray, (100, 100))
        
        # Normalize
        gray = gray / 255.0
        
        # Flatten and return
        return gray.flatten()
    except Exception as e:
        print(f"Error in feature extraction: {e}")
        return None

def compare_faces(features1, features2, threshold=0.8):
    """Compare two feature vectors using cosine similarity"""
    if features1 is None or features2 is None:
        return False
        
    # Simple cosine similarity
    dot_product = np.dot(features1, features2)
    norm1 = np.linalg.norm(features1)
    norm2 = np.linalg.norm(features2)
    
    if norm1 == 0 or norm2 == 0:
        return False
        
    similarity = dot_product / (norm1 * norm2)
    return similarity > threshold

# ---------- ROUTES ----------
@app.route("/")
def main_login():
    return render_template("main_login.html")

@app.route("/lecturer_login", methods=["GET", "POST"])
def lecturer_login():
    if request.method == "POST":
        staff_id = request.form["staff_id"]
        password = request.form["password"]
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM lecturers WHERE staff_id=? AND password=?", (staff_id, password))
        lecturer = cur.fetchone()
        conn.close()
        
        if lecturer:
            session["lecturer"] = staff_id
            session["lecturer_name"] = lecturer[2]
            flash("Login successful!", "success")
            return redirect("/dashboard")
        else:
            flash("Invalid credentials. Please try again.", "danger")
    
    return render_template("lecturer_login.html")

@app.route("/student_login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        student_id = request.form["student_id"]
        password = request.form["password"]
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM students WHERE student_id=? AND password=?", (student_id, password))
        student = cur.fetchone()
        conn.close()
        
        if student:
            session["student"] = student_id
            session["student_name"] = student['name']
            flash("Login successful!", "success")
            return redirect("/student_dashboard")
        else:
            flash("Invalid student ID or password.", "danger")
    
    return render_template("student_login.html")

@app.route("/dashboard")
@lecturer_required
def dashboard():
    # Get attendance statistics
    conn = get_db_connection()
    
    # Count total students
    total_students = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    
    # Count today's attendance per module
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Get module-wise attendance for today
    module_attendance = conn.execute("""
        SELECT module_code, COUNT(DISTINCT student_id) as present_count 
        FROM attendance 
        WHERE date = ? 
        GROUP BY module_code
    """, (today,)).fetchall()
    
    # Get recent attendance
    recent_attendance = conn.execute("""
        SELECT a.student_id, s.name, a.date, a.time, a.module_code 
        FROM attendance a 
        JOIN students s ON a.student_id = s.student_id 
        ORDER BY a.id DESC 
        LIMIT 5
    """).fetchall()
    
    conn.close()
    
    return render_template("dashboard.html", 
                           total_students=total_students,
                           module_attendance=module_attendance,
                           recent_attendance=recent_attendance,
                           modules=MODULES)

@app.route("/student_dashboard")
@student_required
def student_dashboard():
    conn = get_db_connection()
    
    # Get recent attendance for this student
    recent_attendance = conn.execute("""
        SELECT date, time, module_code 
        FROM attendance 
        WHERE student_id = ? 
        ORDER BY date DESC, time DESC 
        LIMIT 5
    """, (session["student"],)).fetchall()
    
    # Get module-wise attendance summary for this student
    module_summary = conn.execute("""
        SELECT module_code, COUNT(*) as days_present
        FROM attendance 
        WHERE student_id = ? 
        GROUP BY module_code
    """, (session["student"],)).fetchall()
    
    conn.close()
    
    return render_template("student_dashboard.html", 
                          recent_attendance=recent_attendance,
                          module_summary=module_summary,
                          modules=MODULES)

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out", "info")
    return redirect("/")

@app.route("/student_logout")
def student_logout():
    session.clear()
    flash("You have been logged out", "info")
    return redirect("/")

# CREATE - Register Student
@app.route("/register_student", methods=["GET", "POST"])
@lecturer_required
def register_student():
    if request.method == "POST":
        student_id = request.form["student_id"]
        name = request.form["name"]
        mobile = request.form["mobile"]
        password = request.form["password"]
        
        # Check if student ID already exists
        conn = get_db_connection()
        existing_student = conn.execute("SELECT * FROM students WHERE student_id=?", (student_id,)).fetchone()
        
        if existing_student:
            flash("Student ID already exists! Please use a different ID.", "danger")
            conn.close()
            return redirect("/register_student")
        
        # Process image
        if 'photo' not in request.files:
            flash("No photo uploaded", "danger")
            return redirect("/register_student")
            
        file = request.files['photo']
        if file.filename == '':
            flash("No selected file", "danger")
            return redirect("/register_student")
            
        # Save file with unique name
        filename = f"{student_id}_{uuid.uuid4().hex[:8]}.jpg"
        photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(photo_path)
        
        # Extract features
        features = extract_face_features(photo_path)
        
        if features is None:
            flash("Error processing image. Please try again.", "danger")
            os.remove(photo_path)
            return redirect("/register_student")
        
        # Save to database with password
        conn.execute("""
            INSERT INTO students (student_id, name, mobile, password, photo_path, face_encoding) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, (student_id, name, mobile, password, photo_path, pickle.dumps(features)))
        
        conn.commit()
        conn.close()
        
        flash(f"Student {name} registered successfully!", "success")
        return redirect("/view_students")
    
    return render_template("register_student.html")

# READ - View All Students
@app.route("/view_students")
@lecturer_required
def view_students():
    conn = get_db_connection()
    students = conn.execute("SELECT * FROM students ORDER BY created_at DESC").fetchall()
    conn.close()
    
    return render_template("view_students.html", students=students)

# READ - View Single Student
@app.route("/student/<int:student_id>")
@lecturer_required
def view_student(student_id):
    conn = get_db_connection()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    
    # Get student's module-wise attendance
    module_attendance = conn.execute("""
        SELECT module_code, COUNT(*) as days_present,
               (SELECT COUNT(DISTINCT date) FROM attendance WHERE module_code = a.module_code) as total_days,
               ROUND(COUNT(*) * 100.0 / (SELECT COUNT(DISTINCT date) FROM attendance WHERE module_code = a.module_code), 2) as attendance_rate
        FROM attendance a
        WHERE student_id = ?
        GROUP BY module_code
    """, (student['student_id'],)).fetchall()
    
    conn.close()
    
    if student is None:
        flash("Student not found!", "danger")
        return redirect("/view_students")
    
    return render_template("view_student.html", student=student, module_attendance=module_attendance, modules=MODULES)

# UPDATE - Edit Student
@app.route("/edit_student/<int:student_id>", methods=["GET", "POST"])
@lecturer_required
def edit_student(student_id):
    conn = get_db_connection()
    
    if request.method == "POST":
        name = request.form["name"]
        mobile = request.form["mobile"]
        photo = request.files['photo']
        
        update_data = [name, mobile]
        update_query = "UPDATE students SET name = ?, mobile = ?"
        
        # Handle photo update
        if photo and photo.filename:
            # Delete old photo
            old_student = conn.execute("SELECT photo_path FROM students WHERE id = ?", (student_id,)).fetchone()
            if old_student and os.path.exists(old_student['photo_path']):
                os.remove(old_student['photo_path'])
            
            # Save new photo
            student_data = conn.execute("SELECT student_id FROM students WHERE id = ?", (student_id,)).fetchone()
            filename = f"{student_data['student_id']}_{uuid.uuid4().hex[:8]}.jpg"
            photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            photo.save(photo_path)
            
            # Extract features from new photo
            features = extract_face_features(photo_path)
            if features is not None:
                update_query += ', photo_path = ?, face_encoding = ?'
                update_data.extend([photo_path, pickle.dumps(features)])
            else:
                flash("Error processing new image. Photo not updated.", "warning")
        
        update_query += ' WHERE id = ?'
        update_data.append(student_id)
        
        conn.execute(update_query, tuple(update_data))
        conn.commit()
        conn.close()
        
        flash('Student updated successfully!', 'success')
        return redirect('/view_students')
    
    # GET request - show edit form
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    conn.close()
    
    if student is None:
        flash("Student not found!", "danger")
        return redirect("/view_students")
    
    return render_template("edit_student.html", student=student)

# DELETE - Remove Student
@app.route("/delete_student/<int:student_id>")
@lecturer_required
def delete_student(student_id):
    conn = get_db_connection()
    
    # Get student data before deletion
    student = conn.execute("SELECT photo_path FROM students WHERE id = ?", (student_id,)).fetchone()
    
    if student:
        # Delete photo file
        if student['photo_path'] and os.path.exists(student['photo_path']):
            os.remove(student['photo_path'])
        
        # Delete from database
        conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
        conn.commit()
        conn.close()
        
        flash('Student deleted successfully!', 'success')
    else:
        flash('Student not found!', 'danger')
    
    return redirect('/view_students')

# Lecturer attendance taking (with module selection)
@app.route("/attendance", methods=["GET", "POST"])
@lecturer_required
def take_attendance():
    if request.method == "POST":
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], 'live_attendance.jpg')
        selected_module = request.form.get("module_code", "ALDS301")

        # --- Case 1: Camera Image (Base64) ---
        if "camera_image" in request.form and request.form["camera_image"]:
            try:
                img_data = request.form["camera_image"].split(",")[1]  # remove "data:image/jpeg;base64,"
                img_bytes = base64.b64decode(img_data)

                with open(temp_path, "wb") as f:
                    f.write(img_bytes)
            except Exception as e:
                flash(f"Error decoding camera image: {e}", "danger")
                return redirect("/attendance")

        # --- Case 2: Uploaded File ---
        elif "photo" in request.files:
            file = request.files["photo"]
            if file.filename == "":
                flash("No selected file", "danger")
                return redirect("/attendance")
            file.save(temp_path)

        else:
            flash("No photo or camera image provided", "danger")
            return redirect("/attendance")

        # --- Extract Features ---
        live_features = extract_face_features(temp_path)
        if live_features is None:
            flash("Error processing image. Please try again.", "danger")
            os.remove(temp_path)
            return redirect("/attendance")

        # --- Compare with Database ---
        conn = get_db_connection()
        students = conn.execute("SELECT student_id, name, face_encoding FROM students").fetchall()

        recognized_students = []
        for student in students:
            db_features = pickle.loads(student['face_encoding'])
            if compare_faces(live_features, db_features):
                now = datetime.now()
                
                # Check if already marked attendance for this module today
                existing = conn.execute("""
                    SELECT * FROM attendance 
                    WHERE student_id=? AND date=? AND module_code=?
                """, (student['student_id'], now.strftime("%Y-%m-%d"), selected_module)).fetchone()
                
                if existing:
                    recognized_students.append(f"{student['name']} (already marked for {selected_module})")
                else:
                    conn.execute("""
                        INSERT INTO attendance (student_id, date, time, module_code) 
                        VALUES (?, ?, ?, ?)
                    """, (student['student_id'], now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), selected_module))
                    recognized_students.append(f"{student['name']} ({selected_module})")
                break

        conn.commit()
        conn.close()
        os.remove(temp_path)

        if recognized_students:
            flash(f"Attendance recorded: {', '.join(recognized_students)}", "success")
        else:
            flash("No matching students found", "warning")

        return redirect("/attendance")

    return render_template("attendance.html", modules=MODULES)

# Student attendance marking (with module selection)
@app.route("/mark_attendance", methods=["GET", "POST"])
@student_required
def mark_attendance():
    if request.method == "POST":
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], 'live_attendance.jpg')
        selected_module = request.form.get("module_code", "ALDS301")

        # Handle camera image
        if "camera_image" in request.form and request.form["camera_image"]:
            try:
                img_data = request.form["camera_image"].split(",")[1]
                img_bytes = base64.b64decode(img_data)

                with open(temp_path, "wb") as f:
                    f.write(img_bytes)
            except Exception as e:
                flash(f"Error decoding camera image: {e}", "danger")
                return redirect("/mark_attendance")

        # Handle uploaded file
        elif "photo" in request.files:
            file = request.files["photo"]
            if file.filename == "":
                flash("No selected file", "danger")
                return redirect("/mark_attendance")
            file.save(temp_path)

        else:
            flash("No photo or camera image provided", "danger")
            return redirect("/mark_attendance")

        # Extract features
        live_features = extract_face_features(temp_path)
        if live_features is None:
            flash("Error processing image. Please try again.", "danger")
            os.remove(temp_path)
            return redirect("/mark_attendance")

        # Compare with database
        conn = get_db_connection()
        student = conn.execute("SELECT face_encoding FROM students WHERE student_id=?", (session["student"],)).fetchone()

        if student:
            db_features = pickle.loads(student['face_encoding'])
            if compare_faces(live_features, db_features):
                now = datetime.now()
                
                # Check if already marked attendance for this module today
                existing = conn.execute("""
                    SELECT * FROM attendance 
                    WHERE student_id=? AND date=? AND module_code=?
                """, (session["student"], now.strftime("%Y-%m-%d"), selected_module)).fetchone()
                
                if existing:
                    flash(f"Attendance already marked for {selected_module} today!", "warning")
                else:
                    conn.execute("""
                        INSERT INTO attendance (student_id, date, time, module_code) 
                        VALUES (?, ?, ?, ?)
                    """, (session["student"], now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), selected_module))
                    conn.commit()
                    flash(f"Attendance marked successfully for {MODULES[selected_module]}!", "success")
            else:
                flash("Face recognition failed. Please try again.", "danger")
        else:
            flash("Student record not found.", "danger")

        conn.close()
        os.remove(temp_path)
        return redirect("/mark_attendance")

    return render_template("mark_attendance.html", modules=MODULES)

@app.route("/view_attendance")
@lecturer_required
def view_attendance():
    date_filter = request.args.get('date', datetime.now().strftime("%Y-%m-%d"))
    module_filter = request.args.get('module', '')
    
    conn = get_db_connection()
    
    # Build query based on filters
    query = """
        SELECT s.student_id, s.name, a.time, a.module_code 
        FROM attendance a 
        JOIN students s ON a.student_id = s.student_id 
        WHERE a.date = ?
    """
    params = [date_filter]
    
    if module_filter:
        query += " AND a.module_code = ?"
        params.append(module_filter)
    
    query += " ORDER BY a.time DESC"
    
    attendance_records = conn.execute(query, tuple(params)).fetchall()
    
    conn.close()
    
    return render_template("view_attendance.html", 
                           attendance_records=attendance_records,
                           selected_date=date_filter,
                           selected_module=module_filter,
                           modules=MODULES)

@app.route("/view_report")
@lecturer_required
def view_report():
    module_filter = request.args.get('module_filter', '')
    date_filter = request.args.get('date_filter', '')
    
    conn = get_db_connection()

    # Build queries based on filters
    base_where = "1=1"
    params = []
    
    if module_filter:
        base_where += " AND a.module_code = ?"
        params.append(module_filter)
    
    if date_filter:
        base_where += " AND a.date = ?"
        params.append(date_filter)

    # total students
    total_students = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] or 0

    # today's stats
    today = datetime.now().strftime("%Y-%m-%d")
    present_today = conn.execute("SELECT COUNT(DISTINCT student_id) FROM attendance WHERE date=?", (today,)).fetchone()[0] or 0
    absent_today = total_students - present_today if total_students > 0 else 0
    attendance_rate = round((present_today / total_students * 100), 2) if total_students > 0 else 0

    # module-wise attendance summary
    module_summary = conn.execute(f"""
        SELECT module_code, COUNT(DISTINCT student_id) as present_count,
               (SELECT COUNT(*) FROM students) as total_students,
               ROUND(COUNT(DISTINCT student_id) * 100.0 / (SELECT COUNT(*) FROM students), 2) as attendance_rate
        FROM attendance 
        WHERE date = ?
        GROUP BY module_code
    """, (today,)).fetchall()

    # student-wise report with module filtering
    student_reports_query = f"""
        SELECT s.student_id, s.name, 
               COUNT(CASE WHEN {base_where} THEN 1 END) as days_present,
               (SELECT COUNT(DISTINCT date) FROM attendance WHERE {base_where.replace('a.', '')}) as total_days
        FROM students s
        LEFT JOIN attendance a ON s.student_id = a.student_id
        GROUP BY s.student_id, s.name
        ORDER BY s.name
    """
    
    raw_reports = conn.execute(student_reports_query, params).fetchall()

    student_reports = []
    for report in raw_reports:
        student_id, name, days_present, total_days = report
        total_absent = (total_days - days_present) if total_days > 0 else 0
        attendance_pct = round((days_present / total_days * 100), 2) if total_days > 0 else 0
        student_reports.append((student_id, name, days_present, total_absent, attendance_pct))

    conn.close()

    return render_template("view_report.html",
                           total_students=total_students,
                           present_today=present_today,
                           absent_today=absent_today,
                           attendance_rate=attendance_rate,
                           student_reports=student_reports,
                           module_summary=module_summary,
                           modules=MODULES,
                           selected_module=module_filter,
                           selected_date=date_filter,
                           current_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

@app.route("/debug_routes")
def debug_routes():
    routes = []
    for rule in app.url_map.iter_rules():
        if "static" not in str(rule):
            routes.append(str(rule))
    return "<br>".join(routes)

if __name__ == "__main__":
    app.run(debug=True)