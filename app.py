"""
MockPrep — PDF Mock Test System
Main Flask Application
"""

import os
import json
import uuid
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, jsonify
)
from werkzeug.utils import secure_filename
from config import Config
from models import db, MockTest, Question, TestAttempt, UserAnswer
from parsers.pdf_parser import (
    extract_text_from_pdf, extract_text_and_images_from_pdf,
    parse_questions, assign_sections_to_questions, assign_images_to_questions
)
from parsers.answer_key_parser import extract_answer_key, validate_answer_key


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Ensure upload directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Initialize database
    db.init_app(app)
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            print(f"Skipping db.create_all() due to: {e}")

    return app


app = create_app()


def allowed_file(filename, file_type='pdf'):
    if file_type == 'pdf':
        allowed = Config.ALLOWED_PDF_EXTENSIONS
    else:
        allowed = Config.ALLOWED_IMAGE_EXTENSIONS
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


# ===== Helpers =====
def get_temp_data():
    """Load temporary parsed data from disk."""
    temp_id = session.get('temp_id')
    if not temp_id:
        return {}
    path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_{temp_id}.json")
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return {}


def save_temp_data(data):
    """Save temporary parsed data to disk and set session id."""
    temp_id = session.get('temp_id')
    if not temp_id:
        temp_id = str(uuid.uuid4())
        session['temp_id'] = temp_id
    path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_{temp_id}.json")
    with open(path, 'w') as f:
        json.dump(data, f)


def clear_temp_data():
    """Clear temporary data."""
    temp_id = session.get('temp_id')
    if temp_id:
        path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_{temp_id}.json")
        if os.path.exists(path):
            os.remove(path)
        session.pop('temp_id', None)


# ===== Routes =====

@app.route('/')
def index():
    """Dashboard page."""
    tests = MockTest.query.order_by(MockTest.created_at.desc()).limit(5).all()
    total_tests = MockTest.query.count()
    total_attempts = TestAttempt.query.count()

    # Calculate average and best scores
    attempts = TestAttempt.query.all()
    avg_score = 0
    best_score = 0
    if attempts:
        accuracies = [a.accuracy_percent for a in attempts]
        avg_score = sum(accuracies) / len(accuracies)
        best_score = max(accuracies)

    stats = {
        'total_tests': total_tests,
        'total_attempts': total_attempts,
        'avg_score': avg_score,
        'best_score': best_score,
    }

    return render_template('index.html', stats=stats, recent_tests=tests)


@app.route('/upload')
def upload():
    """Upload page."""
    return render_template('upload.html')


@app.route('/upload/process', methods=['POST'])
def upload_files():
    """Process uploaded PDF and answer key."""
    # Validate PDF file
    if 'pdf_file' not in request.files:
        flash('Please upload a PDF file.', 'error')
        return redirect(url_for('upload'))

    pdf_file = request.files['pdf_file']
    if pdf_file.filename == '' or not allowed_file(pdf_file.filename, 'pdf'):
        flash('Invalid PDF file. Please upload a .pdf file.', 'error')
        return redirect(url_for('upload'))

    # Validate answer key file
    if 'key_file' not in request.files:
        flash('Please upload an answer key image.', 'error')
        return redirect(url_for('upload'))

    key_file = request.files['key_file']
    if key_file.filename == '' or not allowed_file(key_file.filename, 'image'):
        flash('Invalid image file. Please upload a PNG or JPG file.', 'error')
        return redirect(url_for('upload'))

    # Save files
    pdf_filename = secure_filename(pdf_file.filename)
    key_filename = secure_filename(key_file.filename)

    # Add timestamp to avoid conflicts
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    pdf_filename = f"{timestamp}_{pdf_filename}"
    key_filename = f"{timestamp}_{key_filename}"

    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], pdf_filename)
    key_path = os.path.join(app.config['UPLOAD_FOLDER'], key_filename)

    pdf_file.save(pdf_path)
    key_file.save(key_path)

    try:
        # Parse PDF — extract text AND images
        text, page_boundaries, page_images = extract_text_and_images_from_pdf(
            pdf_path, app.config['UPLOAD_FOLDER']
        )
        questions = parse_questions(text)

        if not questions:
            flash('Could not extract any questions from the PDF. Please check the file format.', 'error')
            return redirect(url_for('upload'))

        # Assign sections if detected
        questions = assign_sections_to_questions(questions, text)

        # Assign extracted images to questions based on page mapping
        questions = assign_images_to_questions(questions, text, page_boundaries, page_images)

        # Parse answer key
        answer_key, raw_ocr_text = extract_answer_key(key_path)

        # Validate answer key
        warnings = validate_answer_key(answer_key, len(questions))

        # Count images extracted
        total_images = sum(len(imgs) for imgs in page_images.values())

        # Store on disk for preview
        temp_data = {
            'parsed_questions': questions,
            'answer_key': {str(k): v for k, v in answer_key.items()},
            'raw_ocr_text': raw_ocr_text,
            'pdf_path': pdf_path,
            'warnings': warnings
        }
        save_temp_data(temp_data)

        img_msg = f" and {total_images} image(s)" if total_images > 0 else ""
        flash(f'Successfully parsed {len(questions)} questions, {len(answer_key)} answers{img_msg}!', 'success')
        return redirect(url_for('preview'))

    except Exception as e:
        flash(f'Error processing files: {str(e)}', 'error')
        return redirect(url_for('upload'))


