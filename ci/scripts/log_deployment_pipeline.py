import requests
import os
import json
import time
import logging
import pandas as pd
# simplepbi for Power BI API REST
from simplepbi import pipelines

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
# 1. ENVIRONMENT SETUP & CONFIGURATION
# ==============================================================================
token = os.getenv("TOKEN")
targets = os.getenv("TARGETS", "").split()
remote_commit = os.getenv("GITHUB_SHA")
run_id = os.getenv("GITHUB_RUN_ID")
repo = os.getenv("GITHUB_REPOSITORY")
base = os.getenv("GITHUB_SERVER_URL")
branch = os.getenv("GITHUB_HEAD_REF")
github_run_url = f"{base}/{repo}/actions/runs/{run_id}"

# Load workspace targets mapping configuration
CONFIG_FILE_PATH = "ci/config/fabric_targets.json"
try:
    with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
        TARGETS_CONFIG = json.load(f)
except Exception as e:
    logging.error(f"❌ Error loading the config file {CONFIG_FILE_PATH}: {e}")
    exit(1)

logging.info(f"Target workspaces detected: {targets}")

# Install Pipelines client from SimplePBI library 
pl = pipelines.Pipelines(token)

# ==============================================================================
# 2. HELPER FUNCTIONS
# ==============================================================================
def wait_for_completion(pl, pipeline_id, operation_id, max_retries=15, wait_seconds=10):
    """Checks the pipeline operation status for the Dev to Test deploy."""
    last_data = None

    for i in range(max_retries):
        data = pl.get_pipeline_operation(pipeline_id, operation_id)
        last_data = data

        status = data.get("status")

        logging.info(f"Attempt {i+1}: {status}")

        if status not in ["NotStarted", "InProgress", "Executing"]:
            logging.info("✅ Deployment Completed")
            return data

        time.sleep(wait_seconds)

    logging.warning("⚠️ Timeout waiting for deployment")
    return last_data

def get_items(pipeline_id, token):
    """ Fetches all items existing in tne Test Fabric workspace.
        To be used when the deploy to Test creates new items (Add).
        To complete the log json file the IDs will be recovered from the 
        workspace content using this function.
        To do dat, we need to request the content using the Test Workspace ID.
        The Test Workspace ID will be recovered from the pipeline stages metadata
    """

    #--- 1. Get the Test Workspace ID from the pipeline stages
    # Endpoint from SimplePBI (Power BI API)
    pipeline_stages = pl.get_pipeline_stages(pipeline_id)
    
    workspace_id = None
    
    # Iterate over the list in the 'value'
    for stage in pipeline_stages.get('value', []):
        # Order: 0 = Dev, 1 = Test, 2 = Prod
        if stage.get('order') == 1:
            workspace_id = stage.get('workspaceId')
            break

    # If the Workspace ID is missing
    if not workspace_id:
        logging.error("❌ Error: not able to find the Test Workspace ID")
        return None

    #--- 2. Use the Test Workspace ID to get the content of the workspace
    # Endpoint from Fabric API
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # --- 3. Execute the HTTP request ---
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        logging.error(f"❌ Error fetching items: {response.status_code} - {response.text}")
        return []
        
    data = response.json()
    items = data.get("value", [])

    # Return the objects items and workspace_id to use later in the script
    return items, workspace_id

# ==============================================================================
# 3. MAIN EXECUTION LOOP (PER TARGET WORKSPACE)
# ==============================================================================
results = []

# --- 3.1 Load Item Type name Mapping ---
# Load the item type mapping from file (it will be used by the log json file)
with open("ci/config/item_type_mapping.json") as f:
    ITEM_TYPE_MAP = json.load(f)

