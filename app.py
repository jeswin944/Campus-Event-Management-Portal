from dotenv import load_dotenv
load_dotenv()

from flask import Flask, session, render_template, redirect, url_for, flash
from extensions import mail
from models.db import get_db_connection
from routes.auth_routes import auth_bp
from routes.student_routes import student_bp
from routes.faculty_routes import faculty_bp
from routes.admin_routes import admin_bp
from routes.public_routes import public_bp
from routes.common_routes import common_bp

# flask imported above
pass

from config import Config

app = Flask(__name__)
app.config.from_object(Config)

mail.init_app(app)

# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(student_bp)
app.register_blueprint(faculty_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(public_bp)
app.register_blueprint(common_bp)


import os
import json
from flask import request

@app.before_request
def check_maintenance_mode():
    # Allow static files, login/logout, and only block student/faculty routes
    if request.path.startswith('/static') or request.path.startswith('/login') or request.path.startswith('/logout'):
        return
        
    maintenance_file = '.maintenance'
    if os.path.exists(maintenance_file):
        # Allow admins to bypass maintenance, but block everyone else from restricted routes
        # Also allow the /maintenance page itself to avoid infinite loop
        if request.path.startswith('/maintenance'):
            return
            
        if request.path.startswith('/student') or request.path.startswith('/faculty'):
            # Clear session for non-admins if they try to access while maintenance is active
            if session.get('role') in ['student', 'faculty'] and not session.get('is_admin'):
                session.clear()
                return redirect(url_for('public.maintenance'))
            return redirect(url_for('public.maintenance'))

@app.after_request
def add_cache_control(response):
    if not request.path.startswith('/static'):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ── Auto-create missing tables on startup ─────────────────────────────────────
def create_missing_tables():
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS waitlist (
                waitlist_id  INT AUTO_INCREMENT PRIMARY KEY,
                event_id     INT NOT NULL,
                student_id   INT NOT NULL,
                position     INT NOT NULL DEFAULT 1,
                added_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (event_id)   REFERENCES events(event_id)   ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES student(student_id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_attendance (
                attendance_id INT AUTO_INCREMENT PRIMARY KEY,
                timetable_id  INT NOT NULL,
                student_id    INT NOT NULL,
                attendance_date DATE NOT NULL,
                status        ENUM('Present', 'Absent') DEFAULT 'Absent',
                UNIQUE KEY unique_attendance (timetable_id, student_id, attendance_date),
                FOREIGN KEY (timetable_id) REFERENCES timetable(timetable_id) ON DELETE CASCADE,
                FOREIGN KEY (student_id)   REFERENCES student(student_id) ON DELETE CASCADE
            )
        """)
        db.commit()
        db.close()
    except Exception as e:
        print(f"[STARTUP] Table creation warning: {e}")

with app.app_context():
    create_missing_tables()

# Context Processor for Notifications
@app.context_processor
def inject_notifications():
    if 'user_id' in session:
        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)
            cursor.execute("""
                SELECT COUNT(*) as count FROM notifications 
                WHERE user_id = %s AND user_role = %s AND is_read = 0
            """, (session['user_id'], session.get('role')))
            result = cursor.fetchone()
            db.close()
            return {'unread_notifications': result['count'] if result else 0}
        except:
            return {'unread_notifications': 0}
    return {'unread_notifications': 0}

@app.errorhandler(403)
def forbidden(e):
    flash("Unauthorized access. You do not have permission to view this page.", "error")
    return redirect(url_for('auth.login'))

@app.errorhandler(404)
def not_found(e):
    return render_template('status.html', 
                          title="Page Not Found",
                          status_code="404",
                          message="The page you are looking for might have been removed, had its name changed, or is temporarily unavailable.",
                          icon="fa-exclamation-triangle",
                          is_maintenance=False), 404

# URL Adapter for Templates (Backward Compatibility)
def legacy_url_for(endpoint, **values):
    mapping = {
        'login': 'auth.login',
        'logout': 'auth.logout',
        'register_user': 'auth.register_user',
        'forgot_password': 'auth.forgot_password',
        'reset_password': 'auth.reset_password',
        'change_password': 'auth.change_password',
        
        'student_dashboard': 'student.student_dashboard',
        'my_registrations': 'student.my_registrations',
        'register_for_event': 'student.register_for_event',
        'cancel_registration': 'student.cancel_registration',
        'submit_feedback': 'student.submit_feedback',
        'student_timetable': 'student.student_timetable',
        'request_onduty': 'student.request_onduty',
        'student_exams': 'student.student_exams',
        'download_certificate': 'student.download_certificate',
        
        'faculty_dashboard': 'faculty.faculty_dashboard',
        'faculty_timetable': 'faculty.faculty_timetable',
        'export_attendance': 'faculty.export_attendance',
        'scan_attendance': 'faculty.scan_attendance',
        
        'admin_dashboard': 'admin.admin_dashboard',
        'create_event': 'admin.create_event',
        'delete_event': 'admin.delete_event',
        'toggle_event_status': 'admin.toggle_event_status',
        'register_faculty': 'admin.register_faculty',
        'manage_users': 'admin.manage_users',
        'edit_student': 'admin.edit_student',
        'delete_student': 'admin.delete_student',
        'edit_faculty': 'admin.edit_faculty',
        'delete_faculty': 'admin.delete_faculty',
        'system_settings': 'admin.system_settings',
        'admin_feedbacks': 'admin.admin_feedbacks',
        'admin_courses': 'admin.admin_courses',
        'delete_course': 'admin.delete_course',
        'manage_courses': 'admin.manage_courses',
        'manage_timetable': 'admin.manage_timetable',
        'delete_timetable_slot_admin': 'admin.delete_timetable_slot_admin',
        'admin_onduty': 'admin.admin_onduty',
        'approve_onduty': 'admin.approve_onduty',
        'admin_exams': 'admin.admin_exams',
        'delete_exam': 'admin.delete_exam',
        'admin_certificates': 'admin.admin_certificates',
        'approve_certificate': 'admin.approve_certificate',
        
        'daily_attendance': 'faculty.daily_attendance_overview',
        'mark_attendance': 'faculty.mark_students_attendance',
        
        'home': 'public.home',
        'events': 'public.events',
        
        'get_notifications': 'common.get_notifications'
    }
    
    # If endpoint contains dot, it's likely already namespaced
    if '.' not in endpoint:
        endpoint = mapping.get(endpoint, endpoint)
        
    return url_for(endpoint, **values)

app.jinja_env.globals['url_for'] = legacy_url_for

# Custom Jinja2 filter: 24h "HH:MM" → clean 12h "H:MM" (no AM/PM suffix)
def fmt_time(value):
    try:
        if value is None:
            return ''
        s = str(value).strip()
        # Handle timedelta objects returned by MySQL TIME columns
        if hasattr(value, 'seconds'):
            total = int(value.total_seconds())
            h = total // 3600
            m = (total % 3600) // 60
        else:
            parts = s.split(':')
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
        h12 = h % 12 or 12
        return f"{h12}:{m:02d}"
    except Exception:
        return str(value)

app.jinja_env.filters['fmt_time'] = fmt_time

if __name__ == '__main__':
    app.run(debug=True)