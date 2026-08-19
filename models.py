from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()


class MockTest(db.Model):
    __tablename__ = 'mock_tests'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    timer_minutes = db.Column(db.Integer, default=60)
    total_questions = db.Column(db.Integer, default=0)
    negative_marking = db.Column(db.Boolean, default=True)
    marks_correct = db.Column(db.Float, default=1.0)
    marks_wrong = db.Column(db.Float, default=-1.0)
    sections_json = db.Column(db.Text, default='[]')  # JSON list of section names

    questions = db.relationship('Question', backref='test', lazy=True,
                                cascade='all, delete-orphan',
                                order_by='Question.question_number')
    attempts = db.relationship('TestAttempt', backref='test', lazy=True,
                               cascade='all, delete-orphan')

    @property
    def sections(self):
        return json.loads(self.sections_json) if self.sections_json else []

    @sections.setter
    def sections(self, value):
        self.sections_json = json.dumps(value)

    def __repr__(self):
        return f'<MockTest {self.name}>'


class Question(db.Model):
    __tablename__ = 'questions'

    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey('mock_tests.id'), nullable=False)
    question_number = db.Column(db.Integer, nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(10), default='mcq')  # 'mcq' or 'text'
    option_a = db.Column(db.Text, default='')
    option_b = db.Column(db.Text, default='')
    option_c = db.Column(db.Text, default='')
    option_d = db.Column(db.Text, default='')
    option_e = db.Column(db.Text, default='')  # Some exams have 5 options
    correct_answer = db.Column(db.Text, default='')  # A-E for MCQ, or text/number for text type
    question_image = db.Column(db.Text, default='')  # Relative path to extracted image from PDF
    section_name = db.Column(db.String(100), default='General')

    answers = db.relationship('UserAnswer', backref='question', lazy=True,
                              cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'question_number': self.question_number,
            'question_text': self.question_text,
            'question_type': self.question_type or 'mcq',
            'option_a': self.option_a,
            'option_b': self.option_b,
            'option_c': self.option_c,
            'option_d': self.option_d,
            'option_e': self.option_e,
            'correct_answer': self.correct_answer,
            'section_name': self.section_name,
            'question_image': self.question_image or '',
        }

    def __repr__(self):
        return f'<Question {self.question_number}>'


class TestAttempt(db.Model):
    __tablename__ = 'test_attempts'

    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey('mock_tests.id'), nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.now)
    finished_at = db.Column(db.DateTime, nullable=True)
    score = db.Column(db.Float, default=0)
    max_score = db.Column(db.Float, default=0)
    total_attempted = db.Column(db.Integer, default=0)
    total_correct = db.Column(db.Integer, default=0)
    total_wrong = db.Column(db.Integer, default=0)
    total_skipped = db.Column(db.Integer, default=0)
    time_taken_seconds = db.Column(db.Integer, default=0)
    accuracy_percent = db.Column(db.Float, default=0)
    section_scores_json = db.Column(db.Text, default='{}')

    user_answers = db.relationship('UserAnswer', backref='attempt', lazy=True,
                                   cascade='all, delete-orphan')

    @property
    def section_scores(self):
        return json.loads(self.section_scores_json) if self.section_scores_json else {}

    @section_scores.setter
    def section_scores(self, value):
        self.section_scores_json = json.dumps(value)

    def __repr__(self):
        return f'<TestAttempt {self.id} for test {self.test_id}>'


class UserAnswer(db.Model):
    __tablename__ = 'user_answers'

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey('test_attempts.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    selected_answer = db.Column(db.Text, default='')  # A-E for MCQ, or text/number for text type
    is_correct = db.Column(db.Boolean, default=False)
    time_spent_seconds = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f'<UserAnswer Q{self.question_id}: {self.selected_answer}>'