# --- 3.2 Starts the iterarion per Target ---
for target in targets:
    logging.info(f"=== Processing target: {target} ===")

    try:
        # --- 3.2 Get dynamic operation ID ---
        env_var = f"OPERATION_ID_{target.upper()}"
        operation_id = os.getenv(env_var)

        # --- 3.3 Load Target Configuration ---
        target_info = TARGETS_CONFIG.get(target.lower())
        if not target_info:
            raise ValueError(f"Target '{target}' missing in configuration file {CONFIG_FILE_PATH}")

        pipeline_id = target_info.get("pipeline_id")

        # --- 3.4 Log Level 1 - Get the Pipeline Operations metadata ---
        # The object "items" will be filled in later depending on the scenario 
        result = {
            "branch": branch,
            "operationId": operation_id,
            "target": target,
            "commit": remote_commit,
            "github_url": github_run_url,
            "test_workspace_id": None,
            "items": []
        }

        # ==================================================
        # Scenario A: Items deleted - No deploy available
        # ==================================================
        # --- 3.4 Check if the deletion file exists in the VM ---
        # If the deleted_items file exists → Items Deletion Scenario
        deleted_file_name = f"deletion_log_{target}.json"
        if os.path.exists(deleted_file_name):
            logging.warning(f"Deletion log found for {target} → Processing deleted items scenario")

            # Use the custom function to fetch the workspace items to build the Log json file
            # When the item is deleted, no pipeline operations are related to it
            # The log file records the ID and name of the item deleted in Dev (it has to be deleted manually in Test)
            workspace_items, workspace_id = get_items(pipeline_id, token)

            # Store the workspace_id once the custom function has been invoked
            result["test_workspace_id"] = workspace_id

            with open(deleted_file_name, "r") as f:
                result_file = json.load(f)

            # Log Level 2
            # Build the json for the delete scenario
            for deleted in result_file:
                source_name = deleted["displayName"]
                item_id = deleted["sourceItemId"]
                change_type = deleted["changeType"]
                raw_type = deleted["itemType"]
                mapped_type = ITEM_TYPE_MAP.get((raw_type or "").lower(), raw_type)

                found = False
                for ws_item in workspace_items:
                    if (
                        ws_item.get("displayName") == source_name
                        and ws_item.get("type") == mapped_type
                    ):
                        item = {
                            "itemType": mapped_type,
                            "targetItemId": ws_item["id"],
                            "targetItemName": ws_item["displayName"],
                            "changeType": change_type
                        }
                        result["items"].append(item)
                        found = True
                        break

        # ==================================================
        # Scenario B: Normal deploy
        # ==================================================
        # --- 3.5 Build the log by using the deploy operation metadata ---
        # Applicable to no deletion scenarios
        else:
            if not operation_id:
                logging.warning(f"⚠️ No operation ID found for {target}")
                results.append((target, "NO_DEPLOY"))
                continue

            logging.info(f"Operation ID: {operation_id}")

            # --- 3.5.1 WAIT the end of the Fabric BI pipeline ---
            # Invoke the custom function to perform the wait operation
            pipelineOperationRaw = wait_for_completion(pl, pipeline_id, operation_id)

            pipelineOperationData = []

            # --- 3.5.2 Deployment completed → All the deployed items should be ready in Test ---
            # Small pause to wait the Fabric API for index
            # Then, list the Test Workspace Items using the custom function
            time.sleep(2) 
            workspace_items, workspace_id = get_items(pipeline_id, token)

            # Store the workspace_id once the function has been invoked
            result["test_workspace_id"] = workspace_id

            # --- 3.5.3 Log Level 2 - Operations details for normal deploy ---
            for step in pipelineOperationRaw.get("executionPlan", {}).get("steps", []):
                source_target = step.get("sourceAndTarget", {})
                diff_state = step.get("preDeploymentDiffState") # Get state to check if the artifact deployed is new

                # --- 3.5.4 Filter the Test Workspace by Item Name AND Type ---
                # Recover the item name from the objects deployed from Dev 
                source_name = source_target.get("sourceDisplayName")

                # Recover the item type from the objects deployed from Dev 
                # Update the name in the object "itemType" to use the one required in the deployment operation
                raw_type = source_target.get("type")
                mapped_type = ITEM_TYPE_MAP.get((raw_type or "").lower(), raw_type)

                found = False
                for ws_item in workspace_items:
                    if (
                        ws_item.get("displayName") == source_name
                        and ws_item.get("type") == mapped_type
                    ):
                        item = {
                            "itemType": mapped_type,
                            "targetItemId": ws_item["id"],
                            "targetItemName": ws_item["displayName"],
                            "changeType": diff_state
                        }
                        result["items"].append(item)
                        found = True
                        break

                if not found:
                    logging.warning(
                        f"⚠️ No match found in TEST workspace "
                        f"for '{source_name}' ({mapped_type})"
                    )

            # Debug #1 for Re-run in Git Actions
            for step in pipelineOperationRaw.get("executionPlan", {}).get("steps", []):
                source_target = step.get("sourceAndTarget", {})

                details = {
                    "github_url": github_run_url,
                    "branch": branch,
                    "commit": remote_commit,

                    "operationId": operation_id,
                    "operationStatus": pipelineOperationRaw.get("status"),
                    "executionStatus": step.get("status"),

                    "itemType": source_target.get("type"),
                    "sourceItemId": source_target.get("source"),
                    "sourceItemName": source_target.get("sourceDisplayName"),

                    "targetItemId": source_target.get("target"),
                    "targetItemName": source_target.get("targetDisplayName"),
                }

                pipelineOperationData.append(details)

            df = pd.DataFrame(pipelineOperationData)
            logging.debug(df.to_string())

        # ==============================================================================
        # 4. SAVE RESULTS - EXECUTION SUMMARY
        # ============================================================================== 

        logging.info(f"Final Log Output for target: {target}")
        
        # Debug #2 for Re-run in Git Actions
        logging.debug(result)

        # Save the JSON output
        file_name = f"deployment_log_{target}.json"
        with open(file_name, "w") as f:
            json.dump(result, f)

        logging.info(f"✅ JSON stored successfully in GitHub VM as {file_name}")

    except Exception as e:
        logging.error(f"❌ Error saving results for target '{target}': {str(e)}", exc_info=True)