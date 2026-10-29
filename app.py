"""
API Behavior Tracker - Main Application
Monitors and logs all API requests, stores them in PostgreSQL,
and provides analytics endpoints.
"""

import os
import time
import logging
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, desc, case, text
import boto3
from botocore.exceptions import ClientError

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Do not write these to the request log (edit this list as needed).
# '/api/analytics' also skips everything under /api/analytics/.
SKIP_LOG_PATHS = [
    '/health',
    '/dashboard',
    '/api/analytics',
]

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    'postgresql+psycopg2://api_tracker:password@localhost:5432/api_tracker'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db = SQLAlchemy(app)

# AWS CloudWatch configuration
cloudwatch_logs = None
log_group_name = os.getenv('CLOUDWATCH_LOG_GROUP', 'api-behavior-tracker')
log_stream_name = os.getenv('CLOUDWATCH_LOG_STREAM', 'api-requests')

# Initialize CloudWatch if AWS credentials are available
try:
    if os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'):
        cloudwatch_logs = boto3.client(
            'logs',
            region_name=os.getenv('AWS_REGION', 'us-east-1')
        )
        # Create log group if it doesn't exist
        try:
            cloudwatch_logs.create_log_group(logGroupName=log_group_name)
        except ClientError as e:
            if e.response['Error']['Code'] != 'ResourceAlreadyExistsException':
                raise
except Exception as e:
    print("CloudWatch initialization warning: %s", e)

# In-memory sequence token for CloudWatch (used if API returns InvalidSequenceTokenException)
_cloudwatch_sequence_token = None


def _put_cloudwatch_log(method, endpoint, status_code, latency_ms):
    """Send a single log event to CloudWatch; handles sequence token for older APIs."""
    global _cloudwatch_sequence_token
    payload = {
        "logGroupName": log_group_name,
        "logStreamName": log_stream_name,
        "logEvents": [{
            "timestamp": int(time.time() * 1000),
            "message": f"{method} {endpoint} - {status_code} - {latency_ms:.2f}ms"
        }]
    }
    if _cloudwatch_sequence_token:
        payload["sequenceToken"] = _cloudwatch_sequence_token
    try:
        resp = cloudwatch_logs.put_log_events(**payload)
        _cloudwatch_sequence_token = resp.get("nextSequenceToken")
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "InvalidSequenceTokenException":
            token = e.response.get("Error", {}).get("expectedSequenceToken")
            if token:
                _cloudwatch_sequence_token = token
                payload["sequenceToken"] = token
                resp = cloudwatch_logs.put_log_events(**payload)
                _cloudwatch_sequence_token = resp.get("nextSequenceToken")
                return
        raise

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Database Models
class APIRequest(db.Model):
    """Model to store API request logs"""
    __tablename__ = 'api_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    endpoint = db.Column(db.String(500), nullable=False, index=True)
    method = db.Column(db.String(10), nullable=False, index=True)
    status_code = db.Column(db.Integer, nullable=False, index=True)
    latency_ms = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))
    
    def to_dict(self):
        return {
            'id': self.id,
            'endpoint': self.endpoint,
            'method': self.method,
            'status_code': self.status_code,
            'latency_ms': self.latency_ms,
            'timestamp': self.timestamp.isoformat(),
            'ip_address': self.ip_address,
            'user_agent': self.user_agent
        }


# Lazy DB init flag (avoids startup failure when DB not ready in K8s)
_db_initialized = False


def _should_skip_logging(path):
    """True if this path is in SKIP_LOG_PATHS (exact or prefix)."""
    for skipped in SKIP_LOG_PATHS:
        if path == skipped or path.startswith(skipped + '/'):
            return True
    return False


# Middleware to log all requests
@app.before_request
def log_request():
    """Log every incoming request"""
    global _db_initialized
    request.start_time = time.time()
    # Lazy DB init on first request (K8s-friendly: app can start before Postgres is ready)
    if not _db_initialized:
        try:
            db.create_all()
            _db_initialized = True
            logger.info("Database tables initialized")
        except Exception as e:
            logger.debug("Database not ready yet: %s", e)


