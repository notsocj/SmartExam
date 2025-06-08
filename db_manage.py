import os
import click
from flask.cli import FlaskGroup
from app import app, db, User

cli = FlaskGroup(app)

@cli.command('init-db')
def init_db_command():
    """Clear existing data and create new tables."""
    db.drop_all()
    db.create_all()
    
    # Create admin user
    admin = User(name='Admin', username='admin', role='admin', student_id='admin')
    admin.set_password('admin')
    db.session.add(admin)
    db.session.commit()
    
    click.echo('Initialized the database and created admin user (username: admin, password: admin)')

@cli.command('create-user')
@click.option('--name', prompt=True, help='User\'s full name')
@click.option('--student-id', prompt=True, help='Student ID')
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True, help='User password')
@click.option('--role', prompt=True, default='student', type=click.Choice(['student', 'admin']), help='User role')
def create_user(name, student_id, password, role):
    """Create a new user."""
    # Check if username already exists
    if User.query.filter_by(username=student_id).first():
        click.echo(f'Error: Username {student_id} already exists')
        return
    
    user = User(name=name, student_id=student_id, username=student_id, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.echo(f'Created user {name} with role {role}')

@cli.command('list-users')
def list_users():
    """List all users."""
    users = User.query.all()
    click.echo(f'Total users: {len(users)}')
    for user in users:
        click.echo(f'ID: {user.id}, Name: {user.name}, Student ID: {user.student_id}, Role: {user.role}')

if __name__ == '__main__':
    cli()
