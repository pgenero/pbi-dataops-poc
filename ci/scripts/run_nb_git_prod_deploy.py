import json
import logging
import os
import sys
import time
import requests

# ==============================================================================
# 0. LOGGING CONFIGURATION
# ==============================================================================
# GitHub Actions automatically sets ACTIONS_STEP_DEBUG to 'true' if "Enable debug logging" is checked
if os.getenv("ACTIONS_STEP_DEBUG") == "true":
    log_level = logging.DEBUG
else:
    log_level = logging.INFO

logging.basicConfig(level=log_level, format="%(asctime)s - %(levelname)s - %(message)s")

# ==============================================================================
# 1. SETUP & VARIABLES
# ==============================================================================
tenant_id = os.getenv("TENANT_ID")
client_id = os.getenv("APP_CLIENT_ID")
client_secret = os.getenv("APP_SECRET_KEY")
branch = os.getenv("BRANCH_NAME")
gh_token = os.getenv("GITHUB_TOKEN")

# Fixed Fabric Infrastructure Identifiers for Production Deployment
WORKSPACE_ID = "4a71978c-aecb-4b5d-a028-5433c07a99c9"
NOTEBOOK_ID = "11035ea6-bfbb-4223-ac4d-65045a0aeb18"
LAKEHOUSE_ID = "85602e65-4d1f-47a3-9bf8-20a0f229eb55"
REPO = "pgenero/pbi-dataops-poc"

logging.info("==================================================")
logging.info(f"🚀 STARTING PROD DEPLOYMENT PROCESS FOR BRANCH: [{branch}]")
logging.info("==================================================")

# --- 1.1 Branch Name Validation in GitHub ---
git_url = f"https://api.github.com/repos/{REPO}/branches/{branch}"
headers_gh = {
    "Authorization": f"Bearer {gh_token}"
}

res = requests.get(git_url, headers=headers_gh)
if res.status_code != 200:
    logging.error(f"❌ Branch '{branch}' does not exist in repository '{REPO}' (HTTP {res.status_code}). Aborting.")
    sys.exit(1)

logging.info(f"✅ Branch '{branch}' validated successfully in GitHub.")

# --- 1.2 Get Fabric API OAuth2 Token ---
token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
payload = {
    "client_id": client_id,
    "client_secret": client_secret,
    "grant_type": "client_credentials",
    "scope": "https://api.fabric.microsoft.com/.default"
}

response = requests.post(token_url, data=payload)
if response.status_code != 200:
    logging.error(f"❌ Failed to obtain Fabric API bearer token: {response.text}")
    sys.exit(1)

token = response.json().get("access_token")
headers = {
    "Authorization": f"Bearer {token}", 
    "Content-Type": "application/json"
}

# ==============================================================================
# 2. RUN FABRIC NOTEBOOK (PROD DEPLOY)
# ==============================================================================
fabric_url = f"https://api.fabric.microsoft.com/v1/workspaces/{WORKSPACE_ID}/notebooks/{NOTEBOOK_ID}/jobs/execute/instances?jobType=RunNotebook"
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

logging.info(f"🚀 Triggering Fabric Production Deployment Notebook...")
response = requests.post(fabric_url, headers=headers, json=payload)

if response.status_code not in [200, 201, 202]:
    logging.error(f"❌ Failed to trigger Fabric Notebook (HTTP {response.status_code}): {response.text}")
    sys.exit(1)

job_location_url = response.headers.get("Location")

if not job_location_url:
    logging.error("❌ Fabric API response missing mandatory 'Location' header.")
    sys.exit(1)

try:
    retry_after = int(response.headers.get("Retry-After", 15))
except (ValueError, TypeError):
    retry_after = 15

logging.info(f"📍 Job accepted by Fabric API. Status URL: {job_location_url}")

# ==============================================================================
# 3. MONITORING LOOP & SUMMARY CHECK
# ==============================================================================
logging.info(f"⏳ Monitoring Notebook execution status for branch [{branch}]...")

