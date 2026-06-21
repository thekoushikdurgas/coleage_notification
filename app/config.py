import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'formsadda-secret-key-12345')
    
    # Database configuration: use PostgreSQL if DATABASE_URL is set, otherwise fallback to SQLite
    BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR, 'formsadda.db')}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # API key for real LLM integration if provided (otherwise mock will be used)
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    
    # Path to Excel input
    EXCEL_FILE_PATH = os.path.join(BASE_DIR, 'inputs', 'College-ALL COLLEGE.xlsx')
