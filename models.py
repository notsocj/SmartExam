from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import json

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    student_id = db.Column(db.String(50), unique=True, nullable=True)  # New field
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20), default='student')  # 'admin' or 'student'
      # Add relationship to results with cascade delete
    results = db.relationship('Result', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Result(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    test_id = db.Column(db.Integer, db.ForeignKey('test.id', ondelete='CASCADE'), nullable=False)
    score = db.Column(db.Float, nullable=False)
    date_taken = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    raw_data = db.Column(db.Text)  # Store JSON or other structured data
    can_retake = db.Column(db.Boolean, default=False, nullable=False)  # New column for retake control

class Test(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    time_limit = db.Column(db.Integer, nullable=False)  # Time limit in minutes
    learning_resource_id = db.Column(db.Integer, db.ForeignKey('learning_resource.id'), nullable=True)  # Link to learning resource
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Add relationship to questions with cascade delete
    questions = db.relationship('Question', backref='test', lazy=True, cascade='all, delete-orphan')
    
    # Add relationship to results with cascade delete
    results = db.relationship('Result', backref='test', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Test {self.title}>'

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey('test.id', ondelete='CASCADE'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(20), nullable=False)  # 'multiple_choice', 'identification', or 'image'
    choices = db.Column(db.Text)  # Stored as JSON for multiple-choice questions
    choice_images = db.Column(db.Text)  # Stored as JSON for multiple-choice image paths
    correct_answer = db.Column(db.Text, nullable=False)
    image_path = db.Column(db.String(255))  # For question images (all types) and image question content
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @property
    def choices_list(self):
        """Return choices as a Python list"""
        if self.choices:
            try:
                return json.loads(self.choices)
            except:
                return []
        return []
    
    @property
    def choice_images_list(self):
        """Return choice images as a Python list"""
        if self.choice_images:
            try:
                return json.loads(self.choice_images)
            except:
                return []
        return []

class LearningResource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    resource_type = db.Column(db.String(20), nullable=False)  # 'mixed', 'video', 'document', 'pdf'
    file_path = db.Column(db.String(500), nullable=True)  # Primary file path (for backward compatibility)
    thumbnail_path = db.Column(db.String(500))  # For video thumbnails
    file_size = db.Column(db.BigInteger)  # Total file size in bytes
    duration = db.Column(db.Integer)  # Duration in seconds for videos
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationship to tests (one resource can have multiple linked tests)
    linked_tests = db.relationship('Test', backref='learning_resource', lazy=True)
    
    # Relationship to multiple files
    files = db.relationship('ResourceFile', backref='resource', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<LearningResource {self.title}>'

class ResourceFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('learning_resource.id', ondelete='CASCADE'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)  # 'video', 'pdf', 'document'
    file_size = db.Column(db.BigInteger)  # File size in bytes
    mime_type = db.Column(db.String(100))
    duration = db.Column(db.Integer)  # Duration in seconds for videos
    upload_order = db.Column(db.Integer, default=0)  # Order of files in the resource
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<ResourceFile {self.filename}>'

class StudentProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey('learning_resource.id', ondelete='CASCADE'), nullable=False)
    progress_percentage = db.Column(db.Float, default=0.0)  # 0-100
    last_position = db.Column(db.Integer, default=0)  # For video playback position
    completed = db.Column(db.Boolean, default=False)
    time_spent = db.Column(db.Integer, default=0)  # Time spent in seconds
    first_accessed = db.Column(db.DateTime, default=datetime.utcnow)
    last_accessed = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Composite unique constraint
    __table_args__ = (db.UniqueConstraint('user_id', 'resource_id', name='unique_user_resource'),)
