"""
Test script to verify the full video generation pipeline.

Usage:
    python test_pipeline.py "self attention mechanism"
"""

import sys
import requests
import time
import json

def test_pipeline(topic: str):
    """Test the full pipeline with a given topic."""
    print(f"Testing pipeline with topic: '{topic}'")
    print("=" * 60)
    
    # Step 1: Submit job
    print("\n[1/3] Submitting job to orchestrator...")
    try:
        response = requests.post(
            "http://localhost:8000/generate",
            json={"topic": topic},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        job_id = data.get("job_id")
        print(f"✓ Job submitted successfully: {job_id}")
    except requests.exceptions.ConnectionError:
        print("✗ ERROR: Cannot connect to orchestrator at http://localhost:8000")
        print("  Make sure Docker Compose is running:")
        print("  docker compose up")
        return False
    except Exception as e:
        print(f"✗ ERROR: {e}")
        return False
    
    # Step 2: Poll job status
    print(f"\n[2/3] Polling job status...")
    max_wait = 600  # 10 minutes
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        try:
            response = requests.get(f"http://localhost:8000/job/{job_id}")
            response.raise_for_status()
            status_data = response.json()
            status = status_data.get("status", "unknown")
            
            print(f"  Status: {status}")
            
            if status == "completed":
                print(f"✓ Job completed successfully!")
                final_output = status_data.get("final_output_path")
                print(f"  Final video: {final_output}")
                return True
            elif status == "failed":
                error = status_data.get("overall_error", "Unknown error")
                print(f"✗ Job failed: {error}")
                return False
            
            time.sleep(5)
        except Exception as e:
            print(f"✗ ERROR polling status: {e}")
            return False
    
    print(f"✗ Timeout: Job did not complete within {max_wait} seconds")
    return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_pipeline.py \"<topic>\"")
        print("Example: python test_pipeline.py \"self attention mechanism\"")
        sys.exit(1)
    
    topic = " ".join(sys.argv[1:])
    success = test_pipeline(topic)
    sys.exit(0 if success else 1)
