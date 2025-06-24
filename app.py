"""
SmartExam Flask Application
===========================

Security Features Implemented:
1. Test Session Tracking: Students cannot access learning resources during active tests
2. Session-based Security: Active test sessions stored in Flask sessions
3. Navigation Restrictions: UI elements disabled during test sessions
4. Route Protection: @check_test_session decorator prevents cheating
5. Browser Security: JavaScript prevents back button usage during tests
6. Automatic Cleanup: Test sessions cleared on completion, logout, or abandonment

Test Security Flow:
- Student starts test → session['active_test_id'] is set
- Learning resources routes blocked with @check_test_session
- Navigation UI shows warning instead of learning links
- Test completion/submission → session cleared
- Student can access resources again after test completion
"""

from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, make_response, send_from_directory, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from flask_session import Session
from functools import wraps
from models import db, User, Result, Question, Test, LearningResource, StudentProgress, ResourceFile
from config import config
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from concurrent.futures import ThreadPoolExecutor
import os
import json
import csv
import io

# Get environment configuration
config_name = os.environ.get('FLASK_ENV', 'default')
app = Flask(__name__)
app.config.from_object(config[config_name])

# Configure session for better persistence
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours in seconds
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'smartexam:'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_NAME'] = 'smartexam_session'

# Configure threading for concurrent access
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 300
app.config['THREADED'] = True

# Initialize thread pool for handling concurrent requests - increased for more students
executor = ThreadPoolExecutor(max_workers=25)