@app.after_request
def log_response(response):
    """Log response and store in database"""
    if _should_skip_logging(request.path):
        return response

    # Calculate latency
    start = getattr(request, 'start_time', time.time())
    latency_ms = (time.time() - start) * 1000
    
    # Extract request details
    # Save the route template (/users/<id>), not /users/1; unknown routes → "unmatched"
    endpoint = request.url_rule.rule if request.url_rule else 'unmatched'
    method = request.method
    status_code = response.status_code
    ip_address = request.remote_addr
    user_agent = request.headers.get('User-Agent', '')
    
    # Log to CloudWatch if available
    if cloudwatch_logs:
        try:
            _put_cloudwatch_log(method, endpoint, status_code, latency_ms)
        except Exception as e:
            logger.warning("Failed to log to CloudWatch: %s", e)
    
    # Store in database (async in production, sync for simplicity)
    try:
        api_request = APIRequest(
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            latency_ms=latency_ms,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.session.add(api_request)
        db.session.commit()
    except Exception as e:
        logger.error("Failed to log request to database: %s", e)
        db.session.rollback()
    
    return response


@app.route('/dashboard', methods=['GET'])
def dashboard():
    """Serve the analytics dashboard HTML page."""
    return render_template('dashboard.html')


# Health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now(timezone.utc).isoformat()
    }), 200


# Analytics Endpoints
def _parse_hours(default=24, max_hours=720):
    """Parse and clamp hours query param (max 30 days)."""
    hours = request.args.get('hours', default, type=int)
    return max(1, min(hours, max_hours))


@app.route('/api/analytics/most-used', methods=['GET'])
def get_most_used_endpoints():
    """Get most frequently used endpoints"""
    limit = min(request.args.get('limit', 10, type=int), 1000)
    limit = max(1, limit)
    hours = _parse_hours()
    
    # Calculate time threshold
    time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    results = db.session.query(
        APIRequest.endpoint,
        APIRequest.method,
        func.count(APIRequest.id).label('count')
    ).filter(
        APIRequest.timestamp >= time_threshold
    ).group_by(
        APIRequest.endpoint,
        APIRequest.method
    ).order_by(
        desc('count')
    ).limit(limit).all()
    
    return jsonify({
        'timeframe_hours': hours,
        'results': [
            {
                'endpoint': r.endpoint,
                'method': r.method,
                'request_count': r.count
            }
            for r in results
        ]
    }), 200


@app.route('/api/analytics/error-rates', methods=['GET'])
def get_error_rates():
    """Get error rates by endpoint"""
    hours = _parse_hours()
    
    time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    # Get total requests and error requests per endpoint
    total_requests = db.session.query(
        APIRequest.endpoint,
        APIRequest.method,
        func.count(APIRequest.id).label('total')
    ).filter(
        APIRequest.timestamp >= time_threshold
    ).group_by(
        APIRequest.endpoint,
        APIRequest.method
    ).subquery()
    
    error_requests = db.session.query(
        APIRequest.endpoint,
        APIRequest.method,
        func.count(APIRequest.id).label('errors')
    ).filter(
        APIRequest.timestamp >= time_threshold,
        APIRequest.status_code >= 400
    ).group_by(
        APIRequest.endpoint,
        APIRequest.method
    ).subquery()
    
    # Join and calculate error rates
    results = db.session.query(
        total_requests.c.endpoint,
        total_requests.c.method,
        total_requests.c.total,
        func.coalesce(error_requests.c.errors, 0).label('errors'),
        func.round(
            func.coalesce(error_requests.c.errors, 0) * 100.0 / total_requests.c.total,
            2
        ).label('error_rate_percent')
    ).outerjoin(
        error_requests,
        (total_requests.c.endpoint == error_requests.c.endpoint) &
        (total_requests.c.method == error_requests.c.method)
    ).order_by(
        desc('error_rate_percent')
    ).all()
    
    return jsonify({
        'timeframe_hours': hours,
        'results': [
            {
                'endpoint': r.endpoint,
                'method': r.method,
                'total_requests': r.total,
                'error_count': r.errors,
                'error_rate_percent': float(r.error_rate_percent)
            }
            for r in results
        ]
    }), 200


def _round2(value):
    """Round a numeric value to 2 decimals; None → 0.0."""
    return round(float(value), 2) if value is not None else 0.0


