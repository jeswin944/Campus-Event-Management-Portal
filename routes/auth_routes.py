from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from werkzeug.security import check_password_hash, generate_password_hash
from models.db import get_db_connection
from services.email_service import send_email
from utils.helpers import login_required
import time
import random
import string
from datetime import datetime, timedelta
import os

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        if session.get('role') == 'student':
            return redirect(url_for('student.student_dashboard'))
        elif session.get('role') == 'faculty':
            if session.get('is_admin'):
                return redirect(url_for('admin.admin_dashboard'))
            return redirect(url_for('faculty.faculty_dashboard'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        login_role = request.form.get('login_role', 'student')

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        if login_role == 'faculty':
            # 1. Check FACULTY (using email)
            cursor.execute("SELECT * FROM faculty WHERE email=%s", (username,))
            faculty_user = cursor.fetchone()

            if faculty_user and check_password_hash(faculty_user['password'], password):
                # CHECK MAINTENANCE MODE
                if os.path.exists('.maintenance') and not faculty_user.get('is_admin'):
                    return redirect(url_for('public.maintenance'))

                session['user_id'] = faculty_user['faculty_id']
                session['role'] = 'faculty'
                session['is_admin'] = (faculty_user['is_admin'] == 1)
                session['name'] = faculty_user['name']
                db.close()
                
                if session['is_admin']:
                    return redirect(url_for('admin.admin_dashboard'))
                return redirect(url_for('faculty.faculty_dashboard'))

        elif login_role == 'student':
            # 2. Check STUDENT (using register_number)
            cursor.execute("SELECT * FROM student WHERE register_number=%s", (username,))
            student_user = cursor.fetchone()

            if student_user and check_password_hash(student_user['password'], password):
                # CHECK MAINTENANCE MODE
                if os.path.exists('.maintenance'):
                    return redirect(url_for('public.maintenance'))

                session['user_id'] = student_user['student_id']
                session['role'] = 'student'
                session['is_admin'] = False
                session['name'] = student_user['name']
                session['register_number'] = student_user['register_number']
                session['is_nie23cs'] = student_user['register_number'].upper().startswith('NIE23CS')
                session['email'] = student_user['email']
                session['department'] = student_user['department']
                session['semester'] = student_user['semester']
                db.close()
                return redirect(url_for('student.student_dashboard'))

        db.close()
        flash("Invalid credentials", "error")
        return redirect(url_for('auth.login'))

    registration_closed = os.path.exists('.registration_closed')
    return render_template('login.html', registration_closed=registration_closed)

@auth_bp.route('/register-user', methods=['POST'])
def register_user():
    if os.path.exists('.registration_closed'):
        flash("New student registrations are currently closed.", "error")
        return redirect(url_for('auth.login'))

    role = request.form.get('role', 'student')
    if role != 'student':
        flash("Only student registration is allowed here.", "error")
        return redirect(url_for('auth.login'))

    name = request.form['name']
    email = request.form['email']
    department = request.form['department']
    password = request.form['password']
    confirm = request.form['confirm_password']

    if password != confirm:
        flash("Passwords do not match", "error")
        return redirect(url_for('auth.login'))

    hashed = generate_password_hash(password)

    if not request.form.get('reg_no'):
        flash("Register Number is required for Students", "error")
        return redirect(url_for('auth.login'))
    username = request.form['reg_no'].strip()

    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT student_id FROM student WHERE register_number=%s", (username,))
        if cursor.fetchone():
             db.close()
             flash("Student already registered (Check Reg No)", "error")
             return redirect(url_for('auth.login'))

        cursor.execute("""
            INSERT INTO student (name, register_number, email, department, semester, password)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (name, username, email, department, request.form['semester'], hashed))

        db.commit()
        db.close()
        flash("Registration successful. Please Login.", "success")
        return redirect(url_for('auth.login'))

    except Exception as e:
        flash(str(e), "error")
        return redirect(url_for('auth.login'))

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))

@auth_bp.route('/change-password', methods=['POST'])
@login_required # Imported from utils.helpers
def change_password():
    current_password = request.form['current_password']
    new_password = request.form['new_password']
    confirm_password = request.form['confirm_password']
    
    if new_password != confirm_password:
        flash("New passwords do not match.", "error")
        return redirect(request.referrer)
        
    table = 'faculty' if session['role'] == 'faculty' else 'student'
    id_col = 'faculty_id' if session['role'] == 'faculty' else 'student_id'
    
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute(f"SELECT password FROM {table} WHERE {id_col}=%s", (session['user_id'],))
    user = cursor.fetchone()
    
    if not user or not check_password_hash(user['password'], current_password):
        db.close()
        flash("Incorrect current password.", "error")
        return redirect(request.referrer)
        
    hashed = generate_password_hash(new_password)
    cursor.execute(f"UPDATE {table} SET password=%s WHERE {id_col}=%s", (hashed, session['user_id']))
    db.commit()
    db.close()
    
    flash("Password changed successfully.", "success")
    return redirect(request.referrer)

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email'].strip()
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        user = None
        role = None
        user_id = None

        cursor.execute("SELECT faculty_id, name, email FROM faculty WHERE email=%s", (email,))
        faculty_user = cursor.fetchone()
        if faculty_user:
            user = faculty_user
            role = 'faculty'
            user_id = faculty_user['faculty_id']

        if not user:
            cursor.execute("SELECT student_id, name, email FROM student WHERE email=%s", (email,))
            student_user = cursor.fetchone()
            if student_user:
                user = student_user
                role = 'student'
                user_id = student_user['student_id']

        db.close()

        if user:
            # Generate a 6-digit OTP
            otp = ''.join(random.choices(string.digits, k=6))
            expiry = (datetime.now() + timedelta(minutes=10)).isoformat()

            # Store OTP in session
            session['otp_code']   = otp
            session['otp_expiry'] = expiry
            session['otp_email']  = email
            session['otp_role']   = role
            session['otp_uid']    = user_id

            html_body = f"""
            <div style="font-family:Arial,sans-serif; max-width:480px; margin:auto; padding:32px; background:#f9f9f9; border-radius:12px;">
                <h2 style="color:#4361ee;">&#128274; Password Reset OTP</h2>
                <p>Hello <strong>{user['name']}</strong>,</p>
                <p>We received a request to reset your password. Use the OTP below:</p>
                <div style="text-align:center; margin:24px 0;">
                    <span style="font-size:2.5rem; font-weight:900; letter-spacing:12px; color:#4361ee; background:#e8ecff; padding:12px 24px; border-radius:10px;">{otp}</span>
                </div>
                <p style="color:#888;">This OTP is valid for <strong>10 minutes</strong>.</p>
                <p style="color:#888;">If you did not request this, please ignore this email.</p>
            </div>
            """
            try:
                send_email("Your Password Reset OTP", [email], html=html_body)
                flash(f"A 6-digit OTP has been sent to {email}. It expires in 10 minutes.", "success")
                return redirect(url_for('auth.verify_otp'))
            except Exception as e:
                flash(f"Error sending OTP: {str(e)}", "error")
        else:
            flash("Email not found in our records.", "error")

        return redirect(url_for('auth.forgot_password'))

    return render_template('forgot_password.html')


@auth_bp.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if 'otp_code' not in session:
        flash("Please request a password reset first.", "error")
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        entered = request.form.get('otp', '').strip()
        expiry  = datetime.fromisoformat(session.get('otp_expiry', '2000-01-01'))

        if datetime.now() > expiry:
            session.pop('otp_code', None)
            flash("OTP has expired. Please request a new one.", "error")
            return redirect(url_for('auth.forgot_password'))

        if entered == session.get('otp_code'):
            # OTP matched — allow reset
            session['otp_verified'] = True
            session.pop('otp_code', None)   # consume the OTP
            return redirect(url_for('auth.reset_password'))
        else:
            flash("Invalid OTP. Please try again.", "error")

    return render_template('verify_otp.html')


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    # Must have gone through OTP verification
    if not session.get('otp_verified'):
        flash("Please verify your OTP first.", "error")
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form['password']
        confirm  = request.form['confirm_password']

        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for('auth.reset_password'))

        hashed = generate_password_hash(password)
        role    = session.get('otp_role')
        user_id = session.get('otp_uid')

        db = get_db_connection()
        cursor = db.cursor()
        try:
            if role == 'faculty':
                cursor.execute("UPDATE faculty SET password=%s WHERE faculty_id=%s", (hashed, user_id))
            else:
                cursor.execute("UPDATE student SET password=%s WHERE student_id=%s", (hashed, user_id))
            db.commit()
        except Exception as e:
            db.rollback()
            flash(f"Error resetting password: {e}", "error")
            db.close()
            return redirect(url_for('auth.reset_password'))
        db.close()

        # Clear all OTP session keys
        for k in ['otp_verified', 'otp_role', 'otp_uid', 'otp_email', 'otp_expiry']:
            session.pop(k, None)

        flash("Password has been reset successfully. Please login.", "success")
        return redirect(url_for('auth.login'))

    return render_template('reset_password.html')
