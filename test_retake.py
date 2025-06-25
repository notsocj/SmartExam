from app import app, db
from models import User, Test, Result, Question
import json

def test_retake_functionality():
    """Test the retake functionality"""
    with app.app_context():
        # Ensure admin user exists
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(name='Admin', username='admin', role='admin', student_id='admin')
            admin.set_password('admin')
            db.session.add(admin)
            db.session.commit()
            print("Created admin user: username=admin, password=admin")
        else:
            print("Admin user already exists")
        
        # Create a test student if doesn't exist
        student = User.query.filter_by(username='test_student').first()
        if not student:
            student = User(name='Test Student', username='test_student', role='student', student_id='test_student')
            student.set_password('password')
            db.session.add(student)
            db.session.commit()
            print("Created test student: username=test_student, password=password")
        
        # Create a sample test if doesn't exist
        test = Test.query.filter_by(title='Sample Retake Test').first()
        if not test:
            test = Test(title='Sample Retake Test', description='Test for retake functionality', time_limit=30)
            db.session.add(test)
            db.session.flush()
            
            # Add a sample question
            question = Question(
                test_id=test.id,
                question_text='What is 2+2?',
                question_type='identification',
                correct_answer='4'
            )
            db.session.add(question)
            db.session.commit()
            print("Created sample test with question")
        
        # Create a sample result to test retake functionality
        existing_result = Result.query.filter_by(user_id=student.id, test_id=test.id).first()
        if not existing_result:
            result_data = {
                '1': {
                    'question_text': 'What is 2+2?',
                    'question_type': 'identification',
                    'user_answer': '3',
                    'correct_answer': '4',
                    'is_correct': False
                }
            }
            
            result = Result(
                user_id=student.id,
                test_id=test.id,
                score=0.0,
                raw_data=json.dumps(result_data),
                can_retake=False
            )
            db.session.add(result)
            db.session.commit()
            print("Created sample result for testing retake functionality")
        
        print("\nRetake functionality test setup complete!")
        print("1. Login as admin (username: admin, password: admin)")
        print("2. Go to dashboard and enable retake for the test student")
        print("3. Login as test_student (username: test_student, password: password)")
        print("4. Take the retake test and verify old result is replaced")

if __name__ == '__main__':
    test_retake_functionality()
