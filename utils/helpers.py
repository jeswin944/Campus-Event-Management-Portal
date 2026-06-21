from flask import session, redirect, url_for, abort
from functools import wraps
from models.db import get_db_connection

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            # Redirect to login page - assuming 'auth.login' endpoint
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapper

def role_required(role):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if session.get('role') != role:
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator

def add_notification(user_id, role, message):
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO notifications (user_id, user_role, message) 
            VALUES (%s, %s, %s)
        """, (user_id, role, message))
        db.commit()
        db.close()
    except Exception as e:
        print(f"Error adding notification: {e}")

def notify_admins(message):
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT faculty_id FROM faculty WHERE is_admin = 1")
        admins = cursor.fetchall()
        
        cursor_insert = db.cursor()
        for admin in admins:
             cursor_insert.execute("""
                INSERT INTO notifications (user_id, user_role, message) 
                VALUES (%s, 'faculty', %s)
            """, (admin['faculty_id'], message))
        
        db.commit()
        db.close()
    except Exception as e:
        print(f"Error notifying admins: {e}")
def calculate_missed_classes(student_id, event_id):
    try:
        from datetime import datetime, timedelta
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # 1. Fetch Event Info
        cursor.execute("SELECT start_time, end_time, event_date FROM events WHERE event_id=%s", (event_id,))
        event = cursor.fetchone()
        if not event or not event['start_time'] or not event['end_time']:
            db.close()
            return 0
        
        # 2. Fetch Student Timetable
        cursor.execute("""
            SELECT t.start_time, t.end_time
            FROM timetable t
            JOIN student s ON s.student_id=%s
            WHERE t.department = s.department
            AND t.semester = s.semester
            AND t.day = DAYNAME(%s)
        """, (student_id, event['event_date']))
        timetable_slots = cursor.fetchall()
        db.close()

        def to_td(t):
            if hasattr(t, 'total_seconds'): return t
            if isinstance(t, str):
                h, m = map(int, t.split(':')[:2])
                return timedelta(hours=h, minutes=m)
            return t

        e_start = to_td(event['start_time'])
        e_end = to_td(event['end_time'])
        
        missed = 0
        for slot in timetable_slots:
            s_start = to_td(slot['start_time'])
            s_end = to_td(slot['end_time'])
            # Check overlap
            if max(e_start, s_start) < min(e_end, s_end):
                missed += 1
        
        return missed
    except Exception as e:
        print(f"Error calculating missed classes: {e}")
        return 0

def get_missed_slot_ids(student_id, event_id):
    try:
        from datetime import datetime, timedelta
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        cursor.execute("SELECT start_time, end_time, event_date FROM events WHERE event_id=%s", (event_id,))
        event = cursor.fetchone()
        if not event or not event['start_time'] or not event['end_time']:
            db.close()
            return []
        
        cursor.execute("""
            SELECT t.timetable_id, t.start_time, t.end_time
            FROM timetable t
            JOIN student s ON s.student_id=%s
            WHERE t.department = s.department
            AND t.semester = s.semester
            AND t.day = DAYNAME(%s)
        """, (student_id, event['event_date']))
        timetable_slots = cursor.fetchall()
        db.close()

        def to_td(t):
            if hasattr(t, 'total_seconds'): return t
            if isinstance(t, str):
                h, m = map(int, t.split(':')[:2])
                return timedelta(hours=h, minutes=m)
            return t

        e_start = to_td(event['start_time'])
        e_end = to_td(event['end_time'])
        
        missed_ids = []
        for slot in timetable_slots:
            s_start = to_td(slot['start_time'])
            s_end = to_td(slot['end_time'])
            if max(e_start, s_start) < min(e_end, s_end):
                missed_ids.append(slot['timetable_id'])
        
        return missed_ids
    except Exception as e:
        print(f"Error fetching missed slot IDs: {e}")
        return []

def get_missed_subjects(student_id, event_id):
    try:
        from datetime import datetime, timedelta
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # 1. Fetch Event Info
        cursor.execute("SELECT start_time, end_time, event_date FROM events WHERE event_id=%s", (event_id,))
        event = cursor.fetchone()
        if not event or not event['start_time'] or not event['end_time']:
            db.close()
            return []
        
        # 2. Fetch Student Timetable with Course Names
        cursor.execute("""
            SELECT t.start_time, t.end_time, c.course_name
            FROM timetable t
            JOIN student s ON s.student_id=%s
            JOIN courses c ON t.course_id = c.course_id
            WHERE t.department = s.department
            AND t.semester = s.semester
            AND t.day = DAYNAME(%s)
        """, (student_id, event['event_date']))
        timetable_slots = cursor.fetchall()
        db.close()

        def to_td(t):
            if hasattr(t, 'total_seconds'): return t
            if isinstance(t, str):
                h, m = map(int, t.split(':')[:2])
                return timedelta(hours=h, minutes=m)
            return t

        e_start = to_td(event['start_time'])
        e_end = to_td(event['end_time'])
        
        missed_subs = []
        for slot in timetable_slots:
            s_start = to_td(slot['start_time'])
            s_end = to_td(slot['end_time'])
            # Check overlap
            if max(e_start, s_start) < min(e_end, s_end):
                missed_subs.append(slot['course_name'])
        
        return missed_subs
    except Exception as e:
        print(f"Error fetching missed subjects: {e}")
        return []
