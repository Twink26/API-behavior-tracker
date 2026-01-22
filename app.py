"""
API Behavior Tracker - Main Application
Monitors and logs all API requests, stores them in PostgreSQL,
and provides analytics endpoints.
"""

import os
import time
import logging
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, desc
import boto3
from botocore.exceptions import ClientError

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    'postgresql://api_tracker:password@localhost:5432/api_tracker'
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
    print(f"CloudWatch initialization warning: {e}")

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
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
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


# Middleware to log all requests
@app.before_request
def log_request():
    """Log every incoming request"""
    request.start_time = time.time()


@app.after_request
def log_response(response):
    """Log response and store in database"""
    # Calculate latency
    latency_ms = (time.time() - request.start_time) * 1000
    
    # Extract request details
    endpoint = request.path
    method = request.method
    status_code = response.status_code
    ip_address = request.remote_addr
    user_agent = request.headers.get('User-Agent', '')
    
    # Log to CloudWatch if available
    if cloudwatch_logs:
        try:
            cloudwatch_logs.put_log_events(
                logGroupName=log_group_name,
                logStreamName=log_stream_name,
                logEvents=[{
                    'timestamp': int(time.time() * 1000),
                    'message': f"{method} {endpoint} - {status_code} - {latency_ms:.2f}ms"
                }]
            )
        except Exception as e:
            logger.warning(f"Failed to log to CloudWatch: {e}")
    
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
        logger.error(f"Failed to log request to database: {e}")
        db.session.rollback()
    
    return response


# Health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat()
    }), 200


# Analytics Endpoints

@app.route('/api/analytics/most-used', methods=['GET'])
def get_most_used_endpoints():
    """Get most frequently used endpoints"""
    limit = request.args.get('limit', 10, type=int)
    hours = request.args.get('hours', 24, type=int)
    
    # Calculate time threshold
    from datetime import timedelta
    time_threshold = datetime.utcnow() - timedelta(hours=hours)
    
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
    hours = request.args.get('hours', 24, type=int)
    
    from datetime import timedelta
    time_threshold = datetime.utcnow() - timedelta(hours=hours)
    
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


@app.route('/api/analytics/response-times', methods=['GET'])
def get_average_response_times():
    """Get average response times by endpoint"""
    hours = request.args.get('hours', 24, type=int)
    
    from datetime import timedelta
    time_threshold = datetime.utcnow() - timedelta(hours=hours)
    
    results = db.session.query(
        APIRequest.endpoint,
        APIRequest.method,
        func.avg(APIRequest.latency_ms).label('avg_latency'),
        func.min(APIRequest.latency_ms).label('min_latency'),
        func.max(APIRequest.latency_ms).label('max_latency'),
        func.count(APIRequest.id).label('request_count')
    ).filter(
        APIRequest.timestamp >= time_threshold
    ).group_by(
        APIRequest.endpoint,
        APIRequest.method
    ).order_by(
        desc('avg_latency')
    ).all()
    
    return jsonify({
        'timeframe_hours': hours,
        'results': [
            {
                'endpoint': r.endpoint,
                'method': r.method,
                'avg_latency_ms': round(float(r.avg_latency), 2),
                'min_latency_ms': round(float(r.min_latency), 2),
                'max_latency_ms': round(float(r.max_latency), 2),
                'request_count': r.request_count
            }
            for r in results
        ]
    }), 200


@app.route('/api/analytics/summary', methods=['GET'])
def get_summary():
    """Get overall summary statistics"""
    hours = request.args.get('hours', 24, type=int)
    
    from datetime import timedelta
    time_threshold = datetime.utcnow() - timedelta(hours=hours)
    
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
    
    return jsonify({
        'timeframe_hours': hours,
        'summary': {
            'total_requests': total_requests or 0,
            'error_count': error_count or 0,
            'error_rate_percent': round((error_count or 0) * 100.0 / (total_requests or 1), 2),
            'avg_latency_ms': round(float(avg_latency or 0), 2),
            'unique_endpoints': unique_endpoints or 0
        }
    }), 200


@app.route('/api/requests', methods=['GET'])
def get_recent_requests():
    """Get recent API requests"""
    limit = request.args.get('limit', 100, type=int)
    hours = request.args.get('hours', 1, type=int)
    
    from datetime import timedelta
    time_threshold = datetime.utcnow() - timedelta(hours=hours)
    
    requests = APIRequest.query.filter(
        APIRequest.timestamp >= time_threshold
    ).order_by(
        desc(APIRequest.timestamp)
    ).limit(limit).all()
    
    return jsonify({
        'count': len(requests),
        'requests': [r.to_dict() for r in requests]
    }), 200


# Initialize database tables on app startup
with app.app_context():
    try:
        db.create_all()
        logger.info("Database tables initialized")
    except Exception as e:
        logger.warning(f"Database initialization warning: {e}")


if __name__ == '__main__':
    # Run the app
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
