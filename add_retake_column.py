from app import app, db
from models import Result
from sqlalchemy import text

def add_retake_column():
    """Add can_retake column to existing Result table"""
    with app.app_context():
        try:
            # Check if column already exists
            result = db.engine.execute(text("PRAGMA table_info(result)"))
            columns = [row[1] for row in result]
            
            if 'can_retake' not in columns:
                # Add the column
                db.engine.execute(text("ALTER TABLE result ADD COLUMN can_retake BOOLEAN DEFAULT 0 NOT NULL"))
                print("Successfully added can_retake column to Result table")
            else:
                print("can_retake column already exists")
                
        except Exception as e:
            print(f"Error adding column: {e}")

if __name__ == '__main__':
    add_retake_column()
