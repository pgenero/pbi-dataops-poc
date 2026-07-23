import requests
import os
import json
import time
import pandas as pd
# simplepbi for Power BI API REST
from simplepbi import pipelines

# Variables
token = os.getenv("TOKEN")
targets = os.getenv("TARGETS", "").split()
remote_commit = os.getenv("GITHUB_SHA")
run_id = os.getenv("GITHUB_RUN_ID")
repo = os.getenv("GITHUB_REPOSITORY")
base = os.getenv("GITHUB_SERVER_URL")
branch = os.getenv("GITHUB_HEAD_REF")
github_run_url = f"{base}/{repo}/actions/runs/{run_id}"


# Debug delete ❌
print("Targets for logging:", targets)

# Install Pipelines client 
pl = pipelines.Pipelines(token)

# Function to check the pipeline operation status
def wait_for_completion(pl, pipeline_id, operation_id, max_retries=15, wait_seconds=10):
    last_data = None

    for i in range(max_retries):
        data = pl.get_pipeline_operation(pipeline_id, operation_id)
        last_data = data

        status = data.get("status")

        print(f"Attempt {i+1}: {status}")

        if status not in ["NotStarted", "InProgress", "Executing"]:
            print("✅ Deployment finished")
            return data

        time.sleep(wait_seconds)

    print("⚠️ Timeout waiting for deployment")
    return last_data

# Function to recover the Test Workspace Content
# To be used when the deploy to test creates new items
# To complete the log json file the IDs will be recovered from the workspace content
# To do dat, we need to request the content using the WorkspaceID.
# Workspace ID will be recovered from the pipeline stages metadata
def get_items(pipeline_id, token):
    #--- 1. Get the Test Workspace ID from the pipeline stages
    # Endpoint from SimplePBI (Power BI API)
    pipeline_stages = pl.get_pipeline_stages(pipeline_id)
    
    workspace_id = None
    
    # Iterate over the list in the 'value'
    for stage in pipeline_stages.get('value', []):
        # Order: 0 = Dev, 1 = Test, 2 = Prod
        if stage.get('order') == 1:
            workspace_id = stage.get('workspaceId')
            break # Encontrado, salimos del bucle

    # If ID is missing
    if not workspace_id:
        print("❌ Not able to find Test Workspace ID")
        return None

    #--- 2. Use the Test Workspace ID to get the content of the workspace
    # Endpoint from Fabric API
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # --- Execute the HTTP request ---
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        print(f"❌ Error fetching items: {response.status_code} - {response.text}")
        return []
        
    data = response.json()
    items = data.get("value", [])
    
    ### FOR DEBUG - DELETE
    print(f"✅ Items retrieved: {len(items)}")
    return items

# ========================
# 2. Loop per target
# ========================
results = []

# Load the item type name mapping to use in the json file
with open("ci/config/item_type_mapping.json") as f:
    ITEM_TYPE_MAP = json.load(f)

for target in targets:
    print(f"\n=== Logging target: {target} ===")

    try:
        # 2.1 Get dynamic operation ID
        env_var = f"OPERATION_ID_{target.upper()}"
        operation_id = os.getenv(env_var)

        if not operation_id:
            print(f"⚠️ No operation ID found for {target}")
            results.append((target, "NO_DEPLOY"))
            continue

        print(f"Operation ID: {operation_id}")

        # 2.2 Map pipeline from target
        if target == "sales":
            pipeline_id = os.getenv("SALES_PIPELINE_ID")
        elif target == "finance":
            pipeline_id = os.getenv("FINANCE_PIPELINE_ID")
        elif target == "operations":
            pipeline_id = os.getenv("OPERATIONS_PIPELINE_ID")

        # 2.3 WAIT the end of the Power BI pipeline
        pipelineOperationRaw = wait_for_completion(pl, pipeline_id, operation_id)

        pipelineOperationData = []

        # 2.4 Log Level 1 - Operations metadata
        result = {
            "branch": branch,
            "operationId": operation_id,
            "target": target,
            "commit": remote_commit,
            "github_url": github_run_url,
            "items": []
        }

        # 2.XXXXX Request the workspace existing items to use in case of Added objects from the Git repo
        workspace_items = get_items(pipeline_id, token)

        # 2.5 Log Level 2 - Oerations details
        for step in pipelineOperationRaw.get("executionPlan", {}).get("steps", []):
            source_target = step.get("sourceAndTarget", {})
            diff_state = step.get("preDeploymentDiffState") # Get state to check if the artifact deployes is new

            # Update the name in the object "itemType" to use the one required in the deployment operation
            raw_type = source_target.get("type")
            mapped_type = ITEM_TYPE_MAP.get((raw_type or "").lower(), raw_type)

            # --- Scenario 1: The deployed item exists in Test and is visible in the Pipeline Operation request
            if diff_state != "New":

                item = {
                    "itemType": mapped_type,
                    "targetItemId": source_target.get("target"),
                    "targetItemName": source_target.get("targetDisplayName"),
                }

                result["items"].append(item)

            # --- Scenario 2: The deployed doesn't exist Test (new), is not visible in the Pipeline Operations request
            # Recover the ID from the Workspace Item endpoint (Target Workspace is Test)
            else:
                source_name = source_target.get("sourceDisplayName")
                found = False
                for ws_item in workspace_items:
                    if (
                        ws_item.get("displayName") == source_name
                        and ws_item.get("type") == mapped_type
                    ):
                        item = {
                            "itemType": mapped_type,
                            "targetItemId": ws_item["id"],
                            "targetItemName": ws_item["displayName"]
                        }
                        result["items"].append(item)
                        found = True
                        break

                if not found:
                    print(
                        f"⚠️ No match found in TEST workspace "
                        f"for '{source_name}' ({mapped_type})"
                    )

        # 2.6 Final Log Output
        print(result)

        # 2.7 Save the json output
        file_name = f"deployment_log_{target}.json"

        with open(file_name, "w") as f:
            json.dump(result, f)

        print("JSON stored")

        # DELETE - Debug only ❌
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

        # DEBUG Remove ❌
        df = pd.DataFrame(pipelineOperationData)
        print(df.to_string())

    except Exception as e:
        print(f"❌ Error logging {target}: {str(e)}")