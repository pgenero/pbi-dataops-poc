import json
import time
import requests
import os

# Variables
token = os.getenv("TOKEN")
workspace_id = "4a71978c-aecb-4b5d-a028-5433c07a99c9"
notebook_id = "13581d5f-41d4-4f09-8d3a-38d9a895837d"

# Read json saved by log_deployment_pipeline.py
with open("deployment_log.json", "r") as f:
    result = json.load(f)

# opcional: convertir a string para enviarlo luego
# log_data = json.dumps(result)

print("JSON readed Ok")

log_string_parameter = json.dumps(result, separators=(',', ':'))

# 2. Build headers
headers = {
    "Authorization": f"Bearer {token}", 
    "Content-Type": "application/json"
    }

# 3. Run Fabric Notebook
fabric_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/notebooks/{notebook_id}/jobs/execute/instances?jobType=RunNotebook"
payload = {"executionData": {"parameters": {"log_payload": {"value": log_string_parameter, "type": "string"}}}}

print("Running Notebook in Fabric...")
response = requests.post(fabric_url, headers=headers, json=payload)

if response.status_code not in [200, 201, 202]:
    print(f"Error starting: {response.text}")
    exit(1)

# Extract the URL for monitoring over headers (Location)
job_location_url = response.headers.get("Location")
retry_after = int(response.headers.get("Retry-After", 15)) # Fallback to 15

print(f"¡Job Accepted! Monitoring: {job_location_url}")

# ==========================================
# 4. BUCLE MONITORING
# ==========================================
while True:
    print(f"Waiting {retry_after} seconds before status check...")
    time.sleep(retry_after)
    
    # Check Job Instance status
    status_response = requests.get(job_location_url, headers=headers)
    
    if status_response.status_code != 200:
        print(f"Error checking status of: {status_response.text}")
        exit(1)
        
    job_status_data = status_response.json()
    current_status = job_status_data.get("status")
    
    print(f"Notebook current state: [{current_status}]")
    
    if current_status in ["Completed", "Succeeded"]:
        print("Succeded! The Notebook completed the execution and the log was saved in the Lakehouse.")
        break
    elif current_status in ["Failed", "Canceled"]:
        print("Error: The execution of the Notebook failed in Fabric.")
        print(f"Failure reason: {job_status_data.get('failureReason', 'No specifieda')}")
        exit(1)