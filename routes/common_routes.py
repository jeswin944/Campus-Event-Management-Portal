from flask import Blueprint, session
from models.db import get_db_connection
from utils.helpers import login_required

common_bp = Blueprint('common', __name__)

@common_bp.route('/get-notifications')
@login_required
def get_notifications():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT * FROM notifications 
        WHERE user_id = %s AND user_role = %s 
        ORDER BY created_at DESC LIMIT 20
    """, (session['user_id'], session['role']))
    notes = cursor.fetchall()
    
    cursor.execute("""
        UPDATE notifications SET is_read = 1 
        WHERE user_id = %s AND user_role = %s
    """, (session['user_id'], session['role']))
    db.commit()
    db.close()
    
    return {'notifications': notes}