@app.route('/preview')
def preview():
    """Preview parsed questions and answer key."""
    temp_data = get_temp_data()
    questions = temp_data.get('parsed_questions', [])
    answer_key_str = temp_data.get('answer_key', {})
    answer_key = {int(k): v for k, v in answer_key_str.items()}
    raw_ocr_text = temp_data.get('raw_ocr_text', '')
    pdf_path = temp_data.get('pdf_path', '')
    warnings = temp_data.get('warnings', [])

    if not questions:
        flash('No parsed questions found. Please upload a PDF first.', 'warning')
        return redirect(url_for('upload'))

    return render_template('preview.html',
                           questions=questions,
                           answer_key=answer_key,
                           raw_ocr_text=raw_ocr_text,
                           pdf_path=pdf_path,
                           warnings=warnings)


@app.route('/preview/save', methods=['POST'])
def save_preview():
    """Save edited questions and answer key, then redirect to setup."""
    total_questions = int(request.form.get('total_questions', 0))

    questions = []
    answer_key = {}

    for i in range(1, total_questions + 1):
        q_text = request.form.get(f'q_{i}_text', '').strip()
        if not q_text:
            continue

        opt_a = request.form.get(f'q_{i}_a', '').strip()
        opt_b = request.form.get(f'q_{i}_b', '').strip()
        opt_c = request.form.get(f'q_{i}_c', '').strip()
        opt_d = request.form.get(f'q_{i}_d', '').strip()
        opt_e = request.form.get(f'q_{i}_e', '').strip()

        # Determine question type based on whether options exist
        q_type = request.form.get(f'q_{i}_type', '').strip()
        if not q_type:
            q_type = 'mcq' if (opt_a or opt_b or opt_c or opt_d) else 'text'

        questions.append({
            'question_number': len(questions) + 1,
            'question_text': q_text,
            'question_type': q_type,
            'option_a': opt_a,
            'option_b': opt_b,
            'option_c': opt_c,
            'option_d': opt_d,
            'option_e': opt_e,
            'section_name': request.form.get(f'q_{i}_section', 'General').strip() or 'General',
            'question_image': request.form.get(f'q_{i}_image', '').strip(),
        })

        # Answer key: for MCQ it's A-E, for text it can be any value
        key_val = request.form.get(f'key_{i}', '').strip()
        if key_val:
            if q_type == 'mcq':
                key_val = key_val.upper()
            answer_key[len(questions)] = key_val

    if not questions:
        flash('No valid questions found. Please try again.', 'error')
        return redirect(url_for('upload'))

    # Merge answer key into questions
    for q in questions:
        q_num = q['question_number']
        q['correct_answer'] = answer_key.get(q_num, '')

    # Get unique sections
    sections = list(set(q.get('section_name', 'General') for q in questions))

    # Store for setup page
    temp_data = get_temp_data()
    temp_data['final_questions'] = questions
    temp_data['sections'] = sections
    save_temp_data(temp_data)

    return redirect(url_for('setup'))


