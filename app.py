from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, make_response, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from functools import wraps
from models import db, User, Result, Question, Test, LearningResource, StudentProgress
from config import config
from datetime import datetime
from werkzeug.utils import secure_filename
import os
import json
import csv
import io

# Get environment configuration
config_name = os.environ.get('FLASK_ENV', 'default')
app = Flask(__name__)
app.config.from_object(config[config_name])

# Initialize database
db.init_app(app)

# Initialize Flask-Migrate
migrate = Migrate(app, db)

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

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
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
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
        return render_template('dashboard.html', users=users, results=results, tests=tests, now=now)
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
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
    
    # Process choices for multiple-choice
    choices = None
    if question_type == 'multiple_choice':
        # Get choices from form and convert to JSON
        choices_list = [c for c in request.form.getlist('choices') if c.strip()]
        choices = json.dumps(choices_list)
    
    # Process image upload for image questions
    image_path = request.form.get('image_path')
    if question_type == 'image' and 'image_file' in request.files:
        file = request.files['image_file']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            upload_folder = os.path.join(app.static_folder, 'uploads')
            
            # Create the uploads directory if it doesn't exist
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            
            file_path = os.path.join(upload_folder, filename)
            file.save(file_path)
            
            # Store relative path from static folder
            image_path = 'uploads/' + filename
    
    if question_id:
        # Update existing question
        question = Question.query.get_or_404(question_id)
        question.question_text = question_text
        question.question_type = question_type
        question.choices = choices
        question.correct_answer = correct_answer
        if image_path:  # Only update if a new image was uploaded
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
        flash('Admin users cannot take tests')
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
    
    return render_template('take_test.html', test=test)

@app.route('/submit_test/<int:test_id>', methods=['POST'])
@login_required
def submit_test(test_id):
    if current_user.role == 'admin':
        flash('Admin users cannot take tests')
        return redirect(url_for('dashboard'))
    
    # Check if the test exists
    test = Test.query.get_or_404(test_id)
    
    # Check if the user has already taken this test
    existing_result = Result.query.filter_by(user_id=current_user.id, test_id=test_id).first()
    if existing_result:
        flash('You have already taken this test')
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
        
        # Store question data
        question_data = {
            'question_text': question.question_text,
            'question_type': question.question_type,
            'user_answer': user_answer,
            'correct_answer': question.correct_answer,
            'is_correct': is_correct
        }
        
        if question.image_path:
            question_data['image_path'] = question.image_path
            
        if question.question_type == 'multiple_choice' and question.choices:
            question_data['choices'] = json.loads(question.choices)
        
        result_data[question.id] = question_data
    
    # Calculate percentage score
    score = (correct_answers / total_questions) * 100 if total_questions > 0 else 0
    
    # Create result record
    result = Result(
        user_id=current_user.id,
        test_id=test_id,
        score=score,
        raw_data=json.dumps(result_data)
    )
    
    db.session.add(result)
    db.session.commit()
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
        
        if 'resource_file' not in request.files:
            flash('No file selected')
            return redirect(url_for('learning_resources'))
        
        file = request.files['resource_file']
        if file.filename == '':
            flash('No file selected')
            return redirect(url_for('learning_resources'))
        
        if file and allowed_learning_file(file.filename):
            filename = secure_filename(file.filename)
            
            # Create unique filename to avoid conflicts
            timestamp = str(int(datetime.now().timestamp()))
            name, ext = os.path.splitext(filename)
            unique_filename = f"{name}_{timestamp}{ext}"
            
            file_path = os.path.join(app.config['LEARNING_RESOURCES_FOLDER'], unique_filename)
            file.save(file_path)
            
            # Determine resource type based on file extension
            file_ext = ext.lower()
            if file_ext in ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm']:
                resource_type = 'video'
            elif file_ext == '.pdf':
                resource_type = 'pdf'
            else:
                resource_type = 'document'
            
            # Get file size
            file_size = get_file_size(file_path)
            
            # Create learning resource record
            resource = LearningResource(
                title=title,
                description=description,
                resource_type=resource_type,
                file_path=f'learning_resources/{unique_filename}',
                file_size=file_size,
                created_by=current_user.id
            )
            
            db.session.add(resource)
            db.session.commit()
            
            flash('Learning resource uploaded successfully!')
        else:
            flash('Invalid file type. Please upload a supported format.')
    
    except Exception as e:
        flash(f'Error uploading file: {str(e)}')
        db.session.rollback()
    
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
                resource_id=resource_id
            )
            db.session.add(progress)
            db.session.commit()
        else:
            # Update last accessed time
            progress.last_accessed = datetime.utcnow()
            db.session.commit()
    
    # For PDF and non-video resources, check if it's a direct file access request
    if resource.resource_type in ['pdf', 'document'] and request.args.get('direct') == '1':
        # Serve the file directly for new tab opening
        return send_from_directory(app.config['LEARNING_RESOURCES_FOLDER'], 
                                 os.path.basename(resource.file_path))
    
    return render_template('view_resource.html', resource=resource, progress=progress)

@app.route('/update_progress/<int:resource_id>', methods=['POST'])
@login_required
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
        
        db.session.commit()
        
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
    app.run(host='0.0.0.0', debug=True, port=5000)
