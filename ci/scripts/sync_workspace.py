import os
import requests
import time
import json
import logging

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
connection_id = os.getenv("GIT_CONNECTION_ID")
remote_commit = os.getenv("GITHUB_SHA")
branch = os.getenv("GITHUB_HEAD_REF")
approver = os.getenv("GITHUB_ACTOR")  # User approving the PR
author = os.getenv("GITHUB_AUTHOR")    # PR creator/contributor
message = os.getenv("PR_TITLE")
targets = os.getenv("TARGETS", "").split()

# Load workspace targets mapping configuration
CONFIG_FILE_PATH = "ci/config/fabric_targets.json"
try:
    with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
        TARGETS_CONFIG = json.load(f)
except Exception as e:
    logging.error(f"❌ Failed to load target configuration file ({CONFIG_FILE_PATH}): {e}")
    exit(1)

logging.info(f"Target workspaces detected: {targets}")

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

results = []


# ==============================================================================
# 2. HELPER FUNCTIONS
# ==============================================================================
def get_items(workspace_id, token):
    """Fetches all items existing within a specific Fabric workspace."""
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        logging.error(f"❌ Failed to fetch workspace items: {response.status_code} - {response.text}")
        return []

    data = response.json()
    items = data.get("value", [])

    return items

# ==============================================================================
# 3. MAIN EXECUTION LOOP (PER TARGET WORKSPACE)
# ==============================================================================
for target in targets:
    logging.info(f"=== Processing target: {target} ===")

    try:
        # --- 3.1 Load Target Configuration ---
        target_info = TARGETS_CONFIG.get(target.lower())

        if not target_info:
            raise ValueError(f"Target '{target}' missing in configuration file ({CONFIG_FILE_PATH})")

        pipeline_id = target_info.get("pipeline_id")
        workspace_id = target_info.get("workspace_id")
        dev_stage_id = target_info.get("dev_stage_id")
        test_stage_id = target_info.get("test_stage_id")

        # Debug #1 for Re-run in Git Actions
        logging.debug(
            f"""[ DEBUG #1 - INITIAL CONFIGURATION ]
        TARGET: {target}
        PIPELINE: {pipeline_id}
        WORKSPACE: {workspace_id}
        DEV_STAGE: {dev_stage_id}
        TEST_STAGE: {test_stage_id}"""
        )

        # --- 3.2 Configure Git Credentials ---
        cred_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/myGitCredentials"
        cred_payload = {
            "source": "ConfiguredConnection",
            "connectionId": connection_id
        }

        cred_response = requests.patch(cred_url, headers=headers, json=cred_payload)
        logging.info(f"Git credentials configured for workspace {workspace_id}: {cred_response.text}")

        # --- 3.3 Get Workspace Git Status Before Sync ---
        status_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/status"
        status_response = requests.get(status_url, headers=headers)
        status_data = status_response.json()

        # Debug #2 for Re-run in Git Actions
        logging.debug(
            f"""[ DEBUG #2 - PRE-SYNC STATUS ]
        Workspace status BEFORE sync: {status_data}"""
        )

        workspace_head = status_data.get("workspaceHead") or ""

        # --- Capture the status changes for potential deploy operation later ---
        changes = status_data.get("changes", [])

        # --- 3.4 Trigger Sync (Workspace <-> Git Repository) ---
        logging.info(f"Starting workspace sync with GitHub for target: {target}")
        
        sync_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/updateFromGit"
        sync_payload = {
            "remoteCommitHash": remote_commit,
            "workspaceHead": workspace_head,
            "options": {
                "allowOverrideItems": True
            }
        }

        sync_response = requests.post(sync_url, headers=headers, json=sync_payload)

        # --- 3.5 Wait for Sync Completion ---
        for i in range(10):
            status_check = requests.get(status_url, headers=headers).json()

            workspace_head = status_check.get("workspaceHead")
            remote_head = status_check.get("remoteCommitHash")

            if workspace_head == remote_head:
                logging.info(f"✅ Sync completed -> Commit: {workspace_head}")
                break

            if i == 0:
                logging.info(f"🔄 Syncing in progress -> Current: {workspace_head} | Target: {remote_head}")

            time.sleep(5)

        # --- 3.6 Save Pre-Sync Workspace Commit Head ---
        with open(os.environ['GITHUB_ENV'], 'a') as f:
            f.write(f"WORKSPACE_HEAD_BEFORE={workspace_head}\n")

        if not workspace_head:
            raise Exception("WORKSPACE_HEAD_BEFORE identifier was not retrieved.")

        # Debug #3 for Re-run in Git Actions
        logging.debug(f"[ DEBUG #3 ] WORKSPACE_HEAD_BEFORE={workspace_head}")

        # --- 3.7. Build the list of Items for Deployment ---
        # Load the item type mapping from file
        with open("ci/config/item_type_mapping.json") as f:
            ITEM_TYPE_MAP = json.load(f)

        # Prepare items list for deploy
        items_to_deploy = []

        # Item list to use when the items are deleted through the Pull Request
        deleted_items = []

        # Request the workspace existing items to use in case of Added objects from the Git repo
        workspace_items = get_items(workspace_id, token)

        # Process Git changes
        # Get the items from the sync git output or for the get_items function
        for change in changes:
            metadata = change.get("itemMetadata", {})
            identifier = metadata.get("itemIdentifier", {})

            raw_type = metadata.get("itemType")
            mapped_type = ITEM_TYPE_MAP.get((raw_type or "").lower(), raw_type)

            remote_change = change.get("remoteChange")
            display_name = metadata.get("displayName")

            # Scenario 1 → Workspace existing items Modified in Git repo 
            # Items source → git output ("changes" object)
            if remote_change == "Modified" and "objectId" in identifier:
                item = {
                    "sourceItemId": identifier["objectId"],
                    "itemType": mapped_type
                }
                items_to_deploy.append(item)

            # Scenario 2 → Workspace new items Added from Git repo 
            # Items source → get_items function
            elif remote_change == "Added":
                found = False
                for ws_item in workspace_items:
                    if (
                        ws_item.get("displayName") == display_name
                        and ws_item.get("type") == mapped_type
                    ):
                        item = {
                            "sourceItemId": ws_item["id"],
                            "itemType": ws_item["type"]
                        }
                        items_to_deploy.append(item)
                        found = True
                        break
                
                if not found:
                    logging.warning(f"⚠️ No matching workspace item found for: {display_name} ({mapped_type})")

            # Scenario 3 → Workspace items Deleted from Git repo 
            # Store the items removed in the Dev to create a log json file
            elif remote_change == "Deleted" and "objectId" in identifier:
                item = {
                    "sourceItemId": identifier["objectId"],
                    "itemType": mapped_type,
                    "displayName": display_name,
                    "changeType": remote_change
                }
                deleted_items.append(item)

        logging.debug(f"Items prepared for deployment: {items_to_deploy}")

        # Debug #4 for Re-run in Git Actions
        for change in changes:
            logging.debug(
                f"""[ DEBUG #4 - DETECTED CHANGES ]
            RAW CHANGE: {change}"""
            )

        # Debug #5 for Re-run in Git Actions
        if changes:
            logging.debug(
                f"""[ DEBUG #5 - TYPE MAPPING ]
            RAW TYPE: {raw_type}
            MAPPED TYPE: {mapped_type}"""
            )

        # --- 3.8 Execute Deployment (Dev -> Test) ---
        # Create the deployment note from the commit message
        note = f"commit={remote_commit[:7]} | branch={branch} | approver={approver} | author={author} | msg={message}"
        logging.info(f"Deployment note: {note}")

        has_items = len(items_to_deploy) > 0
        has_deleted = len(deleted_items) > 0

        # Save the list of deleted items if exist
        if has_deleted:
            logging.warning("⚠️ Deleted items detected -> Skipping deployment step")
            file_name = f"deletion_log_{target}.json"
            with open(file_name, "w") as f:
                json.dump(deleted_items, f)
            logging.info("Deletion JSON stored")

        elif not has_items:
            logging.warning("⚠️ No items to deploy -> Skipping deployment step")

        else:
            deploy_url = f"https://api.fabric.microsoft.com/v1/deploymentPipelines/{pipeline_id}/deploy"
            deploy_payload = {
                "sourceStageId": dev_stage_id,
                "targetStageId": test_stage_id,
                "items": items_to_deploy,
                "note": note
            }

            response = requests.post(deploy_url, headers=headers, json=deploy_payload)

            deployment_id = None
            for key, value in response.headers.items():
                if key.lower() == "deployment-id":
                    deployment_id = value.strip()
                    break
            
            # Debug #6 for Re-run in Git Actions
            logging.debug(
                f"""[ DEBUG #6 - RESPONSE HEADERS ]
            All headers: {dict(response.headers)}"""
            )
            
            if deployment_id:
                logging.info(f"Deployment ID for {target}: {deployment_id}")
                with open(os.environ["GITHUB_ENV"], "a") as f:
                    f.write(f"OPERATION_ID_{target.upper()}={deployment_id}\n")

            # # Debug #7 for Re-run in Git Actions
            logging.debug(
                f"""[ DEBUG #7 - DEPLOYMENT OPERATION DETAILS ]
            STATUS CODE: {response.status_code}
            HEADERS: {response.headers}
            FINAL PAYLOAD: {deploy_payload}"""
            )

            results.append((target, "SUCCESS"))

    except Exception as e:
        logging.error(f"❌ Error processing target '{target}': {str(e)}")
        results.append((target, "FAILED"))


# ==============================================================================
# 4. EXECUTION SUMMARY
# ==============================================================================
logging.info("==================================================")
logging.info("               EXECUTION SUMMARY                  ")
logging.info("==================================================")

failures = [r for r in results if r[1] == "FAILED"]

for target, status in results:
    logging.info(f"Target '{target}': {status}")

if failures:
    logging.error("❌ Execution completed with failures:")
    for target, _ in failures:
        logging.error(f"  - {target}")
    exit(1)
else:
    logging.info("✅ All target operations completed successfully.")
    exit(0)