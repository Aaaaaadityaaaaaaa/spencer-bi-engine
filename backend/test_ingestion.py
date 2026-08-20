from fastapi.testclient import TestClient
from main import app
from services.redis_manager import redis_manager
import json

client = TestClient(app)

def test_ingestion():
    print("Starting test...")
    # 1. POST /sessions
    with open("messy.csv", "rb") as f:
        print("Sending POST /sessions...")
        response = client.post("/sessions", files={"file": ("messy.csv", f, "text/csv")})
        print("Response received!")
    
    print("--- POST /sessions RESPONSE ---")
    print(json.dumps(response.json(), indent=2))
    
    session_uuid = response.json()["session_uuid"]
    
    # 2. GET /sessions/{session_uuid}/schema
    schema_response = client.get(f"/sessions/{session_uuid}/schema")
    print("\n--- GET /sessions/{session_uuid}/schema RESPONSE ---")
    print(json.dumps(schema_response.json(), indent=2))
    
    # 3. Redis value
    redis_val = redis_manager.get_json(f"schema:{session_uuid}")
    print(f"\n--- REDIS schema:{session_uuid} VALUE ---")
    print(json.dumps(redis_val, indent=2))
    
if __name__ == "__main__":
    test_ingestion()
