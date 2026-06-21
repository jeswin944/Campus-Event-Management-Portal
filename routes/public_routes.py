from flask import Blueprint, render_template, session, request
from models.db import get_db_connection

public_bp = Blueprint('public', __name__)

@public_bp.route('/')
def home():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    if session.get('role') == 'student':
        cursor.execute("""
            SELECT e.*, 
            CASE WHEN r.registration_id IS NOT NULL THEN 1 ELSE 0 END as is_registered
            FROM events e
            LEFT JOIN registrations r ON e.event_id = r.event_id AND r.student_id = %s
            WHERE e.is_announced = 1 AND (e.department = 'All' OR e.department = %s)
            ORDER BY e.event_date
        """, (session['user_id'], session.get('department', '')))
    elif session.get('role') == 'faculty' or session.get('is_admin'):
        cursor.execute("SELECT * FROM events WHERE is_announced = 1 ORDER BY event_date")
    else:
        cursor.execute("SELECT * FROM events WHERE is_announced = 1 AND department = 'All' ORDER BY event_date")
    
    events = cursor.fetchall()
    db.close()
    return render_template('index.html', events=events)

@public_bp.route('/events')
def events():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    # Pagination Logic
    page = request.args.get('page', 1, type=int)
    per_page = 6
    offset = (page - 1) * per_page
    
    # Get total count
    # Fetch subset based on role
    if session.get('is_admin') or session.get('role') == 'faculty':
        cursor.execute("SELECT COUNT(*) as total FROM events")
        total_events = cursor.fetchone()['total']
        total_pages = (total_events + per_page - 1) // per_page if total_events else 1
        cursor.execute("SELECT e.*, f.name as coordinator_name FROM events e LEFT JOIN faculty f ON e.coordinator_id = f.faculty_id ORDER BY e.event_date DESC LIMIT %s OFFSET %s", (per_page, offset))
    elif session.get('role') == 'student':
        cursor.execute("SELECT COUNT(*) as total FROM events WHERE is_announced = 1 AND (department = 'All' OR department = %s)", (session.get('department', ''),))
        total_events = cursor.fetchone()['total']
        total_pages = (total_events + per_page - 1) // per_page if total_events else 1
        cursor.execute("""
            SELECT e.*, f.name as coordinator_name,
            CASE WHEN r.registration_id IS NOT NULL THEN 1 ELSE 0 END as is_registered,
            CASE WHEN w.waitlist_id IS NOT NULL THEN 1 ELSE 0 END as is_waitlisted
            FROM events e 
            LEFT JOIN faculty f ON e.coordinator_id = f.faculty_id 
            LEFT JOIN registrations r ON e.event_id = r.event_id AND r.student_id = %s
            LEFT JOIN waitlist w ON e.event_id = w.event_id AND w.student_id = %s
            WHERE e.is_announced = 1 AND (e.department = 'All' OR e.department = %s) 
            ORDER BY e.event_date DESC LIMIT %s OFFSET %s
        """, (session['user_id'], session['user_id'], session.get('department', ''), per_page, offset))
    else:
        cursor.execute("SELECT COUNT(*) as total FROM events WHERE is_announced = 1 AND department = 'All'")
        total_events = cursor.fetchone()['total']
        total_pages = (total_events + per_page - 1) // per_page if total_events else 1
        cursor.execute("SELECT e.*, f.name as coordinator_name FROM events e LEFT JOIN faculty f ON e.coordinator_id = f.faculty_id WHERE e.is_announced = 1 AND e.department = 'All' ORDER BY e.event_date DESC LIMIT %s OFFSET %s", (per_page, offset))
    events = cursor.fetchall()
    
    # Calculate Deadline Status
    from datetime import datetime, timedelta
    current_date = datetime.now().date()
    
    for event in events:
        e_date = event['event_date']
        if isinstance(e_date, str):
            e_date = datetime.strptime(e_date, '%Y-%m-%d').date()
            
        # Deadline is 2 days before event
        # If today is 18th, event is 20th. 20-18=2. Allowed.
        # If today is 19th, event is 20th. 20-19=1. Blocked.
        if (e_date - current_date).days < 2:
            event['deadline_passed'] = True
        else:
            event['deadline_passed'] = False
            
        # Format Time for display
        def format_t(t):
            if not t: return None
            from datetime import time, timedelta
            if isinstance(t, timedelta):
                total = int(t.total_seconds())
                return time(total // 3600 % 24, (total % 3600) // 60).strftime('%I:%M %p')
            if isinstance(t, str):
                try:
                    return datetime.strptime(t, '%H:%M:%S').strftime('%I:%M %p')
                except:
                    try: return datetime.strptime(t, '%H:%M').strftime('%I:%M %p')
                    except: return t
            return t
        
        def format_iso(t):
            if not t: return ''
            from datetime import timedelta
            if isinstance(t, timedelta):
                total = int(t.total_seconds())
                h = (total // 3600) % 24
                m = (total % 3600) // 60
                return f"{h:02d}:{m:02d}"
            s = str(t)
            if len(s) > 5: return s[:5] # HH:MM:SS -> HH:MM
            return s
            
        event['start_time_display'] = format_t(event['start_time'])
        event['end_time_display'] = format_t(event['end_time'])
        event['start_time'] = format_iso(event['start_time'])
        event['end_time'] = format_iso(event['end_time'])

    # Tagging Logic: Recommended (Interest+Dept) and Trending (High Regs)
    cursor.execute("""
        SELECT e.event_id, e.event_date, e.points_awarded, e.event_name, e.description, e.department,
        (SELECT COUNT(*) FROM registrations r WHERE r.event_id = e.event_id) as reg_count
        FROM events e WHERE e.is_announced = 1
    """)
    all_active = cursor.fetchall()

    # Get user context for personalized recommendations
    student_interests = []
    user_dept = session.get('department', 'All')
    if session.get('role') == 'student':
        cursor.execute("SELECT interests FROM student WHERE student_id=%s", (session['user_id'],))
        row = cursor.fetchone()
        if row and row['interests']:
            student_interests = [i.strip().lower() for i in row['interests'].split(',') if i.strip()]

    # Calculating logic sets
    # Trending: top registration counts
    trend_ids = [e['event_id'] for e in sorted(all_active, key=lambda x: x['reg_count'], reverse=True)[:5]]
    
    # Recommended: Personalized Score (Dept weight + Interest keywords)
    for e in all_active:
        score = 0
        if e['department'] == user_dept and user_dept != 'All':
            score += 20
        # Interest keyword matching
        for interest in student_interests:
            if interest in e['event_name'].lower() or (e['description'] and interest in e['description'].lower()):
                score += 10
        # Points boost
        score += (e['points_awarded'] or 0) / 5
        e['match_score'] = score
    
    rec_ids = [e['event_id'] for e in sorted(all_active, key=lambda x: x['match_score'], reverse=True)[:5] if e['match_score'] > 0]
    
    # Upcoming: Chronological soonest
    future_events = [e for e in all_active if e['event_date'] and str(e['event_date']) >= str(current_date)]
    upc_ids = [e['event_id'] for e in sorted(future_events, key=lambda x: str(x['event_date']))[:5]]

    for event in events:
        event['is_recommended'] = event['event_id'] in rec_ids
        event['is_trending'] = event['event_id'] in trend_ids
        event['is_upcoming'] = event['event_id'] in upc_ids

    faculty_list = []
    if session.get('is_admin'):
        cursor.execute("SELECT faculty_id, name, department FROM faculty ORDER BY name")
        faculty_list = cursor.fetchall()

    db.close()
    return render_template('events.html', events=events, page=page, total_pages=total_pages, faculty_list=faculty_list)
@public_bp.route('/maintenance')
def maintenance():
    return render_template('status.html',
                          title="Maintenance Underway",
                          message="We are currently performing some scheduled upgrades to improve your experience. Please try again later.",
                          icon="fa-tools",
                          is_maintenance=True)
