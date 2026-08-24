import json
import logging
import os
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
# 1. SETUP - ENV & CONSTANTS
# ==============================================================================
token = os.getenv("TOKEN")
targets = os.getenv("TARGETS", "").split()
# Workspace ID where the notebook is located in Fabric
workspace_id = "4a71978c-aecb-4b5d-a028-5433c07a99c9"
notebook_id = "13581d5f-41d4-4f09-8d3a-38d9a895837d"

# ==============================================================================
# 2. MAIN EXECUTION LOOP PER TARGET
# ==============================================================================
for target in targets:
    logging.info(f"========== PROCESSING TARGET: {target} ==========")
    file_name = f"deployment_log_{target}.json"

    # --- 2.1 Load Deployment Log JSON ---
    if not os.path.exists(file_name):
        logging.warning(f"⚠️ Log file not found in VM workspace: '{file_name}'. Skipping target [{target}].")
        continue

    try:
        with open(file_name, "r", encoding="utf-8") as f:
            result = json.load(f)
        logging.info(f"✅ Deployment log loaded successfully from '{file_name}'.")
    except Exception as e:
        logging.error(f"❌ Failed to parse JSON file '{file_name}': {e}")
        exit(1)

    # Compact JSON serialization for parameter passing
    log_string_parameter = json.dumps(result, separators=(',', ':'))

    # --- 2.2 Build API Request Headers & Payload ---
    headers = {
        "Authorization": f"Bearer {token}", 
        "Content-Type": "application/json"
    }

    # --- 2.3. Run Fabric Notebook to save the logs in the Fabric Lakehouse ---
    fabric_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/notebooks/{notebook_id}/jobs/execute/instances?jobType=RunNotebook"
    payload = {
        "executionData": {
            "parameters": {
                "log_payload": {
                    "value": log_string_parameter, 
                    "type": "string"
                }
            }
        }
    }

    logging.info(f"🚀 Triggering Fabric Notebook execution for target [{target}]...")
    response = requests.post(fabric_url, headers=headers, json=payload)

    if response.status_code not in [200, 201, 202]:
        logging.error(f"❌ HTTP {response.status_code} - Failed to trigger Notebook job for [{target}]: {response.text}")
        exit(1)

    # --- 2.4 Extract Async Job Metadata ---
    job_location_url = response.headers.get("Location")
    
    try:
        retry_after = int(response.headers.get("Retry-After", 15))
    except (ValueError, TypeError):
        retry_after = 15

    logging.info(f"📍 Job accepted by Fabric API. Monitoring URL: {job_location_url}")

    # ==============================================================================
    # 3. MONITORING LOOP (POLLING)
    # ==============================================================================
    logging.info(f"⏳ Monitoring Notebook execution status for [{target}]...")
    
    while True:
        time.sleep(retry_after)
        
        status_response = requests.get(job_location_url, headers=headers)
        
        if status_response.status_code != 200:
            logging.error(f"❌ Status check failed (HTTP {status_response.status_code}): {status_response.text}")
            exit(1)
            
        job_status_data = status_response.json()
        current_status = job_status_data.get("status")
        
        logging.info(f"📊 Notebook Status [{target}]: '{current_status}'")
        
        if current_status in ["Completed", "Succeeded"]:
            logging.info(f"✅ Success! Fabric Notebook finished execution for target [{target}]. Logs stored in Lakehouse.")
            break
        elif current_status in ["Failed", "Canceled"]:
            failure_reason = job_status_data.get('failureReason', 'No specified reason')
            logging.error(f"❌ Fabric Notebook execution failed for target [{target}].")
            logging.error(f"Reason: {failure_reason}")
            exit(1)