def _pg_percentile(fraction):
    """PostgreSQL percentile_cont(fraction) WITHIN GROUP (ORDER BY latency_ms)."""
    return func.percentile_cont(fraction).within_group(APIRequest.latency_ms)


def _python_percentile(values, fraction):
    """Linear interpolation (same idea as percentile_cont) for SQLite tests."""
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return _round2(xs[0])
    k = (len(xs) - 1) * fraction
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    if lo == hi:
        return _round2(xs[lo])
    return _round2(xs[lo] * (hi - k) + xs[hi] * (k - lo))


def _is_postgres():
    return db.engine.dialect.name == 'postgresql'


@app.route('/api/analytics/response-times', methods=['GET'])
def get_average_response_times():
    """Get average response times by endpoint"""
    hours = _parse_hours()
    
    time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
    time_filter = APIRequest.timestamp >= time_threshold
    
    if _is_postgres():
        results = db.session.query(
            APIRequest.endpoint,
            APIRequest.method,
            func.avg(APIRequest.latency_ms).label('avg_latency'),
            func.min(APIRequest.latency_ms).label('min_latency'),
            func.max(APIRequest.latency_ms).label('max_latency'),
            func.count(APIRequest.id).label('request_count'),
            _pg_percentile(0.5).label('p50_latency'),
            _pg_percentile(0.95).label('p95_latency'),
        ).filter(
            time_filter
        ).group_by(
            APIRequest.endpoint,
            APIRequest.method
        ).order_by(
            desc('avg_latency')
        ).all()
        rows = [
            {
                'endpoint': r.endpoint,
                'method': r.method,
                'avg_latency_ms': _round2(r.avg_latency),
                'min_latency_ms': _round2(r.min_latency),
                'max_latency_ms': _round2(r.max_latency),
                'request_count': r.request_count,
                'p50_latency': _round2(r.p50_latency),
                'p95_latency': _round2(r.p95_latency),
            }
            for r in results
        ]
    else:
        # SQLite has no percentile_cont — reuse avg/min/max SQL, percentiles in Python
        results = db.session.query(
            APIRequest.endpoint,
            APIRequest.method,
            func.avg(APIRequest.latency_ms).label('avg_latency'),
            func.min(APIRequest.latency_ms).label('min_latency'),
            func.max(APIRequest.latency_ms).label('max_latency'),
            func.count(APIRequest.id).label('request_count')
        ).filter(
            time_filter
        ).group_by(
            APIRequest.endpoint,
            APIRequest.method
        ).order_by(
            desc('avg_latency')
        ).all()
        latencies = db.session.query(
            APIRequest.endpoint, APIRequest.method, APIRequest.latency_ms
        ).filter(time_filter).all()
        by_key = {}
        for endpoint, method, latency in latencies:
            by_key.setdefault((endpoint, method), []).append(latency)
        rows = [
            {
                'endpoint': r.endpoint,
                'method': r.method,
                'avg_latency_ms': _round2(r.avg_latency),
                'min_latency_ms': _round2(r.min_latency),
                'max_latency_ms': _round2(r.max_latency),
                'request_count': r.request_count,
                'p50_latency': _python_percentile(by_key.get((r.endpoint, r.method), []), 0.5),
                'p95_latency': _python_percentile(by_key.get((r.endpoint, r.method), []), 0.95),
            }
            for r in results
        ]
    
    return jsonify({
        'timeframe_hours': hours,
        'results': rows
    }), 200


@app.route('/api/analytics/summary', methods=['GET'])
def get_summary():
    """Get overall summary statistics"""
    hours = _parse_hours()
    
    time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    # Total requests
    total_requests = db.session.query(func.count(APIRequest.id)).filter(
        APIRequest.timestamp >= time_threshold
    ).scalar()
    
    # Error count
    error_count = db.session.query(func.count(APIRequest.id)).filter(
        APIRequest.timestamp >= time_threshold,
        APIRequest.status_code >= 400
    ).scalar()
    
    # Average latency
    avg_latency = db.session.query(func.avg(APIRequest.latency_ms)).filter(
        APIRequest.timestamp >= time_threshold
    ).scalar()
    
    # Unique endpoints
    unique_endpoints = db.session.query(func.count(func.distinct(APIRequest.endpoint))).filter(
        APIRequest.timestamp >= time_threshold
    ).scalar()
    
    # Overall p95 (Postgres percentile_cont; Python fallback on SQLite)
    if _is_postgres():
        p95_latency = db.session.query(
            _pg_percentile(0.95)
        ).filter(
            APIRequest.timestamp >= time_threshold
        ).scalar()
        p95_latency = _round2(p95_latency)
    else:
        lats = [row[0] for row in db.session.query(APIRequest.latency_ms).filter(
            APIRequest.timestamp >= time_threshold
        ).all()]
        p95_latency = _python_percentile(lats, 0.95)
    
    return jsonify({
        'timeframe_hours': hours,
        'summary': {
            'total_requests': total_requests or 0,
            'error_count': error_count or 0,
            'error_rate_percent': round((error_count or 0) * 100.0 / (total_requests or 1), 2),
            'avg_latency_ms': round(float(avg_latency or 0), 2),
            'unique_endpoints': unique_endpoints or 0,
            'p95_latency': p95_latency
        }
    }), 200