while True:
    time.sleep(retry_after)
    
    # Check Job Instance status
    status_response = requests.get(job_location_url, headers=headers)
    
    if status_response.status_code != 200:
        logging.error(f"❌ Status check failed (HTTP {status_response.status_code}): {status_response.text}")
        sys.exit(1)
        
    job_status_data = status_response.json()
    current_status = job_status_data.get("status")
    
    logging.info(f"📊 Fabric Notebook Status: [{current_status}]")
    
    # --- NOTEBOOK SUCCEEDED ---
    if current_status in ["Completed", "Succeeded"]:
        logging.info("=======================================================")
        logging.info("         FABRIC EXECUTION SUMMARY RESULTS              ")
        logging.info("=======================================================")

        # 3.1 Build the execution log filename
        file_name = f"execution_log_{branch}.json"

        # 3.2 Request Token for OneLake Access Scope
        onelake_token_payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "https://storage.azure.com/.default"
        }

        token_res = requests.post(token_url, data=onelake_token_payload)
        if token_res.status_code != 200:
            logging.error(f"❌ Failed to obtain OneLake API bearer token: {token_res.text}")
            sys.exit(1)

        onelake_token = token_res.json().get("access_token")

        # 3.3 Read Summary File directly from OneLake DFS API
        onelake_url = f"https://onelake.dfs.fabric.microsoft.com/{WORKSPACE_ID}/{LAKEHOUSE_ID}/Files/ci_cd_results/{file_name}"
        headers_onelake = {
            "Authorization": f"Bearer {onelake_token}"
        }

        logging.info(f"📥 Fetching execution summary log from OneLake: '{file_name}'...")
        onelake_res = requests.get(onelake_url, headers=headers_onelake)

        has_internal_errors = False

        if onelake_res.status_code == 200:
            try:
                execution_summary = onelake_res.json()
                
                # Format and print execution summary in GitHub Actions logs
                for item in execution_summary:
                    target = item.get("target", "Unknown")
                    deploy_st = item.get("deploy_status", "N/A")
                    git_st = item.get("git_commit_status", "N/A")
                    refresh_st = item.get("refresh_status", "Not Triggered")
                    err_msg = item.get("error_message")

                    logging.info(f"📌 Target Workspace: [{target}]")
                    logging.info(f"   ├─ Deploy Status:     {deploy_st}")
                    logging.info(f"   ├─ Git Push Status:   {git_st}")
                    
                    if refresh_st not in ["No Models Deployed", "Not Triggered"]:
                        logging.info(f"   ├─ Model Refresh:     {refresh_st}")

                    if err_msg:
                        logging.warning(f"   └─ ⚠️ Error Detail:    {err_msg}")
                        has_internal_errors = True
                    else:
                        logging.info(f"   └─ Status:            ✅ All OK")

            except json.JSONDecodeError:
                logging.warning(f"⚠️ Failed to parse JSON summary from OneLake. Raw content: {onelake_res.text}")
                has_internal_errors = True
        else:
            logging.error(f"❌ Error fetching summary file from OneLake (HTTP {onelake_res.status_code}): {onelake_res.text}")
            has_internal_errors = True

        logging.info("=======================================================")

        # --- Delete Git Branch upon success ---
        if not has_internal_errors:
            logging.info(f"🗑️ Deleting feature branch '{branch}' from GitHub...")
            git_delete_url = f"https://api.github.com/repos/{REPO}/git/refs/heads/{branch}"
            git_delete_response = requests.delete(git_delete_url, headers=headers_gh)
      
            if git_delete_response.status_code == 204:
                logging.info(f"✅ Git branch '{branch}' deleted successfully. Pipeline finished!")
            else:
                logging.error(f"❌ Failed to delete Git branch '{branch}' (HTTP {git_delete_response.status_code}): {git_delete_response.text}")
                sys.exit(1)
        else:
            logging.error(f"❌ Pipeline failed: Feature branch '{branch}' was NOT deleted due to internal errors reported in OneLake log.")
            sys.exit(1)

        break

    # --- Fabric Notebook Fail → Keep Git Feature Branch ---
    elif current_status in ["Failed", "Canceled"]:
        failure_reason = job_status_data.get('failureReason', 'No failure details provided')
        logging.error("❌ Fabric Notebook execution failed at infrastructure level.")
        logging.error(f"Failure Reason: {failure_reason}")
        sys.exit(1)