# Configure SQLite for better concurrent access
if 'sqlite' in app.config['SQLALCHEMY_DATABASE_URI']:
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    import sqlite3
    
    @event.listens_for(Engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            # Enable WAL mode for better concurrent access
            cursor.execute("PRAGMA journal_mode=WAL")
            # Increase timeout for concurrent access
            cursor.execute("PRAGMA busy_timeout=30000")
            # Optimize for concurrent reads
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=10000")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.close()

# Initialize database
db.init_app(app)

# Initialize Flask-Migrate
migrate = Migrate(app, db)

# Initialize login manager with better session protection
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.session_protection = "basic"  # Changed from "strong" to "basic"
login_manager.remember_cookie_duration = None
login_manager.login_message = "Please log in to access this page"
login_manager.login_message_category = "info"

# Initialize Flask-Session after app configuration
Session(app)

# Security decorator to check if student is currently taking a test
def check_test_session(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_authenticated and current_user.role == 'student':
            # Check if student has an active test session
            if 'active_test_id' in session:
                flash('You cannot access this page while taking a test. Please complete your current test first.', 'error')
                return redirect(url_for('take_test', test_id=session['active_test_id']))
        return f(*args, **kwargs)
    return decorated_function

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Custom Jinja filter to convert JSON strings to Python objects
@app.template_filter('from_json')
def from_json(value):
    return json.loads(value) if value else []

# Role-based access control decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Admin access required')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            # Set session as permanent and login user
            session.permanent = True
            login_user(user, remember=True, duration=timedelta(seconds=app.config['PERMANENT_SESSION_LIFETIME']))
            
            # Clear any stale test sessions from previous logins
            session.pop('active_test_id', None)
            session.pop('test_start_time', None)
            
            return redirect(url_for('dashboard'))
        flash('Invalid username or password')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    # Clear any active test session on logout
    session.pop('active_test_id', None)
    session.pop('test_start_time', None)
    logout_user()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
@login_required
@admin_required
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        student_id = request.form.get('student_id')
        password = request.form.get('password')
        role = request.form.get('role', 'student')
        
        # For admin role, student_id can be empty
        if role == 'admin' and not student_id:
            student_id = f"admin_{int(datetime.now().timestamp())}"  # Generate a unique identifier
        
        # Use student_id as username for simplicity
        username = student_id
        
        if User.query.filter_by(username=username).first():
            flash('Username/Student ID already exists')
            return redirect(url_for('register'))
        
        if User.query.filter_by(student_id=student_id).first():
            flash('Student ID already exists')
            return redirect(url_for('register'))
        
        user = User(name=name, student_id=student_id, username=username, role=role)
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        flash('User registered successfully')
        return redirect(url_for('dashboard'))
    
    return render_template('register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    from datetime import datetime
    now = datetime.now()
    
    if current_user.role == 'admin':
        users = User.query.all()
        results = Result.query.all()
        tests = Test.query.all()
        
        # Calculate test statistics
        test_statistics = {}
        for test in tests:
            test_results = Result.query.filter_by(test_id=test.id).all()
            if test_results:
                scores = [result.score for result in test_results]
                test_statistics[test.id] = {
                    'total_students': len(test_results),
                    'average_score': sum(scores) / len(scores),
                    'highest_score': max(scores),
                    'lowest_score': min(scores),
                    'student_results': [
                        {
                            'student_name': result.user.name,
                            'student_id': result.user.student_id,
                            'score': result.score,
                            'date_taken': result.date_taken,
                            'result_id': result.id
                        }
                        for result in sorted(test_results, key=lambda x: x.score, reverse=True)
                    ]
                }
        
        return render_template('dashboard.html', users=users, results=results, tests=tests, test_statistics=test_statistics, now=now)
    else:
        # For students, get their results and available tests
        user_results = Result.query.filter_by(user_id=current_user.id).all()
        
        # Get list of completed test IDs
        completed_test_ids = [result.test_id for result in user_results]
        
        # Count available tests
        available_tests_count = Test.query.count()
        completed_tests_count = len(completed_test_ids)
        
        return render_template('dashboard.html', 
                              user_results=user_results, 
                              now=now,
                              available_tests_count=available_tests_count,
                              completed_tests_count=completed_tests_count)

@app.route('/user/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        user.name = request.form.get('name')
        student_id = request.form.get('student_id')
        
        # Check if student_id exists and is not the current user
        existing_user_with_student_id = User.query.filter_by(student_id=student_id).first()
        if existing_user_with_student_id and existing_user_with_student_id.id != user.id:
            flash('Student ID already exists')
            return redirect(url_for('edit_user', user_id=user_id))
        
        # Set username to be the same as student_id
        username = student_id
        
        # Check if username exists and is not the current user
        existing_user = User.query.filter_by(username=username).first()
        if existing_user and existing_user.id != user.id:
            flash('Username already exists')
            return redirect(url_for('edit_user', user_id=user_id))
            
        user.student_id = student_id
        user.username = username
        user.role = request.form.get('role', 'student')
        
        # Update password if provided
        password = request.form.get('password')
        if password and password.strip():
            user.set_password(password)
        
        db.session.commit()
        flash('User updated successfully')
        return redirect(url_for('dashboard'))
    
    return render_template('edit_user.html', user=user)

@app.route('/user/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    try:
        user = User.query.get_or_404(user_id)
        
        # Prevent deleting yourself
        if user.id == current_user.id:
            flash('You cannot delete your own account', 'error')
            return redirect(url_for('dashboard'))
        
        # Store user name for success message
        user_name = user.name
        
        # Delete all results associated with this user first
        results = Result.query.filter_by(user_id=user_id).all()
        for result in results:
            db.session.delete(result)
        
        # Then delete the user
        db.session.delete(user)
        db.session.commit()
        
        flash(f'User "{user_name}" deleted successfully', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while deleting the user. Please try again.', 'error')
    
    return redirect(url_for('dashboard'))

@app.route('/result/<int:result_id>')
@login_required
def view_result(result_id):
    result = Result.query.get_or_404(result_id)
    
    # Only admin or the owner can view their result
    if current_user.role != 'admin' and result.user_id != current_user.id:
        flash('You do not have permission to view this result')
        return redirect(url_for('dashboard'))
    
    # Parse the raw_data JSON to display question details
    result_data = json.loads(result.raw_data) if result.raw_data else {}
    
    return render_template('result.html', result=result, result_data=result_data)

@app.route('/export_result_csv/<int:result_id>')
@login_required
def export_result_csv(result_id):
    result = Result.query.get_or_404(result_id)
    
    # Only admin or the owner can export their result
    if current_user.role != 'admin' and result.user_id != current_user.id:
        flash('You do not have permission to export this result')
        return redirect(url_for('dashboard'))
    
    # Get all results for this user
    user_results = Result.query.filter_by(user_id=result.user_id).order_by(Result.date_taken.desc()).all()
    
    # Create CSV content
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Find the maximum number of questions across all tests to create consistent columns
    max_questions = 0
    all_test_data = {}
    
    for user_result in user_results:
        if user_result.raw_data:
            result_data = json.loads(user_result.raw_data)
            all_test_data[user_result.id] = result_data
            max_questions = max(max_questions, len(result_data))
      # Create header row
    header = ['Timestamp', 'Student Name', 'Student ID', 'Test Name', 'Score']
    
    # Add question columns for maximum questions found
    for i in range(1, max_questions + 1):
        header.append(f'Q{i}')
    
    # Add summary columns
    header.extend(['Total Questions', 'Correct Answers', 'Percentage'])
    
    # Write header
    writer.writerow(header)
      # Write data for each test result
    for user_result in user_results:
        if user_result.raw_data:
            result_data = json.loads(user_result.raw_data)
            correct_count = sum(1 for data in result_data.values() if data.get('is_correct', False))
            total_count = len(result_data)
        else:
            result_data = {}
            correct_count = 0
            total_count = 0
          # Create score string to avoid Excel date formatting - add quotes to prevent date interpretation
        score_text = f'"{correct_count}/{total_count}"' if total_count > 0 else '"0/0"'
        
        # Create data row
        row = [
            user_result.date_taken.strftime('%d/%m/%Y %H:%M'),  # Timestamp
            user_result.user.name,  # Student Name  
            user_result.user.student_id,  # Student ID
            user_result.test.title,  # Test Name
            score_text  # Score (fraction format)
        ]
        
        # Add user answers for each question (fill empty cells for tests with fewer questions)
        for i in range(max_questions):
            if i < len(result_data):
                question_data = list(result_data.values())[i]
                row.append(question_data.get('user_answer', ''))
            else:
                row.append('')  # Empty cell for tests with fewer questions
        
        # Add summary data
        row.extend([
            total_count if total_count > 0 else 'N/A',  # Total Questions
            correct_count if total_count > 0 else 'N/A',  # Correct Answers
            f"{user_result.score:.1f}%" if user_result.score is not None else 'N/A'  # Percentage
        ])
        
        # Write data row
        writer.writerow(row)
    
    # Create response
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename={result.user.name.replace(" ", "_")}_All_Tests_Export_{datetime.now().strftime("%Y%m%d")}.csv'
    
    return response

# Add this function to handle file uploads
def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Learning Resources File Upload Functions
def allowed_learning_file(filename):
    ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'wmv', 'flv', 'webm', 'pdf', 'doc', 'docx', 'ppt', 'pptx', 'txt'}
    if not filename or '.' not in filename:
        return False
    extension = filename.rsplit('.', 1)[1].lower()
    return extension in ALLOWED_EXTENSIONS

def get_file_type(filename):
    """Determine file type based on extension"""
    ext = filename.rsplit('.', 1)[1].lower()
    if ext in ['mp4', 'avi', 'mov', 'wmv', 'flv', 'webm']:
        return 'video'
    elif ext == 'pdf':
        return 'pdf'
    else:
        return 'document'

def get_file_size(file_path):
    try:
        return os.path.getsize(file_path)
    except:
        return 0

@app.route('/create_test')
@login_required
@admin_required
def create_test():
    # Get edit_test parameter if provided
    test_id = request.args.get('edit_test', None)
    test = None
    
    if test_id:
        test = Test.query.get_or_404(test_id)
    
    # Get all tests
    tests = Test.query.all()
    
    # If a test_id is specified for question management
    current_test_id = request.args.get('test_id', None)
    current_test = None
    question = None
    
    if current_test_id:
        current_test = Test.query.get_or_404(current_test_id)
        
        # Check if we're editing a specific question
        question_id = request.args.get('edit', None)
        if question_id:
            question = Question.query.get_or_404(question_id)
            if question.question_type == 'multiple_choice' and question.choices:
                question.choices_list = json.loads(question.choices)
    
    return render_template('create_test.html', 
                          tests=tests, 
                          test=test, 
                          current_test=current_test,
                          question=question)

@app.route('/create_test_set', methods=['POST'])
@login_required
@admin_required
def create_test_set():
    test_title = request.form.get('test_title')
    test_description = request.form.get('test_description', '')
    time_limit = int(request.form.get('time_limit', 30))
    test_id = request.form.get('test_id', '')
    learning_resource_id = request.form.get('learning_resource_id', '') or None
    
    if test_id:  # Update existing test
        test = Test.query.get_or_404(test_id)
        test.title = test_title
        test.description = test_description
        test.time_limit = time_limit
        test.learning_resource_id = learning_resource_id
        test.updated_at = datetime.utcnow()
        flash('Test updated successfully')
    else:  # Create new test
        test = Test(
            title=test_title,
            description=test_description,
            time_limit=time_limit,
            learning_resource_id=learning_resource_id
        )
        db.session.add(test)
        flash('Test created successfully')
    
    db.session.commit()
    return redirect(url_for('create_test'))

@app.route('/delete_test', methods=['POST'])
@login_required
@admin_required
def delete_test():
    test_id = request.form.get('test_id')
    test = Test.query.get_or_404(test_id)
    
    # Delete all results associated with this test first
    results = Result.query.filter_by(test_id=test_id).all()
    for result in results:
        db.session.delete(result)
    
    # Delete all questions associated with this test
    questions = Question.query.filter_by(test_id=test_id).all()
    for question in questions:
        db.session.delete(question)
    
    # Finally, delete the test
    db.session.delete(test)
    db.session.commit()
    
    flash('Test updated successfully')
    return redirect(url_for('create_test'))

@app.route('/manage_questions/<int:test_id>')
@login_required
@admin_required
def manage_questions(test_id):
    edit_question_id = request.args.get('edit', None)
    
    # Redirect to create_test with appropriate parameters
    if edit_question_id:
        return redirect(url_for('create_test', test_id=test_id, edit=edit_question_id, tab='questions'))
    else:
        return redirect(url_for('create_test', test_id=test_id, tab='questions'))

@app.route('/create_question/<int:test_id>', methods=['POST'])
@login_required
@admin_required
def create_question(test_id):
    # Get common fields
    question_text = request.form.get('question_text')
    question_type = request.form.get('question_type')
    correct_answer = request.form.get('correct_answer')
    question_id = request.form.get('question_id', '')
    use_choice_images = 'use_choice_images' in request.form
    
    # Process choices for multiple-choice
    choices = None
    choice_images = None
    
    if question_type == 'multiple_choice':
        if use_choice_images:
            # Handle image choices with custom descriptions
            choice_images_list = []
            choice_descriptions = request.form.getlist('choice_descriptions')
            existing_images = request.form.getlist('existing_choice_images')
            uploaded_files = request.files.getlist('choice_images')
            
            # Build final descriptions list
            final_descriptions = []
            
            for i, file in enumerate(uploaded_files):
                image_path = None
                
                # Check if there's an existing image
                if i < len(existing_images) and existing_images[i]:
                    image_path = existing_images[i]
                
                # If a new file is uploaded, replace the existing one
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    # Create unique filename with question info
                    unique_filename = f"choice_{test_id}_{int(datetime.now().timestamp())}_{i}_{filename}"
                    upload_folder = os.path.join(app.static_folder, 'uploads')
                    
                    if not os.path.exists(upload_folder):
                        os.makedirs(upload_folder)
                    
                    file_path = os.path.join(upload_folder, unique_filename)
                    file.save(file_path)
                    image_path = 'uploads/' + unique_filename
                
                if image_path:
                    choice_images_list.append(image_path)
                    # Get the corresponding description
                    if i < len(choice_descriptions) and choice_descriptions[i].strip():
                        final_descriptions.append(choice_descriptions[i].strip())
                    else:
                        final_descriptions.append(f"Image {i+1}")
            
            if choice_images_list:
                choice_images = json.dumps(choice_images_list)
                choices = json.dumps(final_descriptions)
        else:
            # Handle text choices
            choices_list = [c for c in request.form.getlist('choices') if c.strip()]
            choices = json.dumps(choices_list)
    
    # Process image upload for image questions
    image_path = request.form.get('image_path')
    if question_type == 'image' and 'image_file' in request.files:
        file = request.files['image_file']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            upload_folder = os.path.join(app.static_folder, 'uploads')
            
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            
            file_path = os.path.join(upload_folder, filename)
            file.save(file_path)
            image_path = 'uploads/' + filename
    
    if question_id:
        # Update existing question
        question = Question.query.get_or_404(question_id)
        question.question_text = question_text
        question.question_type = question_type
        question.choices = choices
        question.choice_images = choice_images
        question.correct_answer = correct_answer
        if image_path:
            question.image_path = image_path
        question.updated_at = datetime.utcnow()
        flash('Question updated successfully')
    else:
        # Create new question
        new_question = Question(
            test_id=test_id,
            question_text=question_text,
            question_type=question_type,
            choices=choices,
            choice_images=choice_images,
            correct_answer=correct_answer,
            image_path=image_path
        )
        db.session.add(new_question)
        flash('Question created successfully')
    
    db.session.commit()
    return redirect(url_for('manage_questions', test_id=test_id))

@app.route('/delete_question', methods=['POST'])
@login_required
@admin_required
def delete_question():
    question_id = request.form.get('question_id')
    test_id = request.form.get('test_id')
    
    question = Question.query.get_or_404(question_id)
    db.session.delete(question)
    db.session.commit()
    
    flash('Question deleted successfully')
    return redirect(url_for('manage_questions', test_id=test_id))

@app.route('/available_tests')
@login_required
def available_tests():
    if current_user.role == 'admin':
        flash('This page is for students to take tests')
        return redirect(url_for('dashboard'))
    
    # Get all available tests
    tests = Test.query.all()
    
    # Get user's results
    user_results = Result.query.filter_by(user_id=current_user.id).all()
    
    # Create a set of completed test IDs
    completed_tests = {result.test_id for result in user_results}
    
    # Create a mapping of test_id to result_id for quick lookup
    test_results = {result.test_id: result.id for result in user_results}
    
    return render_template('available_tests.html', 
                          tests=tests, 
                          user_results=user_results,
                          completed_tests=completed_tests,
                          test_results=test_results,
                          now=datetime.now())

@app.route('/take_test/<int:test_id>')
@login_required
def take_test(test_id):
    if current_user.role == 'admin':
        flash('Admins cannot take tests')
        return redirect(url_for('dashboard'))
    
    # Check if the test exists
    test = Test.query.get_or_404(test_id)
    
    # Check if the user has already taken this test
    existing_result = Result.query.filter_by(user_id=current_user.id, test_id=test_id).first()
    if existing_result:
        flash('You have already taken this test')
        return redirect(url_for('available_tests'))
    
    # Check if the test has questions
    if not test.questions:
        flash('This test has no questions')
        return redirect(url_for('available_tests'))
    
    # Set active test session to prevent access to resources
    session['active_test_id'] = test_id
    session['test_start_time'] = datetime.utcnow().isoformat()
    session['security_violations'] = 0
    session['tab_switches'] = 0
    session['fullscreen_exits'] = 0
    session['security_log'] = []
    session.permanent = True
    
    # Log test start
    app.logger.info(f'Test started: User {current_user.id} ({current_user.name}) started test {test_id} ({test.title})')
    
    return render_template('take_test.html', test=test)

@app.route('/submit_test/<int:test_id>', methods=['POST'])
@login_required
def submit_test(test_id):
    if current_user.role == 'admin':
        flash('Admins cannot take tests')
        return redirect(url_for('dashboard'))
    
    # Check if the test exists
    test = Test.query.get_or_404(test_id)
    
    # Check if the user has already taken this test
    existing_result = Result.query.filter_by(user_id=current_user.id, test_id=test_id).first()
    if existing_result:
        flash('You have already taken this test')
        return redirect(url_for('available_tests'))
    
    # Verify this matches the active test session
    if session.get('active_test_id') != test_id:
        flash('Invalid test session. Please start the test again.')
        return redirect(url_for('available_tests'))
    
    # Process the test submission
    questions = test.questions
    
    if not questions:
        flash('This test has no questions')
        return redirect(url_for('available_tests'))
    
    # Calculate score
    total_questions = len(questions)
    correct_answers = 0
    result_data = {}
    
    for question in questions:
        # Get the user's answer for this question
        user_answer = request.form.get(f'answer_{question.id}', '').strip()
        
        # Check if the answer is correct
        is_correct = False
        if user_answer.lower() == question.correct_answer.lower():
            correct_answers += 1
            is_correct = True
        
        # Store question data with consistent structure
        question_data = {
            'question_text': question.question_text,
            'question_type': question.question_type,
            'user_answer': user_answer,
            'correct_answer': question.correct_answer,
            'is_correct': is_correct
        }
        
        if question.image_path:
            question_data['image_path'] = question.image_path
            
        if question.question_type == 'multiple_choice':
            if question.choices:
                question_data['choices'] = json.loads(question.choices)
            if question.choice_images:
                question_data['choice_images'] = json.loads(question.choice_images)
        
        # Use string key to ensure consistency
        result_data[str(question.id)] = question_data
    
    # Calculate percentage score
    score = (correct_answers / total_questions) * 100 if total_questions > 0 else 0
    
    # Get security information from session
    security_violations = session.get('security_violations', 0)
    tab_switches = session.get('tab_switches', 0)
    fullscreen_exits = session.get('fullscreen_exits', 0)
    security_log = session.get('security_log', [])
    
    # Add security information to result data
    result_data['security_info'] = {
        'violations': security_violations,
        'tab_switches': tab_switches,
        'fullscreen_exits': fullscreen_exits,
        'security_log': security_log[:10]  # Store only last 10 entries
    }
    
    # Create result record
    result = Result(
        user_id=current_user.id,
        test_id=test_id,
        score=score,
        raw_data=json.dumps(result_data)
    )
    
    db.session.add(result)
    db.session.commit()
    
    # Log test completion with security info
    app.logger.info(f'Test completed: User {current_user.id} ({current_user.name}) completed test {test_id} with score {score:.1f}%. Security violations: {security_violations}, Tab switches: {tab_switches}, Fullscreen exits: {fullscreen_exits}')
    
    # Clear active test session after submission
    session.pop('active_test_id', None)
    session.pop('test_start_time', None)
    session.pop('last_heartbeat', None)
    session.pop('security_violations', None)
    session.pop('tab_switches', None)
    session.pop('fullscreen_exits', None)
    session.pop('security_log', None)
    session.permanent = True
    
    # Redirect to result page
    flash(f'Test submitted successfully. Your score: {score:.1f}%')
    return redirect(url_for('view_result', result_id=result.id))

@app.route('/student_records/<int:user_id>')
@login_required
@admin_required
def view_student_records(user_id):
    # Get the student user
    student = User.query.get_or_404(user_id)
    
    # Ensure we're viewing a student's records
    if student.role != 'student':
        flash('Records can only be viewed for student accounts')
        return redirect(url_for('dashboard'))
    
    # Get all results for this student
    results = Result.query.filter_by(user_id=user_id).order_by(Result.date_taken.desc()).all()
    
    # Calculate statistics
    total_tests_taken = len(results)
    if total_tests_taken > 0:
        average_score = sum(result.score for result in results) / total_tests_taken
        highest_score = max(result.score for result in results)
        lowest_score = min(result.score for result in results)
        
        # Count scores by grade levels
        excellent_count = len([r for r in results if r.score >= 90])
        good_count = len([r for r in results if 70 <= r.score < 90])
        fair_count = len([r for r in results if 50 <= r.score < 70])
        poor_count = len([r for r in results if r.score < 50])
    else:
        average_score = 0
        highest_score = 0
        lowest_score = 0
        excellent_count = good_count = fair_count = poor_count = 0
    
    # Get total available tests
    total_available_tests = Test.query.count()
    
    statistics = {
        'total_tests_taken': total_tests_taken,
        'total_available_tests': total_available_tests,
        'completion_rate': (total_tests_taken / total_available_tests * 100) if total_available_tests > 0 else 0,
        'average_score': average_score,
        'highest_score': highest_score,
        'lowest_score': lowest_score,
        'excellent_count': excellent_count,
        'good_count': good_count,
        'fair_count': fair_count,
        'poor_count': poor_count
    }
    
    return render_template('student_records.html', 
                          student=student, 
                          results=results, 
                          statistics=statistics,
                          now=datetime.now())

@app.route('/learning_resources')
@login_required
@check_test_session
def learning_resources():
    if current_user.role == 'admin':
        # Admin view - manage all resources
        resources = LearningResource.query.filter_by(is_active=True).order_by(LearningResource.created_at.desc()).all()
        tests = Test.query.all()  # For linking tests to resources
        return render_template('admin_learning_resources.html', resources=resources, tests=tests)
    else:
        # Student view - view available resources
        resources = LearningResource.query.filter_by(is_active=True).order_by(LearningResource.created_at.desc()).all()
        
        # Get student progress for each resource
        progress_data = {}
        for resource in resources:
            progress = StudentProgress.query.filter_by(
                user_id=current_user.id, 
                resource_id=resource.id
            ).first()
            progress_data[resource.id] = progress
        
        return render_template('student_learning_resources.html', 
                             resources=resources, 
                             progress_data=progress_data)

@app.route('/upload_learning_resource', methods=['POST'])
@login_required
@admin_required
def upload_learning_resource():
    try:
        title = request.form.get('title')
        description = request.form.get('description', '')
        
        if not title:
            flash('Title is required', 'error')
            return redirect(url_for('learning_resources'))
          # Get multiple files
        uploaded_files = request.files.getlist('resource_files')
        
        if not uploaded_files or all(file.filename == '' for file in uploaded_files):
            flash('At least one file is required', 'error')
            return redirect(url_for('learning_resources'))
        
        # Filter out empty files and validate
        valid_files = []
        invalid_files = []
        
        for file in uploaded_files:
            if file and file.filename and file.filename.strip():
                if allowed_learning_file(file.filename):
                    valid_files.append(file)
                else:
                    invalid_files.append(file.filename)
        
        if not valid_files:
            if invalid_files:
                flash(f'Invalid file types detected: {", ".join(invalid_files)}. Please upload only MP4, AVI, MOV, WMV, FLV, WEBM, PDF, DOC, DOCX, PPT, PPTX, or TXT files.', 'error')
            else:
                flash('No valid files found. Please upload video, PDF, or document files.', 'error')
            return redirect(url_for('learning_resources'))
        
        if invalid_files:
            flash(f'Some files were skipped due to invalid formats: {", ".join(invalid_files)}. Only valid files were uploaded.', 'warning')
        
        # Determine resource type based on uploaded files
        file_types = [get_file_type(file.filename) for file in valid_files]
        if len(set(file_types)) > 1:
            resource_type = 'mixed'
        else:
            resource_type = file_types[0]
        
        # Create the learning resource
        resource = LearningResource(
            title=title,
            description=description,
            resource_type=resource_type,
            created_by=current_user.id,
            file_size=0  # Will be calculated from all files
        )
        
        db.session.add(resource)
        db.session.flush()  # Get the ID
        
        total_size = 0
        
        # Save each file
        for index, file in enumerate(valid_files):
            if file and file.filename:
                filename = secure_filename(file.filename)
                unique_filename = f"{resource.id}_{index}_{filename}"
                file_path = os.path.join(app.config['LEARNING_RESOURCES_FOLDER'], unique_filename)
                
                # Save file
                file.save(file_path)
                
                # Get file info
                file_size = get_file_size(file_path)
                file_type = get_file_type(filename)
                total_size += file_size
                
                # Create ResourceFile record
                resource_file = ResourceFile(
                    resource_id=resource.id,
                    filename=unique_filename,
                    original_filename=filename,
                    file_path=f"learning_resources/{unique_filename}",
                    file_type=file_type,
                    file_size=file_size,
                    upload_order=index,
                    mime_type=file.content_type or 'application/octet-stream'
                )
                
                db.session.add(resource_file)
        
        # Update resource with total size
        resource.file_size = total_size
        
        # Set primary file path for backward compatibility (first file)
        if valid_files:
            first_file = valid_files[0]
            first_filename = secure_filename(first_file.filename)
            resource.file_path = f"learning_resources/{resource.id}_0_{first_filename}"
        
        db.session.commit()
        flash(f'Learning resource uploaded successfully with {len(valid_files)} file(s)!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error uploading resource: {str(e)}', 'error')
    
    return redirect(url_for('learning_resources'))

@app.route('/edit_learning_resource/<int:resource_id>', methods=['POST'])
@login_required
@admin_required
def edit_learning_resource(resource_id):
    try:
        resource = LearningResource.query.get_or_404(resource_id)
        
        resource.title = request.form.get('title')
        resource.description = request.form.get('description', '')
        resource.updated_at = datetime.utcnow()
        
        db.session.commit()
        flash('Learning resource updated successfully!')
    
    except Exception as e:
        flash(f'Error updating resource: {str(e)}')
        db.session.rollback()
    
    return redirect(url_for('learning_resources'))

@app.route('/delete_learning_resource/<int:resource_id>', methods=['POST'])
@login_required
@admin_required
def delete_learning_resource(resource_id):
    try:
        resource = LearningResource.query.get_or_404(resource_id)
        
        # Delete the actual file
        file_path = os.path.join(app.static_folder, 'uploads', resource.file_path)
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # Delete progress records
        StudentProgress.query.filter_by(resource_id=resource_id).delete()
        
        # Unlink any tests associated with this resource
        tests = Test.query.filter_by(learning_resource_id=resource_id).all()
        for test in tests:
            test.learning_resource_id = None
        
        db.session.delete(resource)
        db.session.commit()
        
        flash('Learning resource deleted successfully!')
    
    except Exception as e:
        flash(f'Error deleting resource: {str(e)}')
        db.session.rollback()
    
    return redirect(url_for('learning_resources'))

@app.route('/view_resource/<int:resource_id>')
@login_required
@check_test_session  # Add this decorator to prevent access during tests
def view_resource(resource_id):
    resource = LearningResource.query.get_or_404(resource_id)
    
    # Get or create progress record for students
    progress = None
    if current_user.role == 'student':
        progress = StudentProgress.query.filter_by(
            user_id=current_user.id, 
            resource_id=resource_id
        ).first()
        
        if not progress:
            progress = StudentProgress(
                user_id=current_user.id,
                resource_id=resource_id,
                progress_percentage=0.0
            )
            db.session.add(progress)
            db.session.commit()
    
    # For PDF and non-video resources, check if it's a direct file access request
    if request.args.get('direct') == '1':
        # If there are multiple files, serve the first PDF or document
        if resource.files:
            target_file = None
            # Look for PDF first, then any document
            for file in resource.files:
                if file.file_type == 'pdf':
                    target_file = file
                    break
            if not target_file:
                for file in resource.files:
                    if file.file_type == 'document':
                        target_file = file
                        break
            if not target_file:
                target_file = resource.files[0]
            
            return send_from_directory(
                app.config['LEARNING_RESOURCES_FOLDER'], 
                target_file.filename
            )
        else:
            # Fallback to old single file system
            if resource.file_path:
                filename = resource.file_path.split('/')[-1]
                return send_from_directory(app.config['LEARNING_RESOURCES_FOLDER'], filename)
    
    # Get all files for the resource, ordered by upload_order
    resource_files = ResourceFile.query.filter_by(resource_id=resource_id).order_by(ResourceFile.upload_order).all()
    
    return render_template('view_resource.html', 
                         resource=resource, 
                         progress=progress, 
                         resource_files=resource_files)

@app.route('/update_progress/<int:resource_id>', methods=['POST'])
@login_required
@check_test_session  # Add this decorator to prevent progress updates during tests
def update_progress(resource_id):
    if current_user.role != 'student':
        return jsonify({'success': False, 'message': 'Only students can update progress'})
    
    try:
        progress = StudentProgress.query.filter_by(
            user_id=current_user.id,
            resource_id=resource_id
        ).first()
        
        if not progress:
            progress = StudentProgress(
                user_id=current_user.id,
                resource_id=resource_id
            )
            db.session.add(progress)
        
        data = request.get_json()
        progress.progress_percentage = data.get('progress', 0)
        progress.last_position = data.get('position', 0)
        progress.time_spent = data.get('time_spent', 0)
        progress.completed = data.get('completed', False)
        progress.last_accessed = datetime.utcnow()
        
        db.session.commit();
        
        return jsonify({'success': True})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/link_test_to_resource', methods=['POST'])
@login_required
@admin_required
def link_test_to_resource():
    try:
        test_id = request.form.get('test_id')
        resource_id = request.form.get('resource_id')
        
        test = Test.query.get_or_404(test_id)
        resource = LearningResource.query.get_or_404(resource_id)
        
        test.learning_resource_id = resource_id
        db.session.commit()
        
        flash(f'Test "{test.title}" linked to resource "{resource.title}" successfully!')
    
    except Exception as e:
        flash(f'Error linking test to resource: {str(e)}')
        db.session.rollback()
    
    return redirect(url_for('learning_resources'))

@app.route('/unlink_test_from_resource/<int:test_id>', methods=['POST'])
@login_required
@admin_required
def unlink_test_from_resource(test_id):
    try:
        test = Test.query.get_or_404(test_id)
        test.learning_resource_id = None
        db.session.commit()
        
        flash(f'Test "{test.title}" unlinked from resource successfully!')
    
    except Exception as e:
        flash(f'Error unlinking test: {str(e)}')
        db.session.rollback()
    
    return redirect(url_for('learning_resources'))

@app.route('/resource_file/<path:filename>')
@login_required
@check_test_session  # Add this decorator to prevent direct file access during tests
def resource_file(filename):
    # Serve files from the learning resources folder
    return send_from_directory(app.config['LEARNING_RESOURCES_FOLDER'], filename)

@app.route('/')
def index():
    return redirect(url_for('login'))

def init_db():
    with app.app_context():
        # Check if database needs to be initialized
        db_file = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        initialize_db = not os.path.exists(db_file) or os.environ.get('REINIT_DB') == '1'
        
        if initialize_db:
            # Create all tables
            db.create_all()
            
            # Only create admin user if no users exist
            if User.query.count() == 0:
                admin = User(name='Admin', username='admin', role='admin', student_id='admin')
                admin.set_password('admin')
                db.session.add(admin)
                db.session.commit()
                print('Admin user created with username: admin, password: admin')
        else:
            print('Database already exists. Skipping initialization.')

if __name__ == '__main__':
    init_db()
    # Enable multiple device access on same network with proper threading
    app.run(host='0.0.0.0', debug=True, port=5000, threaded=True, processes=1, use_reloader=False)

# Test security routes (for debugging - remove in production)
@app.route('/debug/session')
@login_required
def debug_session():
    """Debug route to check session state"""
    if current_user.role != 'admin':
        return "Access denied", 403
    
    return {
        'user': current_user.name,
        'session_id': session.sid,
        'test_start_time': session.get('test_start_time'),
        'active_test_id': session.get('active_test_id'),
        'role': current_user.role,
        'active_test_id': session.get('active_test_id'),
        'test_start_time': session.get('test_start_time'),
        'session_keys': list(session.keys())
    }

@app.route('/test_heartbeat', methods=['POST'])
@login_required
def test_heartbeat():
    """Handle test session heartbeat to monitor if student is still active"""
    if current_user.role != 'student':
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Check if student has an active test session
    if 'active_test_id' not in session:
        return jsonify({'error': 'No active test session'}), 400
    
    try:
        data = request.get_json()
        test_id = data.get('test_id')
        timestamp = data.get('timestamp')
        security_violations = data.get('security_violations', 0)
        tab_switches = data.get('tab_switches', 0)
        fullscreen_exits = data.get('fullscreen_exits', 0)
        
        # Verify the test_id matches the active session
        if test_id != session['active_test_id']:
            return jsonify({'error': 'Test ID mismatch'}), 400
        
        # Update session with latest heartbeat
        session['last_heartbeat'] = timestamp
        session['security_violations'] = security_violations
        session['tab_switches'] = tab_switches
        session['fullscreen_exits'] = fullscreen_exits
        session.permanent = True
        
        # Log security issues if any
        if security_violations > 0:
            app.logger.warning(f'Security violations detected for user {current_user.id} in test {test_id}: {security_violations} violations, {tab_switches} tab switches, {fullscreen_exits} fullscreen exits')
        
        return jsonify({'status': 'success', 'timestamp': timestamp})
        
    except Exception as e:
        app.logger.error(f'Heartbeat error for user {current_user.id}: {str(e)}')
        return jsonify({'error': 'Server error'}), 500

@app.route('/record_security_violation', methods=['POST'])
@login_required
def record_security_violation():
    """Record security violations during test"""
    if current_user.role != 'student':
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Check if student has an active test session
    if 'active_test_id' not in session:
        return jsonify({'error': 'No active test session'}), 400
    
    try:
        data = request.get_json()
        test_id = data.get('test_id')
        violation_type = data.get('violation_type')
        timestamp = data.get('timestamp')
        total_violations = data.get('total_violations', 0)
        
        # Verify the test_id matches the active session
        if test_id != session['active_test_id']:
            return jsonify({'error': 'Test ID mismatch'}), 400
        
        # Log the violation
        app.logger.warning(f'Security violation: User {current_user.id} ({current_user.name}) in test {test_id} - {violation_type} at {timestamp}. Total violations: {total_violations}')
        
        # Store violations in session
        if 'security_log' not in session:
            session['security_log'] = []
        
        session['security_log'].append({
            'type': violation_type,
            'timestamp': timestamp,
            'test_id': test_id
        })
        
        # Limit log size to prevent session bloat
        if len(session['security_log']) > 100:
            session['security_log'] = session['security_log'][-100:]
        
        session.permanent = True
        
        return jsonify({'status': 'recorded'})
        
    except Exception as e:
        app.logger.error(f'Security violation recording error for user {current_user.id}: {str(e)}')
        return jsonify({'error': 'Server error'}), 500

@app.route('/test_abandoned', methods=['POST'])
@login_required
def test_abandoned():
    """Handle test abandonment (when student closes browser/tab)"""
    if current_user.role != 'student':
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        # This is called via sendBeacon, so data might be in request.data
        data = request.get_json() or {}
        test_id = data.get('test_id')
        timestamp = data.get('timestamp')
        violations = data.get('violations', 0)
        
        # Log the abandonment
        app.logger.warning(f'TEST ABANDONED: User {current_user.id} ({current_user.name}) abandoned test {test_id} at {timestamp} with {violations} security violations')
        
        # Clear the test session
        session.pop('active_test_id', None)
        session.pop('test_start_time', None)
        session.pop('last_heartbeat', None)
        session.pop('security_violations', None)
        session.pop('security_log', None)
        session.permanent = True
        
        return '', 204  # No content response for sendBeacon
        
    except Exception as e:
        app.logger.error(f'Test abandonment handling error: {str(e)}')
        return '', 500
        app.logger.error(f'Test abandonment handling error: {str(e)}')
        return '', 500
