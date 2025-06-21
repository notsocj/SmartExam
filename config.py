import os

# Base directory of the application
basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'development-secret-key'
    # Create a database directory if it doesn't exist
    DB_DIR = os.path.join(basedir, 'database')
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)
    # SQLite database path
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        f'sqlite:///{os.path.join(DB_DIR, "smartexam.db")}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Session configuration for multi-user support
    SESSION_TYPE = 'filesystem'
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True
    SESSION_KEY_PREFIX = 'smartexam:'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # File upload settings
    UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads')
    LEARNING_RESOURCES_FOLDER = os.path.join(UPLOAD_FOLDER, 'learning_resources')
    MAX_CONTENT_LENGTH = 1024 * 1024 * 1024  # 1GB max file size
    
    # Performance settings for concurrent access
    SEND_FILE_MAX_AGE_DEFAULT = 300
    THREADED = True
    
    # Create upload directories if they don't exist
    for folder in [UPLOAD_FOLDER, LEARNING_RESOURCES_FOLDER]:
        if not os.path.exists(folder):
            os.makedirs(folder)
    
class DevelopmentConfig(Config):
    DEBUG = True
    
class ProductionConfig(Config):
    DEBUG = False
    # More secure secret key requirement for production
    SECRET_KEY = os.environ.get('SECRET_KEY')
    
# Configuration dictionary for easy switching between environments
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