@app.route('/setup')
def setup():
    """Test setup page — configure timer, name, scoring."""
    temp_data = get_temp_data()
    questions = temp_data.get('final_questions', [])
    sections = temp_data.get('sections', ['General'])

    if not questions:
        flash('No questions found. Please upload a PDF first.', 'warning')
        return redirect(url_for('upload'))

    # Suggest a test name
    suggested_name = f"Mock Test — {datetime.now().strftime('%b %d, %Y')}"

    return render_template('setup.html',
                           questions_json=json.dumps(questions),
                           total_questions=len(questions),
                           sections=sections,
                           suggested_name=suggested_name)


@app.route('/test/create', methods=['POST'])
def create_test():
    """Create the test in the database and redirect to test page."""
    questions_data = json.loads(request.form.get('questions_json', '[]'))
    test_name = request.form.get('test_name', 'Untitled Test')
    timer_minutes = int(request.form.get('timer_minutes', 60))

    if timer_minutes == 0:  # custom timer
        timer_minutes = int(request.form.get('custom_timer', 60))

    # Handle "custom" option from select
    if request.form.get('timer_minutes') == 'custom':
        timer_minutes = int(request.form.get('custom_timer', 60))

    marks_correct = float(request.form.get('marks_correct', 1))
    marks_wrong = float(request.form.get('marks_wrong', -1))
    negative_marking = 'negative_marking' in request.form

    if not negative_marking:
        marks_wrong = 0

    # Create test in database
    sections = list(set(q.get('section_name', 'General') for q in questions_data))

    test = MockTest(
        name=test_name,
        timer_minutes=timer_minutes,
        total_questions=len(questions_data),
        negative_marking=negative_marking,
        marks_correct=marks_correct,
        marks_wrong=marks_wrong,
    )
    test.sections = sections
    db.session.add(test)
    db.session.flush()  # Get the test ID

    # Add questions
    for q_data in questions_data:
        question = Question(
            test_id=test.id,
            question_number=q_data['question_number'],
            question_text=q_data['question_text'],
            question_type=q_data.get('question_type', 'mcq'),
            option_a=q_data.get('option_a', ''),
            option_b=q_data.get('option_b', ''),
            option_c=q_data.get('option_c', ''),
            option_d=q_data.get('option_d', ''),
            option_e=q_data.get('option_e', ''),
            correct_answer=q_data.get('correct_answer', ''),
            section_name=q_data.get('section_name', 'General'),
            question_image=q_data.get('question_image', ''),
        )
        db.session.add(question)

    db.session.commit()

    # Clear temp data
    clear_temp_data()

    flash(f'Test "{test_name}" created successfully!', 'success')
    return redirect(url_for('start_test', test_id=test.id))


@app.route('/test/<int:test_id>')
def start_test(test_id):
    """Start a mock test."""
    test = MockTest.query.get_or_404(test_id)
    questions = Question.query.filter_by(test_id=test_id).order_by(Question.question_number).all()

    # Create a new attempt
    attempt = TestAttempt(
        test_id=test.id,
        max_score=test.marks_correct * test.total_questions,
    )
    db.session.add(attempt)
    db.session.commit()

    # Prepare questions JSON for frontend
    questions_json = json.dumps([q.to_dict() for q in questions])

    return render_template('test.html',
                           test=test,
                           questions=questions,
                           questions_json=questions_json,
                           attempt=attempt)


