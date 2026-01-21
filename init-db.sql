-- Database initialization script
-- This is automatically handled by SQLAlchemy, but included for reference

CREATE DATABASE IF NOT EXISTS api_tracker;

-- The APIRequest table will be created automatically by SQLAlchemy
-- Schema:
-- CREATE TABLE api_requests (
--     id SERIAL PRIMARY KEY,
--     endpoint VARCHAR(500) NOT NULL,
--     method VARCHAR(10) NOT NULL,
--     status_code INTEGER NOT NULL,
--     latency_ms FLOAT NOT NULL,
--     timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
--     ip_address VARCHAR(45),
--     user_agent VARCHAR(500)
-- );

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_endpoint ON api_requests(endpoint);
CREATE INDEX IF NOT EXISTS idx_method ON api_requests(method);
CREATE INDEX IF NOT EXISTS idx_status_code ON api_requests(status_code);
CREATE INDEX IF NOT EXISTS idx_timestamp ON api_requests(timestamp);
