import requests
import os
import time

BASE_URL = "https://graphrecall.onrender.com"
# BASE_URL = "http://localhost:8000" # Uncomment for local testing

def ingest_file(filename):
    filepath = os.path.join("sample_content", filename)
    with open(filepath, "r") as f:
        content = f.read()
    
    print(f"🚀 Ingesting {filename}...")
    
    payload = {
        "content": content,
        "source_url": f"file://{filename}",
        "user_id": "00000000-0000-0000-0000-000000000001"
    }
    
    try:
        response = requests.post(f"{BASE_URL}/api/ingest", json=payload, timeout=60)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Success! Created {data['concepts_created']} concepts, {data['relationships_created']} connections.")
            print(f"   Note ID: {data['note_id']}")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {str(e)}")

def main():
    print(f"Targeting Backend: {BASE_URL}")
    files = ["machine_learning.txt", "photosynthesis.txt"]
    
    for file in files:
        ingest_file(file)
        time.sleep(2) # Brief pause between requests

if __name__ == "__main__":
    main()
