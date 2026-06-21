from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, current_app
from models.db import get_db_connection
from utils.helpers import login_required, add_notification, notify_admins
from services.email_service import send_email
from werkzeug.security import generate_password_hash
from datetime import timedelta
import time

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if not session.get('is_admin'):
        abort(403)
    
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    stats = {}
    
    cursor.execute("SELECT COUNT(*) as count FROM events")
    stats['total_events'] = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM registrations")
    stats['total_registrations'] = cursor.fetchone()['count']

    cursor.execute("SELECT COUNT(*) as count FROM onduty_requests WHERE status='Pending'")
    stats['pending_ods'] = cursor.fetchone()['count']

    from datetime import datetime
    today_date = datetime.now().date()
    cursor.execute("SELECT COUNT(DISTINCT timetable_id) as count FROM daily_attendance WHERE attendance_date = %s", (today_date,))
    stats['today_attendance_count'] = cursor.fetchone()['count']

    cursor.execute("SELECT faculty_id, name, department FROM faculty ORDER BY name")
    faculty_list = cursor.fetchall()

    cursor.execute("""
        SELECT 
            e.event_name,
            COUNT(r.registration_id) as total_reg,
            SUM(CASE WHEN r.attendance = 'Present' THEN 1 ELSE 0 END) as attended
        FROM events e
        LEFT JOIN registrations r ON e.event_id = r.event_id
        GROUP BY e.event_id, e.event_name
    """)
    analytics_data = cursor.fetchall()
    
    db.close()
    return render_template('admin_dashboard.html', faculty_list=faculty_list, analytics_data=analytics_data, **stats)

@admin_bp.route('/create-event', methods=['GET', 'POST'])
@login_required
def create_event():
    if not session.get('is_admin'):
        abort(403)

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':
        event_name = request.form['event_name']
        event_date = request.form['event_date']
        location = request.form['location']
        description = request.form['description']
        coordinator_id = request.form['coordinator_id']
        duration = request.form.get('duration', '1 Day')
        event_end_date = request.form.get('event_end_date') if duration != '1 Day' else None
        max_seats = request.form.get('max_seats', 30)
        event_type = request.form.get('event_type', 'General')
        department = request.form.get('department', 'All')
        points_awarded = request.form.get('points_awarded', 10)

        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')

        try:
            cursor.execute("""
                INSERT INTO events (event_name, event_date, event_end_date, duration, location, description, coordinator_id, max_seats, is_announced, event_type, points_awarded, department, start_time, end_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s)
            """, (event_name, event_date, event_end_date, duration, location, description, coordinator_id, max_seats, event_type, points_awarded, department, start_time, end_time))
            db.commit()

            # Only notify admin on creation
            cursor.execute("SELECT email FROM faculty WHERE is_admin=1")
            admins = cursor.fetchall()
            
            body = f"""
Event Draft Created!

Event Name: {event_name}
Date: {event_date}
Location: {location}

This event is currently a draft and has NOT been announced to students/faculty yet. 
Use the 'Announce' button in the dashboard to send notifications.
"""
            for admin in admins:
                send_email("Event Created (Draft)", [admin['email']], body=body)

            # Notification for coordinator
            add_notification(coordinator_id, 'faculty', f"Assigned Coordinator: {event_name} (Draft).")

            db.close()
            flash("Event created as draft! Only admins notified.", "success")
            return redirect(url_for('admin.admin_dashboard'))
        except Exception as e:
            db.rollback()
            db.close()
            flash(f"Error creating event: {str(e)}", "error")
            return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/admin/announce-event/<int:event_id>')
@login_required
def announce_event(event_id):
    if not session.get('is_admin'):
        abort(403)
    
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    try:
        cursor.execute("SELECT * FROM events WHERE event_id=%s", (event_id,))
        event = cursor.fetchone()
        
        if not event:
            db.close()
            flash("Event not found.", "error")
            return redirect(url_for('public.events'))
            
        if event['is_announced']:
            db.close()
            flash("Event already announced.", "info")
            return redirect(url_for('public.events'))

        # Fetch all students and faculty
        cursor.execute("SELECT email FROM student")
        students = cursor.fetchall()
        cursor.execute("SELECT email FROM faculty")
        faculty_members = cursor.fetchall()
        
        all_emails = [s['email'] for s in students] + [f['email'] for f in faculty_members]
        
        body = f"""
A new event has been officially announced!

Event Name: {event['event_name']}
Date: {event['event_date']}
Location: {event['location']}
Description: {event['description']}

Login to the portal to register or view more details!
"""
        # Send one announcement email with everyone in BCC for privacy and speed
        send_email("New Event Announcement!", recipients=[current_app.config['MAIL_USERNAME']], bcc=all_emails, body=body)

        # Update status
        cursor.execute("UPDATE events SET is_announced=1 WHERE event_id=%s", (event_id,))
        db.commit()
        
        # Notifications
        cursor.execute("SELECT student_id FROM student")
        for s in cursor.fetchall():
            add_notification(s['student_id'], 'student', f"New Event Announced: {event['event_name']}!")
            
        db.close()
        flash("Event announced to all students and faculty!", "success")
    except Exception as e:
        db.rollback()
        db.close()
        flash(f"Error announcing event: {str(e)}", "error")
        
    return redirect(url_for('public.events'))

