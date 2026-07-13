import json
import time
import requests
import os

# --- Variables ---
tenant_id = os.getenv("TENANT_ID")
client_id = os.getenv("APP_CLIENT_ID")
client_secret = os.getenv("APP_SECRET_KEY")
branch = os.getenv("BRANCH_NAME")
workspace_id = "4a71978c-aecb-4b5d-a028-5433c07a99c9"
notebook_id = "11035ea6-bfbb-4223-ac4d-65045a0aeb18"

# --- Branch Name Validation ---
repo = "pgenero/pbi-dataops-poc"
git_url = f"https://api.github.com/repos/{repo}/branches/{branch}"

gh_token = os.getenv("GITHUB_TOKEN")

headers_gh = {
    "Authorization": f"Bearer {gh_token}"
}

res = requests.get(git_url, headers=headers_gh)

if res.status_code != 200:
    raise Exception(f"Branch does not exist: {branch}")


# --- Get token ---
token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

payload = {
    "client_id": client_id,
    "client_secret": client_secret,
    "grant_type": "client_credentials",
    "scope": "https://api.fabric.microsoft.com/.default"
}

response = requests.post(token_url, data=payload)

if response.status_code != 200:
    raise Exception(f"Error getting token: {response.text}")

token = response.json()["access_token"]

# 2. Build headers
headers = {
    "Authorization": f"Bearer {token}", 
    "Content-Type": "application/json"
    }

# 3. Run Fabric Notebook
fabric_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/notebooks/{notebook_id}/jobs/execute/instances?jobType=RunNotebook"
payload = {
    "executionData": {
        "parameters": {
            "branch": {
                "value": branch,
                "type": "string"
            }
        }
    }
}

print("Running Notebook in Fabric...")
response = requests.post(fabric_url, headers=headers, json=payload)

if response.status_code not in [200, 201, 202]:
    print(f"Error starting: {response.text}")
    exit(1)

# Extract the URL for monitoring over headers (Location)
job_location_url = response.headers.get("Location")
retry_after = int(response.headers.get("Retry-After", 15)) # Fallback to 15

if not job_location_url:
    raise Exception("No Location header returned from Fabric API")

print(f"¡Job Accepted! Monitoring: {job_location_url}")

# ==========================================
# 4. BUCLE MONITORING
# ==========================================
while True:
    print(f"=== WAITING FOR NOTEBOOK EXECUTION ===")
    print(f"Waiting {retry_after} seconds before status check...")
    time.sleep(retry_after)
    
    # Check Job Instance status
    status_response = requests.get(job_location_url, headers=headers)
    
    if status_response.status_code != 200:
        print(f"Error checking status of: {status_response.text}")
        exit(1)
        
    job_status_data = status_response.json()
    current_status = job_status_data.get("status")
    
    print(f"Fabric Notebook current state: [{current_status}]")
    
    # --- Fabric Notebook Success → Delete Git Feature Branch ---
    if current_status in ["Completed", "Succeeded"]:
        print(f"Fabric Notebook completed. State: [{current_status}]")

        # --- Delete the Feature Branch ---
        git_delete_url = f"https://api.github.com/repos/{repo}/git/refs/heads/{branch}"
        git_delete_response = requests.delete(git_delete_url, headers=headers_gh)
  
        if git_delete_response.status_code == 204:
            print(f"✅ Git Branch {branch} deleted")
        else:
            print(f"❌ Failed to delete Git branch: {git_delete_response.text}")

        break

    # --- Fabric Notebook Fail → Keep Git Feature Branch ---
    elif current_status in ["Failed", "Canceled"]:
        print("❌ Fabric Notebook execution failed.")
        print(f"Failure reason: {job_status_data.get('failureReason', 'No specified')}")
        exit(1)
