"""Request-logging behaviour."""
from app import app, APIRequest


def _rows():
    """All logged rows in the current app context."""
    with app.app_context():
        return APIRequest.query.all()


def test_request_is_logged(client):
    """A normal route writes one row with endpoint, method, status, and latency > 0."""
    client.get('/api/requests')
    rows = _rows()
    assert len(rows) == 1
    row = rows[0]
    assert row.endpoint == '/api/requests'
    assert row.method == 'GET'
    assert row.status_code == 200
    assert row.latency_ms > 0


def test_health_is_not_logged(client):
    """GET /health must not create a log row."""
    client.get('/health')
    assert _rows() == []


def test_dashboard_and_analytics_not_logged(client):
    """GET /dashboard and /api/analytics/summary must not create log rows."""
    client.get('/dashboard')
    client.get('/api/analytics/summary')
    assert _rows() == []


def test_unknown_route_saved_as_unmatched(client):
    """Unknown URLs are stored as endpoint 'unmatched' with status 404."""
    response = client.get('/this-route-does-not-exist')
    assert response.status_code == 404
    rows = _rows()
    assert len(rows) == 1
    assert rows[0].endpoint == 'unmatched'
    assert rows[0].status_code == 404


def test_endpoint_is_normalized(client):
    """Different IDs for /users/<id> should store one template, not each raw path."""
    client.get('/users/1')
    client.get('/users/2')
    endpoints = {row.endpoint for row in _rows()}
    assert endpoints == {'/users/<id>'}
