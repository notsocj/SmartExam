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
        f'sqlite:///{os.path.join(DB_DIR, "walo.db")}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
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