@admin_bp.route('/admin/edit-event/<int:event_id>', methods=['GET', 'POST'])
@login_required
def edit_event(event_id):
    if not session.get('is_admin'):
        abort(403)
        
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        event_name = request.form['event_name']
        event_date = request.form['event_date']
        location = request.form['location']
        description = request.form['description']
        coordinator_id = request.form['coordinator_id']
        event_type = request.form.get('event_type', 'General')
        department = request.form.get('department', 'All')
        points_awarded = request.form.get('points_awarded', 10)
        event_end_date = request.form.get('event_end_date')
        duration = request.form.get('duration', '1 Day')
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')

        if duration == '1 Day':
            event_end_date = event_date

        try:
            cursor.execute("""
                UPDATE events 
                SET event_name=%s, event_date=%s, event_end_date=%s, duration=%s, location=%s, description=%s, 
                    coordinator_id=%s, event_type=%s, points_awarded=%s, department=%s, start_time=%s, end_time=%s
                WHERE event_id=%s
            """, (event_name, event_date, event_end_date, duration, location, description, 
                  coordinator_id, event_type, points_awarded, department, start_time, end_time, event_id))
            db.commit()
            flash("Event updated successfully!", "success")
        except Exception as e:
            db.rollback()
            flash(f"Error updating event: {e}", "error")
        
        db.close()
        return redirect(url_for('public.events'))

    cursor.execute("SELECT * FROM events WHERE event_id=%s", (event_id,))
    event = cursor.fetchone()
    db.close()
    if not event:
        flash("Event not found.", "error")
        return redirect(url_for('public.events'))
        
    return redirect(url_for('public.events')) # We handle via Modal so this shouldn't be reached directly for GET usually if logic is in modal


@admin_bp.route('/admin/delete-event/<int:event_id>')
@login_required
def delete_event(event_id):
    if not session.get('is_admin'):
        abort(403)
    time.sleep(3)
    
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT event_name FROM events WHERE event_id=%s", (event_id,))
        event = cursor.fetchone()
        if not event:
            db.close()
            flash("Event not found.", "error")
            # Redirect to events? events is likely public or student
            return redirect(url_for('public.events')) 

        cursor.execute("DELETE FROM feedback WHERE event_id=%s", (event_id,))
        cursor.execute("DELETE FROM onduty_requests WHERE event_id=%s", (event_id,))
        cursor.execute("DELETE FROM registrations WHERE event_id=%s", (event_id,))
        cursor.execute("DELETE FROM events WHERE event_id=%s", (event_id,))
        db.commit()
        flash(f"Event '{event['event_name']}' and all related records deleted successfully.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error deleting event: {str(e)}", "error")
        
    db.close()
    return redirect(url_for('public.events'))


@admin_bp.route('/admin/register-faculty', methods=['GET', 'POST'])
@login_required
def register_faculty():
    if not session.get('is_admin'):
        abort(403)

    if request.method == 'POST':
        time.sleep(3)
        name = request.form['name']
        email = request.form['email']
        department = request.form['department']
        password = request.form['password']
        
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        cursor.execute("SELECT faculty_id FROM faculty WHERE email=%s", (email,))
        if cursor.fetchone():
            db.close()
            flash("Faculty email already registered", "error")
            return redirect(url_for('admin.register_faculty'))

        hashed = generate_password_hash(password)
        
        try:
            cursor.execute("""
                INSERT INTO faculty (name, email, department, password, is_admin)
                VALUES (%s, %s, %s, %s, 0)
            """, (name, email, department, hashed))
            db.commit()
            db.close()
            flash("Faculty member registered successfully", "success")
            return redirect(url_for('admin.admin_dashboard'))
        except Exception as e:
            db.rollback()
            db.close()
            flash(f"Error registering faculty: {str(e)}", "error")
            return redirect(url_for('admin.register_faculty'))

    return render_template('register_faculty.html')

@admin_bp.route('/admin/manage-users')
@login_required
def manage_users():
    if not session.get('is_admin'):
        abort(403)
        
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM student ORDER BY name")
    students = cursor.fetchall()
    cursor.execute("SELECT * FROM faculty ORDER BY name")
    faculty = cursor.fetchall()
    db.close()
    
    return render_template('manage_users.html', students=students, faculty=faculty)

