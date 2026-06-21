import mysql.connector
import os

def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="123456",
        database="campus_event_db"
    )
