#!/usr/bin/env python3
"""
Simple test script for the Media Player REST API
Run this after starting the player to test API endpoints
"""

import requests
import time
import json

API_BASE = "http://localhost:5000/api"

def test_endpoint(method, endpoint, data=None):
    """Test an API endpoint and print results"""
    url = f"{API_BASE}{endpoint}"
    try:
        if method == "GET":
            response = requests.get(url, timeout=5)
        else:
            response = requests.post(url, json=data, timeout=5)
        
        print(f"{method} {endpoint}: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"  Response: {json.dumps(result, indent=2)}")
        else:
            print(f"  Error: {response.text}")
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"{method} {endpoint}: ERROR - {e}")
        return False

def main():
    print("Testing Media Player REST API")
    print("=" * 40)
    
    # Test status endpoint
    print("\n1. Testing status endpoint...")
    test_endpoint("GET", "/status")
    
    # Test playback control
    print("\n2. Testing playback control...")
    test_endpoint("POST", "/play")
    time.sleep(1)
    test_endpoint("POST", "/pause")
    time.sleep(1)
    test_endpoint("POST", "/play")
    
    # Test seeking
    print("\n3. Testing seeking...")
    test_endpoint("POST", "/seek-forward", {"seconds": 10})
    time.sleep(1)
    test_endpoint("POST", "/seek-backward", {"seconds": 5})
    
    # Test volume
    print("\n4. Testing volume control...")
    test_endpoint("POST", "/volume", {"volume": 75})
    time.sleep(1)
    test_endpoint("POST", "/volume", {"volume": 50})
    
    # Test playlist navigation
    print("\n5. Testing playlist navigation...")
    test_endpoint("POST", "/next")
    time.sleep(1)
    test_endpoint("POST", "/previous")
    
    print("\n" + "=" * 40)
    print("API testing completed!")

if __name__ == "__main__":
    main()