@app.route('/test/submit', methods=['POST'])
def submit_test():
    """Process test submission and calculate results."""
    test_id = int(request.form.get('test_id'))
    attempt_id = int(request.form.get('attempt_id'))
    answers_json = request.form.get('answers_json', '{}')
    time_taken = int(request.form.get('time_taken', 0))
    question_times_json = request.form.get('question_times_json', '{}')

    test = MockTest.query.get_or_404(test_id)
    attempt = TestAttempt.query.get_or_404(attempt_id)
    questions = Question.query.filter_by(test_id=test_id).order_by(Question.question_number).all()

    answers = json.loads(answers_json)  # { "0": "A", "1": "B", ... } (0-indexed)
    question_times = json.loads(question_times_json)

    total_correct = 0
    total_wrong = 0
    total_skipped = 0
    total_attempted = 0
    score = 0

    # Section tracking
    section_scores = {}

    for i, question in enumerate(questions):
        selected = answers.get(str(i), '')
        is_correct = False
        time_spent = int(question_times.get(str(i), 0))

        section = question.section_name or 'General'
        if section not in section_scores:
            section_scores[section] = {
                'total': 0, 'attempted': 0, 'correct': 0, 'wrong': 0,
                'skipped': 0, 'score': 0, 'accuracy': 0
            }
        section_scores[section]['total'] += 1

        if selected:
            total_attempted += 1
            section_scores[section]['attempted'] += 1

            # Compare answers — for text type, do case-insensitive comparison
            correct_ans = (question.correct_answer or '').strip()
            selected_clean = selected.strip()

            if question.question_type == 'text':
                # For text/numerical answers: case-insensitive, strip whitespace
                is_correct = selected_clean.lower() == correct_ans.lower()
            else:
                # For MCQ: exact match (A, B, C, D, E)
                is_correct = selected_clean == correct_ans

            if is_correct:
                total_correct += 1
                score += test.marks_correct
                section_scores[section]['correct'] += 1
                section_scores[section]['score'] += test.marks_correct
            else:
                total_wrong += 1
                score += test.marks_wrong  # negative marking
                section_scores[section]['wrong'] += 1
                section_scores[section]['score'] += test.marks_wrong
        else:
            total_skipped += 1
            section_scores[section]['skipped'] += 1

        # Save user answer
        user_answer = UserAnswer(
            attempt_id=attempt.id,
            question_id=question.id,
            selected_answer=selected,
            is_correct=is_correct,
            time_spent_seconds=time_spent,
        )
        db.session.add(user_answer)

    # Calculate section accuracies
    for section in section_scores:
        data = section_scores[section]
        data['accuracy'] = (data['correct'] / data['attempted'] * 100) if data['attempted'] > 0 else 0

    # Update attempt
    attempt.finished_at = datetime.now()
    attempt.score = score
    attempt.max_score = test.marks_correct * test.total_questions
    attempt.total_attempted = total_attempted
    attempt.total_correct = total_correct
    attempt.total_wrong = total_wrong
    attempt.total_skipped = total_skipped
    attempt.time_taken_seconds = time_taken
    attempt.accuracy_percent = (total_correct / total_attempted * 100) if total_attempted > 0 else 0
    attempt.section_scores = section_scores

    db.session.commit()

    return redirect(url_for('report', attempt_id=attempt.id))


@app.route('/report/<int:attempt_id>')
def report(attempt_id):
    """Detailed performance report."""
    attempt = TestAttempt.query.get_or_404(attempt_id)
    test = attempt.test
    questions = Question.query.filter_by(test_id=test.id).order_by(Question.question_number).all()
    user_answers = {ua.question_id: ua for ua in UserAnswer.query.filter_by(attempt_id=attempt.id).all()}

    section_scores = attempt.section_scores

    # Build review data
    review_data = []
    for q in questions:
        ua = user_answers.get(q.id)
        selected = ua.selected_answer if ua else ''
        is_correct = ua.is_correct if ua else False
        time_spent = ua.time_spent_seconds if ua else 0

        if not selected:
            status = 'skipped'
        elif is_correct:
            status = 'correct'
        else:
            status = 'wrong'

        review_data.append({
            'question_number': q.question_number,
            'question_text': q.question_text,
            'question_type': q.question_type or 'mcq',
            'question_image': q.question_image or '',
            'section_name': q.section_name,
            'correct_answer': q.correct_answer,
            'selected_answer': selected,
            'status': status,
            'time_spent': time_spent,
            'options': [
                ('A', q.option_a),
                ('B', q.option_b),
                ('C', q.option_c),
                ('D', q.option_d),
                ('E', q.option_e),
            ]
        })

    return render_template('report.html',
                           attempt=attempt,
                           test=test,
                           review_data=review_data,
                           section_scores=section_scores,
                           section_scores_json=json.dumps(section_scores))


@app.route('/history')
def history():
    """Test history page."""
    tests = MockTest.query.order_by(MockTest.created_at.desc()).all()
    return render_template('history.html', tests=tests)


@app.route('/test/<int:test_id>/delete', methods=['POST'])
def delete_test(test_id):
    """Delete a test and all its data."""
    test = MockTest.query.get_or_404(test_id)
    db.session.delete(test)
    db.session.commit()
    flash(f'Test "{test.name}" deleted.', 'info')
    return redirect(url_for('history'))


# ===== Error Handlers =====

@app.errorhandler(404)
def not_found(e):
    flash('Page not found.', 'error')
    return redirect(url_for('index'))


@app.errorhandler(500)
def server_error(e):
    flash(f'Server error: {str(e)}', 'error')
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, port=5000)