@admin_bp.route('/admin/edit-student/<int:id>', methods=['POST'])
@login_required
def edit_student(id):
    if not session.get('is_admin'):
        abort(403)
    
    name = request.form.get('name')
    email = request.form.get('email')
    reg_no = request.form.get('register_number')
    dept = request.form.get('department')
    sem = request.form.get('semester')
    
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE student 
            SET name=%s, email=%s, register_number=%s, department=%s, semester=%s
            WHERE student_id=%s
        """, (name, email, reg_no, dept, sem, id))
        db.commit()
        flash("Student updated successfully", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error updating student: {str(e)}", "error")
    db.close()
    return redirect(url_for('admin.manage_users'))

@admin_bp.route('/admin/delete-student/<int:id>')
@login_required
def delete_student(id):
    if not session.get('is_admin'):
        abort(403)
    time.sleep(3)
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM feedback WHERE student_id=%s", (id,))
        cursor.execute("DELETE FROM onduty_requests WHERE student_id=%s", (id,))
        cursor.execute("DELETE FROM registrations WHERE student_id=%s", (id,))
        cursor.execute("DELETE FROM student WHERE student_id=%s", (id,))
        db.commit()
        flash("Student deleted successfully", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error deleting student: {str(e)}", "error")
    db.close()
    return redirect(url_for('admin.manage_users'))

@admin_bp.route('/admin/edit-faculty/<int:id>', methods=['POST'])
@login_required
def edit_faculty(id):
    if not session.get('is_admin'):
        abort(403)
    name = request.form.get('name')
    email = request.form.get('email')
    dept = request.form.get('department')
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE faculty 
            SET name=%s, email=%s, department=%s
            WHERE faculty_id=%s
        """, (name, email, dept, id))
        db.commit()
        flash("Faculty member updated successfully", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error updating faculty: {str(e)}", "error")
    db.close()
    return redirect(url_for('admin.manage_users'))

@admin_bp.route('/admin/delete-faculty/<int:id>')
@login_required
def delete_faculty(id):
    if not session.get('is_admin'):
        abort(403)
    time.sleep(3)
    if id == session.get('user_id') and session.get('role') == 'faculty':
        flash("You cannot delete your own admin account.", "error")
        return redirect(url_for('admin.manage_users'))
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM faculty WHERE faculty_id=%s", (id,))
        db.commit()
        flash("Faculty member deleted successfully", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error deleting faculty: {str(e)}", "error")
    db.close()
    return redirect(url_for('admin.manage_users'))

import os

MAINTENANCE_FILE = '.maintenance'
REGISTRATION_CLOSED_FILE = '.registration_closed'
SYSTEM_EMAIL_FILE = '.system_email'

@admin_bp.route('/admin/system-settings', methods=['GET', 'POST'])
@login_required
def system_settings():
    if not session.get('is_admin'):
        abort(403)
        
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'save_settings':
            if 'maintenance_mode' in request.form:
                with open(MAINTENANCE_FILE, 'w') as f:
                    f.write('maintenance_active')
                flash("Maintenance Mode Enabled.", "warning")
            else:
                if os.path.exists(MAINTENANCE_FILE):
                    os.remove(MAINTENANCE_FILE)
                flash("System settings updated.", "success")
                
            if 'registration_open' in request.form:
                if os.path.exists(REGISTRATION_CLOSED_FILE):
                    os.remove(REGISTRATION_CLOSED_FILE)
            else:
                with open(REGISTRATION_CLOSED_FILE, 'w') as f:
                    f.write('closed')
                    
            system_email = request.form.get('system_email', 'admin@college.edu')
            with open(SYSTEM_EMAIL_FILE, 'w') as f:
                f.write(system_email)
                
        elif action == 'delete_students':
            db = get_db_connection()
            try:
                cursor = db.cursor()
                cursor.execute("DELETE FROM waitlist")
                cursor.execute("DELETE FROM feedback")
                cursor.execute("DELETE FROM onduty_requests")
                cursor.execute("DELETE FROM registrations")
                cursor.execute("DELETE FROM student")
                db.commit()
                flash("All student data deleted successfully.", "success")
            except Exception as e:
                db.rollback()
                flash(f"Error deleting students: {e}", "error")
            finally:
                db.close()
                
        elif action == 'reset_database':
            db = get_db_connection()
            try:
                cursor = db.cursor()
                cursor.execute("DELETE FROM waitlist")
                cursor.execute("DELETE FROM feedback")
                cursor.execute("DELETE FROM onduty_requests")
                cursor.execute("DELETE FROM registrations")
                cursor.execute("DELETE FROM events")
                cursor.execute("DELETE FROM student")
                cursor.execute("DELETE FROM faculty")
                cursor.execute("DELETE FROM timetable")
                cursor.execute("DELETE FROM courses")
                db.commit()
                flash("Database reset successfully. Only admin remains.", "success")
            except Exception as e:
                db.rollback()
                flash(f"Error resetting database: {e}", "error")
            finally:
                db.close()
                
        return redirect(url_for('admin.system_settings'))
        
    maintenance_active = os.path.exists(MAINTENANCE_FILE)
    registration_open = not os.path.exists(REGISTRATION_CLOSED_FILE)
    
    system_email = 'admin@college.edu'
    if os.path.exists(SYSTEM_EMAIL_FILE):
        with open(SYSTEM_EMAIL_FILE, 'r') as f:
            system_email = f.read().strip()
            
    return render_template('system_settings.html', maintenance_active=maintenance_active, registration_open=registration_open, system_email=system_email)

@admin_bp.route('/admin/feedbacks')
@login_required
def admin_feedbacks():
    if not session.get('is_admin'):
        abort(403)
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT f.*, e.event_name, s.name as student_name, s.department
        FROM feedback f
        JOIN events e ON f.event_id = e.event_id
        JOIN student s ON f.student_id = s.student_id
        ORDER BY f.created_at DESC
    """)
    feedbacks = cursor.fetchall()
    db.close()
    return render_template('admin_feedbacks.html', feedbacks=feedbacks)

@admin_bp.route('/admin/courses', methods=['GET', 'POST'])
@login_required
def admin_courses():
    if not session.get('is_admin'):
        abort(403)
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    if request.method == 'POST':
        course_name = request.form['course_name']
        dept = request.form['department']
        semester = request.form['semester']
        try:
            cursor.execute("INSERT INTO courses (course_name, department, semester) VALUES (%s, %s, %s)", 
                           (course_name, dept, semester))
            db.commit()
            flash("Course added successfully!", "success")
        except Exception as e:
            db.rollback()
            flash(f"Error adding course: {e}", "error")
        db.close()
        return redirect(url_for('admin.admin_courses'))
    cursor.execute("SELECT * FROM courses ORDER BY department, semester")
    courses = cursor.fetchall()
    db.close()
    return render_template('admin_courses.html', courses=courses)

@admin_bp.route('/admin/delete-course/<int:course_id>')
@login_required
def delete_course(course_id):
    if not session.get('is_admin'):
        abort(403)
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM timetable WHERE course_id=%s", (course_id,))
        cursor.execute("DELETE FROM courses WHERE course_id=%s", (course_id,))
        db.commit()
        flash("Course deleted.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error deleting course: {e}", "error")
    db.close()
    return redirect(url_for('admin.admin_courses'))

@admin_bp.route('/admin/edit-course/<int:course_id>', methods=['POST'])
@login_required
def edit_course(course_id):
    if not session.get('is_admin'):
        abort(403)
    course_name = request.form.get('course_name', '').strip()
    department  = request.form.get('department', '').strip()
    semester    = request.form.get('semester', '').strip()
    if not course_name or not department or not semester:
        flash("All fields are required.", "error")
        return redirect(url_for('admin.admin_courses'))
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE courses
               SET course_name=%s, department=%s, semester=%s
             WHERE course_id=%s
        """, (course_name, department, semester, course_id))
        db.commit()
        flash("Course updated successfully.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error updating course: {e}", "error")
    db.close()
    return redirect(url_for('admin.admin_courses'))

@admin_bp.route('/admin/manage-courses')
@login_required
def manage_courses():
    return redirect(url_for('admin.admin_courses'))

@admin_bp.route('/admin/manage-timetable', methods=['GET', 'POST'])
@login_required
def manage_timetable():
    if not session.get('is_admin'):
        abort(403)
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    if request.method == 'POST':
        is_break = request.form.get('is_break') == 'on'
        course_id = request.form.get('course_id') if not is_break else None
        faculty_id = request.form.get('faculty_id') if not is_break else None
        day = request.form['day']
        start_time = request.form['start_time']
        end_time = request.form['end_time']
        classroom = request.form.get('classroom', '') if not is_break else 'N/A'
        dept = request.form.get('department')
        semester = request.form.get('semester')
        
        # If course is selected, override dept/sem from course for accuracy
        if course_id:
            cursor.execute("SELECT department, semester FROM courses WHERE course_id=%s", (course_id,))
            c_info = cursor.fetchone()
            if c_info:
                dept = c_info['department']
                semester = c_info['semester']
        
        if not is_break and faculty_id:
            cursor.execute("""
                SELECT timetable_id FROM timetable
                WHERE faculty_id=%s
                AND day=%s
                AND (
                    (start_time < %s AND end_time > %s)
                )
            """, (faculty_id, day, end_time, start_time))
            conflict = cursor.fetchone()
            if conflict:
                 flash("Time conflict detected! Faculty is already booked for this slot.", "error")
                 db.close()
                 return redirect(url_for('admin.manage_timetable'))
        
        try:
            cursor.execute("""
                INSERT INTO timetable (course_id, faculty_id, day, start_time, end_time, classroom, department, semester)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (course_id, faculty_id, day, start_time, end_time, classroom, dept, semester))
            db.commit()
            flash("Schedule assigned successfully.", "success")
        except Exception as e:
            db.rollback()
            flash(f"Error assigning schedule: {e}", "error")
        db.close()
        return redirect(url_for('admin.manage_timetable'))
        
    cursor.execute("""
        SELECT t.*, c.course_name, f.name as faculty_name
        FROM timetable t
        LEFT JOIN courses c ON t.course_id = c.course_id
        LEFT JOIN faculty f ON t.faculty_id = f.faculty_id
    """)
    timetable = cursor.fetchall()

    # Convert timedeltas/time objects to strings for JSON serialization in template
    for slot in timetable:
        if slot.get('start_time'): slot['start_time'] = str(slot['start_time'])
        if slot.get('end_time'): slot['end_time'] = str(slot['end_time'])
        
    # Group by day for the Matrix View
    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    timetable_matrix = {day: [] for day in days_order}
    for slot in timetable:
        if slot['day'] in timetable_matrix:
            timetable_matrix[slot['day']].append(slot)

    # Standard periods for headers
    standard_periods = [
        {'start': '09:00:00', 'end': '10:00:00', 'label': '09:00 - 10:00'},
        {'start': '10:00:00', 'end': '11:00:00', 'label': '10:00 - 11:00'},
        {'start': '11:00:00', 'end': '11:10:00', 'label': '11:00 - 11:10 (B)'},
        {'start': '11:10:00', 'end': '12:10:00', 'label': '11:10 - 12:10'},
        {'start': '12:10:00', 'end': '12:50:00', 'label': '12:10 - 12:50 (L)'},
        {'start': '12:50:00', 'end': '13:50:00', 'label': '12:50 - 01:50'},
        {'start': '13:50:00', 'end': '14:00:00', 'label': '01:50 - 02:00 (B)'},
        {'start': '14:00:00', 'end': '15:00:00', 'label': '02:00 - 03:00'},
        {'start': '15:00:00', 'end': '16:00:00', 'label': '03:00 - 04:00'}
    ]

    cursor.execute("SELECT * FROM courses ORDER BY course_name")
    courses = cursor.fetchall()
    cursor.execute("SELECT faculty_id, name, department FROM faculty ORDER BY name")
    faculty_list = cursor.fetchall()
    db.close()
    return render_template('admin_timetable.html', 
                          timetable_matrix=timetable_matrix, 
                          standard_periods=standard_periods,
                          timetable=timetable, # keep original for fallback or modals
                          courses=courses, 
                          faculty_list=faculty_list)

@admin_bp.route('/admin/delete-timetable-slot/<int:slot_id>')
@login_required
def delete_timetable_slot_admin(slot_id):
    if not session.get('is_admin'):
        abort(403)
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM timetable WHERE timetable_id=%s", (slot_id,))
        db.commit()
        flash("Schedule deleted.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error deleting schedule: {e}", "error")
    db.close()
    return redirect(url_for('admin.manage_timetable'))

@admin_bp.route('/admin/edit-timetable', methods=['POST'])
@login_required
def edit_timetable_slot_admin():
    if not session.get('is_admin'):
        abort(403)
        
    slot_id = request.form['slot_id']
    is_break = request.form.get('is_break') == 'on'
    course_id = request.form.get('course_id') if not is_break else None
    faculty_id = request.form.get('faculty_id') if not is_break else None
    day = request.form['day']
    start_time = request.form['start_time']
    end_time = request.form['end_time']
    classroom = request.form.get('classroom', '') if not is_break else 'N/A'
    dept = request.form.get('department')
    semester = request.form.get('semester')

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if course_id:
        cursor.execute("SELECT department, semester FROM courses WHERE course_id=%s", (course_id,))
        c_info = cursor.fetchone()
        if c_info:
            dept = c_info['department']
            semester = c_info['semester']
    
    # Conflict check (excluding current slot)
    if not is_break and faculty_id:
        cursor.execute("""
            SELECT timetable_id FROM timetable
            WHERE faculty_id=%s
            AND day=%s
            AND timetable_id != %s
            AND (
                (start_time < %s AND end_time > %s)
            )
        """, (faculty_id, day, slot_id, end_time, start_time))
        conflict = cursor.fetchone()
        if conflict:
             flash("Time conflict detected! Faculty is already booked for this slot.", "error")
             db.close()
             return redirect(url_for('admin.manage_timetable'))
             
    try:
        cursor.execute("""
            UPDATE timetable 
            SET course_id=%s, faculty_id=%s, day=%s, start_time=%s, end_time=%s, classroom=%s, department=%s, semester=%s
            WHERE timetable_id=%s
        """, (course_id, faculty_id, day, start_time, end_time, classroom, dept, semester, slot_id))
        db.commit()
        flash("Schedule updated successfully.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error updating schedule: {e}", "error")
        
    db.close()
    return redirect(url_for('admin.manage_timetable'))

@admin_bp.route('/admin/delete-all-timetable')
@login_required
def delete_all_timetable():
    if not session.get('is_admin'):
        abort(403)
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM timetable")
        db.commit()
        flash("All timetable records have been cleared.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error clearing timetable: {e}", "error")
    db.close()
    return redirect(url_for('admin.manage_timetable'))

@admin_bp.route('/admin/Duty Leave')
@login_required
def admin_onduty():
    if not session.get('is_admin'):
        abort(403)
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT od.*, s.name as student_name, s.register_number, s.department, s.semester, 
               e.event_name, e.event_date, e.start_time, e.end_time
        FROM onduty_requests od
        JOIN student s ON od.student_id = s.student_id
        JOIN events e ON od.event_id = e.event_id
        ORDER BY od.request_date DESC
    """)
    requests = cursor.fetchall()
    
    from utils.helpers import get_missed_subjects # Import locally if needed or add at top
    from datetime import timedelta
    for req in requests:
        for key in ('start_time', 'end_time'):
            val = req[key]
            if isinstance(val, timedelta):
                total = int(val.total_seconds())
                req[key] = f"{total // 3600:02d}:{(total % 3600) // 60:02d}"
            elif val:
                req[key] = str(val)[:5] # take HH:MM
        
        # Calculate missed subjects dynamically for more clarity
        req['missed_subjects'] = get_missed_subjects(req['student_id'], req['event_id'])

    # Pass all timetable slots so admin can pick the period in the modal
    cursor.execute("""
        SELECT t.timetable_id, t.day, t.start_time, t.end_time, t.department, t.semester,
               c.course_name
        FROM timetable t
        LEFT JOIN courses c ON t.course_id = c.course_id
        ORDER BY FIELD(t.day,'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'), t.start_time
    """)
    timetable_slots = cursor.fetchall()
    # Convert timedelta to HH:MM strings for safe JS use
    for slot in timetable_slots:
        for key in ('start_time', 'end_time'):
            val = slot[key]
            if isinstance(val, timedelta):
                total = int(val.total_seconds())
                slot[key] = f"{total // 3600:02d}:{(total % 3600) // 60:02d}"
            else:
                slot[key] = str(val)
        slot['course_name'] = slot['course_name'] or 'N/A'
    db.close()
    return render_template('admin_onduty.html', requests=requests, timetable_slots=timetable_slots)

@admin_bp.route('/admin/duty-leave/respond/<int:req_id>/<string:action>', methods=['GET', 'POST'])
@login_required
def approve_onduty(req_id, action):
    if not session.get('is_admin'):
        abort(403)

    new_status = 'Approved' if action == 'approve' else 'Rejected'
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT od.student_id, od.event_id, e.event_name, e.event_date
            FROM onduty_requests od
            JOIN events e ON od.event_id = e.event_id
            WHERE od.request_id = %s
        """, (req_id,))
        req_details = cursor.fetchone()

        if new_status == 'Approved' and request.method == 'POST' and req_details:
            # Receive multiple timetable IDs as a list
            selected_ids = request.form.getlist('timetable_id')
            od_date = request.form.get('od_date') or str(req_details['event_date'])

            # Store selected IDs (optional, but keep for record integrity)
            ids_str = ",".join(selected_ids) if selected_ids else None

            cursor.execute("""
                UPDATE onduty_requests
                SET status=%s, approved_by=%s, timetable_id=%s, od_date=%s
                WHERE request_id=%s
            """, (new_status, session['user_id'], ids_str, od_date, req_id))

            # Auto-mark student Present for ALL chosen periods
            for sid in selected_ids:
                cursor.execute("""
                    INSERT INTO daily_attendance (timetable_id, student_id, attendance_date, status)
                    VALUES (%s, %s, %s, 'Present')
                    ON DUPLICATE KEY UPDATE status = 'Present'
                """, (sid, req_details['student_id'], od_date))
        else:
            cursor.execute(
                "UPDATE onduty_requests SET status=%s, approved_by=%s WHERE request_id=%s",
                (new_status, session['user_id'], req_id)
            )

        if req_details:
            msg = f"Your Duty Leave request for event '{req_details['event_name']}' has been {new_status} by Admin."
            add_notification(req_details['student_id'], 'student', msg)
        db.commit()
        flash(f"Request {new_status}.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error updating request: {e}", "error")
    db.close()
    return redirect(url_for('admin.admin_onduty'))



@admin_bp.route('/admin/certificates')
@login_required
def admin_certificates():
    if not session.get('is_admin'):
        abort(403)
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    # Fetch Pending
    cursor.execute("""
        SELECT r.registration_id, r.certificate_status, s.name as student_name, e.event_name, e.event_date
        FROM registrations r
        JOIN student s ON r.student_id = s.student_id
        JOIN events e ON r.event_id = e.event_id
        WHERE r.certificate_status = 'Pending'
        ORDER BY e.event_date DESC
    """)
    pending_certs = cursor.fetchall()

    # Fetch Approved
    cursor.execute("""
        SELECT r.registration_id, r.certificate_status, s.name as student_name, e.event_name, e.event_date
        FROM registrations r
        JOIN student s ON r.student_id = s.student_id
        JOIN events e ON r.event_id = e.event_id
        WHERE r.certificate_status = 'Approved'
        ORDER BY e.event_date DESC
    """)
    approved_certs = cursor.fetchall()
    
    db.close()
    return render_template('admin_certificates.html', pending_certs=pending_certs, approved_certs=approved_certs)

@admin_bp.route('/admin/approve-certificate/<int:reg_id>')
@login_required
def approve_certificate(reg_id):
    if not session.get('is_admin'):
        abort(403)
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("UPDATE registrations SET certificate_status='Approved' WHERE registration_id=%s", (reg_id,))
        db.commit()
        cursor.execute("SELECT student_id FROM registrations WHERE registration_id=%s", (reg_id,))
        res = cursor.fetchone()
        if res:
             add_notification(res['student_id'], 'student', "Your certificate has been approved! Download it now.")
        flash("Certificate approved successfully!", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error approving certificate: {e}", "error")
    db.close()
    return redirect(url_for('admin.admin_certificates'))

@admin_bp.route('/admin/toggle-event-status/<int:event_id>/<string:new_status>')
@login_required
def toggle_event_status(event_id, new_status):
    if not session.get('is_admin'):
        abort(403)
    
    if new_status not in ['Open', 'Closed']:
        flash("Invalid status.", "error")
        return redirect(url_for('public.events'))
        
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE events SET status=%s WHERE event_id=%s", (new_status, event_id))
        db.commit()
        flash(f"Event registration is now {new_status}.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error updating status: {e}", "error")
    db.close()
    
    return redirect(url_for('public.events'))
@admin_bp.route('/admin/event-attendance')
@login_required
def event_attendance_list():
    if not (session.get('is_admin') or session.get('role') == 'faculty'):
        abort(403)
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    # Get summary of attendance for all events
    cursor.execute("""
        SELECT e.event_id, e.event_name, e.event_date, e.event_type, e.department,
               COUNT(r.registration_id) as total_registered,
               COALESCE(SUM(CASE WHEN r.attendance = 'Present' THEN 1 ELSE 0 END), 0) as present_count
        FROM events e
        LEFT JOIN registrations r ON e.event_id = r.event_id
        GROUP BY e.event_id, e.event_name
        ORDER BY e.event_date DESC
    """)
    event_records = cursor.fetchall()
    db.close()
    return render_template('admin_event_attendance.html', event_records=event_records)

@admin_bp.route('/admin/daily-attendance')
@login_required
def daily_attendance_list():
    if not session.get('is_admin'):
        abort(403)
        
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    from datetime import datetime
    selected_date_str = request.args.get('date')
    if selected_date_str:
        try:
            target_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
        except:
            target_date = datetime.now().date()
    else:
        target_date = datetime.now().date()
        
    day_name = target_date.strftime('%A')
    
    # Get summary of sessions where attendance has been marked
    cursor.execute("""
        SELECT da.attendance_date, da.timetable_id, t.start_time, t.end_time, t.day,
               c.course_name, c.department, c.semester, f.name as faculty_name,
               COUNT(da.student_id) as total_students,
               SUM(CASE WHEN da.status = 'Present' THEN 1 ELSE 0 END) as present_count
        FROM daily_attendance da
        JOIN timetable t ON da.timetable_id = t.timetable_id
        JOIN courses c ON t.course_id = c.course_id
        JOIN faculty f ON t.faculty_id = f.faculty_id
        GROUP BY da.attendance_date, da.timetable_id
        ORDER BY da.attendance_date DESC, t.start_time
    """)
    attendance_records = cursor.fetchall()

    # Get slots for the SELECTED date so admin can mark them
    cursor.execute("""
        SELECT t.*, c.course_name, c.department, c.semester, f.name as faculty_name 
        FROM timetable t 
        JOIN courses c ON t.course_id = c.course_id 
        JOIN faculty f ON t.faculty_id = f.faculty_id
        WHERE t.day = %s
        ORDER BY t.start_time
    """, (day_name,))
    slots_for_date = cursor.fetchall()
    
    db.close()
    return render_template('admin_attendance_list.html', 
                           records=attendance_records, 
                           today_slots=slots_for_date, 
                           today_date=target_date)

@admin_bp.route('/admin/view-attendance/<int:timetable_id>/<string:date>')
@login_required
def view_attendance_detail(timetable_id, date):
    if not session.get('is_admin'):
        abort(403)
        
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    # Get slot details
    cursor.execute("""
        SELECT t.*, c.course_name, c.department, c.semester, f.name as faculty_name
        FROM timetable t
        JOIN courses c ON t.course_id = c.course_id
        JOIN faculty f ON t.faculty_id = f.faculty_id
        WHERE t.timetable_id = %s
    """, (timetable_id,))
    slot = cursor.fetchone()
    
    if not slot:
        db.close()
        abort(404)
        
    # Get detailed student list for that date
    cursor.execute("""
        SELECT s.name, s.register_number, da.status, s.student_id
        FROM daily_attendance da
        JOIN student s ON da.student_id = s.student_id
        WHERE da.timetable_id = %s AND da.attendance_date = %s
        ORDER BY s.name
    """, (timetable_id, date))
    students = cursor.fetchall()

    if not students:
        # Fetch all eligible students for this course if marks haven't been made yet
        cursor.execute("""
            SELECT name, register_number, 'Absent' as status, student_id
            FROM student
            WHERE department = %s AND semester = %s
            AND register_number LIKE 'NIE23CS%'
            ORDER BY name
        """, (slot['department'], slot['semester']))
        students = cursor.fetchall()
        is_new = True
    else:
        is_new = False
    
    db.close()
    return render_template('admin_view_attendance.html', slot=slot, students=students, date=date, is_new=is_new)

@admin_bp.route('/admin/edit-attendance/<int:timetable_id>/<string:date>', methods=['POST'])
@login_required
def edit_attendance(timetable_id, date):
    if not session.get('is_admin'):
        abort(403)
        
    present_students = request.form.getlist('students') # IDs of students checked as present
    
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    # Get all students who SHOULD have been in this class (based on existing records for this date/slot)
    cursor.execute("SELECT student_id FROM daily_attendance WHERE timetable_id = %s AND attendance_date = %s", (timetable_id, date))
    recorded_students = [s['student_id'] for s in cursor.fetchall()]
    
    try:
        # Get all students for this course to ensure we mark everyone (either present or absent)
        cursor.execute("""
            SELECT student_id FROM student 
            WHERE department = (SELECT department FROM courses WHERE course_id = (SELECT course_id FROM timetable WHERE timetable_id = %s))
            AND semester = (SELECT semester FROM courses WHERE course_id = (SELECT course_id FROM timetable WHERE timetable_id = %s))
            AND register_number LIKE 'NIE23CS%%'
        """, (timetable_id, timetable_id))
        all_students = [s['student_id'] for s in cursor.fetchall()]

        for s_id in all_students:
            status = 'Present' if str(s_id) in present_students else 'Absent'
            cursor.execute("""
                INSERT INTO daily_attendance (timetable_id, student_id, attendance_date, status)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE status = VALUES(status)
            """, (timetable_id, s_id, date, status))
        
        db.commit()
        flash("Attendance saved successfully!", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error saving attendance: {e}", "error")
        
    db.close()
    return redirect(url_for('admin.view_attendance_detail', timetable_id=timetable_id, date=date))

@admin_bp.route('/admin/delete-attendance/<int:timetable_id>/<string:date>')
@login_required
def delete_attendance(timetable_id, date):
    if not session.get('is_admin'):
        abort(403)

    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            "DELETE FROM daily_attendance WHERE timetable_id = %s AND attendance_date = %s",
            (timetable_id, date)
        )
        db.commit()
        flash(f"Attendance records for {date} deleted successfully.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error deleting attendance: {e}", "error")
    db.close()
    return redirect(url_for('admin.daily_attendance_list'))

@admin_bp.route('/admin/bulk-add-timetable', methods=['POST'])
@login_required
def bulk_add_timetable():
    from flask import jsonify
    if not session.get('is_admin'):
        return jsonify({"success": False, "error": "Unauthorized"}), 403
        
    data = request.get_json()
    if not data or 'slots' not in data:
        return jsonify({"success": False, "error": "Invalid data"}), 400
        
    db = get_db_connection()
    cursor = db.cursor()
    
    try:
        for slot in data['slots']:
            cursor.execute("""
                INSERT INTO timetable (course_id, faculty_id, day, start_time, end_time, classroom, department, semester)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (slot['course_id'], slot['faculty_id'], slot['day'], slot['start_time'], slot['end_time'], slot['classroom'], slot.get('department'), slot.get('semester')))
        
        db.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()