def _aware_utc(dt):
    """Normalize a datetime to timezone-aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _align_bucket(dt, hours):
    """Snap dt to hour (if hours > 24) or 5-minute (if hours <= 24)."""
    dt = _aware_utc(dt).replace(second=0, microsecond=0)
    if hours > 24:
        return dt.replace(minute=0)
    return dt.replace(minute=(dt.minute // 5) * 5)


def _pg_bucket_column(hours):
    """PostgreSQL bucket: date_trunc hour, or minute truncated down to 5 minutes."""
    ts = APIRequest.timestamp
    if hours > 24:
        return func.date_trunc('hour', ts)
    # date_trunc('minute') then subtract leftover minutes (0–4)
    return func.date_trunc('minute', ts) - (
        func.extract('minute', ts) % 5
    ) * text("interval '1 minute'")


@app.route('/api/analytics/timeseries', methods=['GET'])
def get_timeseries():
    """Request counts per time bucket (hourly or 5-minute)."""
    hours = _parse_hours()
    now = datetime.now(timezone.utc)
    time_threshold = now - timedelta(hours=hours)

    if _is_postgres():
        bucket_col = _pg_bucket_column(hours)
        grouped = db.session.query(
            bucket_col.label('bucket'),
            func.count(APIRequest.id).label('total'),
            func.coalesce(
                func.sum(case((APIRequest.status_code >= 400, 1), else_=0)),
                0
            ).label('errors')
        ).filter(
            APIRequest.timestamp >= time_threshold
        ).group_by(
            bucket_col
        ).all()
        counts = {
            _align_bucket(row.bucket, hours): {'total': int(row.total), 'errors': int(row.errors)}
            for row in grouped if row.bucket is not None
        }
    else:
        # SQLite has no date_trunc — group in Python
        raw = db.session.query(APIRequest.timestamp, APIRequest.status_code).filter(
            APIRequest.timestamp >= time_threshold
        ).all()
        counts = {}
        for ts, status in raw:
            key = _align_bucket(ts, hours)
            slot = counts.setdefault(key, {'total': 0, 'errors': 0})
            slot['total'] += 1
            if status >= 400:
                slot['errors'] += 1

    if not counts:
        return jsonify({'timeframe_hours': hours, 'results': []}), 200

    step = timedelta(hours=1) if hours > 24 else timedelta(minutes=5)
    t = _align_bucket(time_threshold, hours)
    end = _align_bucket(now, hours)
    results = []
    while t <= end:
        slot = counts.get(t, {'total': 0, 'errors': 0})
        results.append({
            'bucket': t.isoformat(),
            'total': slot['total'],
            'errors': slot['errors'],
        })
        t += step

    return jsonify({'timeframe_hours': hours, 'results': results}), 200


@app.route('/api/requests', methods=['GET'])
def get_recent_requests():
    """Get recent API requests"""
    limit = min(request.args.get('limit', 100, type=int), 1000)
    limit = max(1, limit)
    hours = _parse_hours(default=1)
    
    time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    requests = APIRequest.query.filter(
        APIRequest.timestamp >= time_threshold
    ).order_by(
        desc(APIRequest.timestamp)
    ).limit(limit).all()
    
    return jsonify({
        'count': len(requests),
        'requests': [r.to_dict() for r in requests]
    }), 200


if __name__ == '__main__':
    # Run the app
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
