"""Test fixtures. The app is pointed at a throwaway DB before it is imported."""
import os
import sys
import tempfile

import pytest

# Make the project root importable (so "from app import ..." works)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Never use the real database: TEST_DATABASE_URL, or a temp SQLite file
if os.environ.get('TEST_DATABASE_URL'):
    os.environ['DATABASE_URL'] = os.environ['TEST_DATABASE_URL']
else:
    _tmp = tempfile.NamedTemporaryFile(prefix='api_tracker_test_', suffix='.db', delete=False)
    _tmp.close()
    os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.abspath(_tmp.name).replace('\\', '/')

from flask import jsonify  # noqa: E402
from app import app, db, APIRequest  # noqa: E402

# Extra route used only in tests to check endpoint normalization
if '/users/<id>' not in {rule.rule for rule in app.url_map.iter_rules()}:
    @app.route('/users/<id>')
    def _test_get_user(id):
        return jsonify({'id': id}), 200


@pytest.fixture
def client():
    """Flask test client + empty api_requests table for every test."""
    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        APIRequest.query.delete()
        db.session.commit()
    with app.test_client() as test_client:
        yield test_client
    with app.app_context():
        db.session.remove()