@admin_bp.route('/admin/bulk-update-timetable', methods=['POST'])
@login_required
def bulk_update_timetable():
    from flask import jsonify
    if not session.get('is_admin'):
        return jsonify({"success": False, "error": "Unauthorized"}), 403
        
    data = request.get_json()
    if not data or 'slots' not in data:
        return jsonify({"success": False, "error": "Invalid data"}), 400
        
    db = get_db_connection()
    cursor = db.cursor()
    
    try:
        for slot in data['slots']:
            # For each day selected, find if a slot exists at this exact time for this dept/sem
            # If yes, update it. If not, create it.
            dept = slot.get('department')
            sem = slot.get('semester')
            
            cursor.execute("""
                SELECT timetable_id FROM timetable 
                WHERE day=%s AND start_time=%s AND end_time=%s AND department=%s AND semester=%s
            """, (slot['day'], slot['start_time'], slot['end_time'], dept, sem))
            existing = cursor.fetchone()
            
            if existing:
                cursor.execute("""
                    UPDATE timetable 
                    SET course_id=%s, faculty_id=%s, classroom=%s
                    WHERE timetable_id=%s
                """, (slot['course_id'], slot['faculty_id'], slot['classroom'], existing[0]))
            else:
                cursor.execute("""
                    INSERT INTO timetable (course_id, faculty_id, day, start_time, end_time, classroom, department, semester)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (slot['course_id'], slot['faculty_id'], slot['day'], slot['start_time'], slot['end_time'], slot['classroom'], dept, sem))
        
        db.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()
