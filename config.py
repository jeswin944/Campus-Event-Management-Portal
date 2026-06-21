import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "campus_event_secret_key")
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
