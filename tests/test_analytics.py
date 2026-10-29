"""Analytics API behaviour."""
from datetime import datetime, timezone, timedelta

from app import app, db, APIRequest


def _insert_rows(status_codes, endpoint='/fake'):
    """Insert fake api_requests rows (used instead of going through HTTP)."""
    with app.app_context():
        now = datetime.now(timezone.utc)
        for i, status in enumerate(status_codes):
            db.session.add(APIRequest(
                endpoint=f'{endpoint}-{i}' if endpoint == '/unique' else endpoint,
                method='GET',
                status_code=status,
                latency_ms=10.0,
                timestamp=now,
            ))
        db.session.commit()


def test_summary_counts_and_error_rate(client):
    """10 rows with 3 errors should report total 10 and error rate 30."""
    _insert_rows([500, 500, 500] + [200] * 7)
    data = client.get('/api/analytics/summary').get_json()
    summary = data['summary']
    assert summary['total_requests'] == 10
    assert summary['error_count'] == 3
    assert summary['error_rate_percent'] == 30.0


def test_summary_empty_database(client):
    """Empty DB should return zeros and not crash."""
    data = client.get('/api/analytics/summary').get_json()
    summary = data['summary']
    assert summary['total_requests'] == 0
    assert summary['error_count'] == 0
    assert summary['error_rate_percent'] == 0.0
    assert summary['avg_latency_ms'] == 0.0
    assert summary['unique_endpoints'] == 0


def test_most_used_limit_is_capped(client):
    """limit=99999 must not return more than 1000 groups."""
    _insert_rows([200] * 1005, endpoint='/unique')
    data = client.get('/api/analytics/most-used?limit=99999').get_json()
    assert len(data['results']) <= 1000
    assert len(data['results']) == 1000


def test_response_times_p50_and_p95(client):
    """Latencies 1..100 ms should give p50 ~50 and p95 ~95."""
    with app.app_context():
        now = datetime.now(timezone.utc)
        for ms in range(1, 101):
            db.session.add(APIRequest(
                endpoint='/p95',
                method='GET',
                status_code=200,
                latency_ms=float(ms),
                timestamp=now,
            ))
        db.session.commit()
    data = client.get('/api/analytics/response-times').get_json()
    assert data['results']
    row = data['results'][0]
    assert 49 <= row['p50_latency'] <= 51
    assert 94 <= row['p95_latency'] <= 96
    # Existing fields must still be present
    assert row['avg_latency_ms'] == 50.5
    assert row['min_latency_ms'] == 1.0
    assert row['max_latency_ms'] == 100.0
    assert row['request_count'] == 100
    summary = client.get('/api/analytics/summary').get_json()['summary']
    assert 94 <= summary['p95_latency'] <= 96


def test_response_times_empty_database(client):
    """Empty DB should return [] / zeros and not crash."""
    times = client.get('/api/analytics/response-times').get_json()
    assert times['results'] == []
    summary = client.get('/api/analytics/summary').get_json()['summary']
    assert summary['p95_latency'] == 0.0


def test_timeseries_three_hours(client):
    """Rows in 3 different hours should land in 3 buckets with correct totals/errors."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    with app.app_context():
        rows = [
            (now - timedelta(hours=2), 200),
            (now - timedelta(hours=2), 200),
            (now - timedelta(hours=1), 500),
            (now, 200),
            (now, 404),
        ]
        for ts, status in rows:
            db.session.add(APIRequest(
                endpoint='/ts', method='GET', status_code=status,
                latency_ms=10.0, timestamp=ts,
            ))
        db.session.commit()
    data = client.get('/api/analytics/timeseries?hours=48').get_json()
    nonzero = [r for r in data['results'] if r['total'] > 0]
    assert len(nonzero) == 3
    assert [r['total'] for r in nonzero] == [2, 1, 2]
    assert [r['errors'] for r in nonzero] == [0, 1, 1]
    assert any(r['total'] == 0 for r in data['results'])


def test_timeseries_empty_database(client):
    """Empty DB should return an empty list and not crash."""
    data = client.get('/api/analytics/timeseries?hours=24').get_json()
    assert data['results'] == []


def test_timeseries_hours_is_capped(client):
    """hours=99999 must be capped at 720."""
    data = client.get('/api/analytics/timeseries?hours=99999').get_json()
    assert data['timeframe_hours'] == 720

