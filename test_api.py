#!/usr/bin/env python3
"""
Simple test script to generate sample API requests for testing the tracker
"""

import requests
import time
import random
from datetime import datetime

BASE_URL = "http://localhost:5000"

def test_health():
    """Test health endpoint"""
    print("Testing /health...")
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}\n")

def generate_sample_requests():
    """Generate sample API requests"""
    endpoints = [
        "/api/analytics/summary",
        "/api/analytics/most-used",
        "/api/analytics/error-rates",
        "/api/analytics/response-times",
        "/api/requests",
        "/health"
    ]
    
    print("Generating sample requests...")
    for i in range(20):
        endpoint = random.choice(endpoints)
        try:
            response = requests.get(f"{BASE_URL}{endpoint}")
            print(f"Request {i+1}: {endpoint} - Status: {response.status_code}")
            time.sleep(0.5)  # Small delay
        except Exception as e:
            print(f"Error: {e}")
    
    print("\nSample requests generated!\n")

def test_analytics():
    """Test analytics endpoints"""
    print("Testing analytics endpoints...")
    
    endpoints = {
        "Summary": "/api/analytics/summary?hours=24",
        "Most Used": "/api/analytics/most-used?limit=5",
        "Error Rates": "/api/analytics/error-rates?hours=24",
        "Response Times": "/api/analytics/response-times?hours=24",
        "Recent Requests": "/api/requests?limit=10"
    }
    
    for name, endpoint in endpoints.items():
        print(f"\n{name}:")
        try:
            response = requests.get(f"{BASE_URL}{endpoint}")
            if response.status_code == 200:
                data = response.json()
                print(f"  Status: {response.status_code}")
                if 'summary' in data:
                    print(f"  Total Requests: {data['summary'].get('total_requests', 0)}")
                    print(f"  Error Rate: {data['summary'].get('error_rate_percent', 0)}%")
                elif 'results' in data:
                    print(f"  Results Count: {len(data['results'])}")
                elif 'requests' in data:
                    print(f"  Requests Count: {data['count']}")
            else:
                print(f"  Status: {response.status_code}")
        except Exception as e:
            print(f"  Error: {e}")

if __name__ == "__main__":
    print("=" * 50)
    print("API Behavior Tracker - Test Script")
    print("=" * 50)
    print()
    
    # Test health
    test_health()
    
    # Generate sample requests
    generate_sample_requests()
    
    # Test analytics
    test_analytics()
    
    print("\n" + "=" * 50)
    print("Testing complete!")
    print("=" * 50)
