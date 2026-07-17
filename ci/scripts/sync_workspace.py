import os
import requests
import time
import json

# ========================
# 1. SETUP - ENV VARIABLES
# ========================
token = os.getenv("TOKEN")
connection_id = os.getenv("GIT_CONNECTION_ID")
remote_commit = os.getenv("GITHUB_SHA")
branch = os.getenv("GITHUB_HEAD_REF") # os.getenv("GITHUB_REF_NAME")
approver = os.getenv("GITHUB_ACTOR") # no need to get it in the YML - Person that approves the PR
author = os.getenv("GITHUB_AUTHOR") # contributor that creates the PR
message = os.getenv("PR_TITLE")
targets = os.getenv("TARGETS", "").split()

# Debug Detele ❌
print("Targets detected:", targets)

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

results = []

# =========================
# 2. BUILD FUNCTION
# =========================
# --- 2.1 Get Items from a given Workspace ---
def get_items(workspace_id, token):
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

  print(f"✅ Items retrieved: {len(items)}")
  return items

# =========================
# 3. MAIN LOOP - PER TARGET
# =========================
for target in targets:
    print(f"\n=== Processing target: {target} ===\n")

    try:
        # --- 3.1 Target-Specific Configuration Mapping ---
        if target == "sales":
            pipeline_id = os.getenv("SALES_PIPELINE_ID")
            workspace_id = os.getenv("SALES_WORKSPACE_ID")
            dev_stage_id = os.getenv("SALES_DEV_STAGE_ID")
            test_stage_id = os.getenv("SALES_TEST_STAGE_ID")
        elif target == "finance":
            pipeline_id = os.getenv("FINANCE_PIPELINE_ID")
            workspace_id = os.getenv("FINANCE_WORKSPACE_ID")
            dev_stage_id = os.getenv("FINANCE_DEV_STAGE_ID")
            test_stage_id = os.getenv("FINANCE_TEST_STAGE_ID")
        elif target == "operations":
            pipeline_id = os.getenv("OPERATIONS_PIPELINE_ID")
            workspace_id = os.getenv("OPERATIONS_WORKSPACE_ID")
            dev_stage_id = os.getenv("OPERATIONS_DEV_STAGE_ID")
            test_stage_id = os.getenv("OPERATIONS_TEST_STAGE_ID")

        # Debug Delete ❌
        print(f"""
        TARGET: {target}
        PIPELINE: {pipeline_id}
        WORKSPACE: {workspace_id}
        DEV_STAGE: {dev_stage_id}
        TEST_STAGE: {test_stage_id}
        """)

        #-------------------------------------------
        # --- 3.2 Git Credentials Configuration  ---
        cred_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/myGitCredentials"

        cred_payload = {
            "source": "ConfiguredConnection",
            "connectionId": connection_id
        }

        cred_response = requests.patch(cred_url, headers=headers, json=cred_payload)
        print("Git credentials configured:", cred_response.text)

        # -----------------------------------------------------------
        # --- 3.3 Get Workspace Git status before Synchronization ---
        status_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/status"

        status_response = requests.get(status_url, headers=headers)
        status_data = status_response.json()

        print("Workspace status BEFORE sync:", status_data)

        workspace_head = status_data.get("workspaceHead") or ""

        # --- Capture the status changes for potential deploy operation later ---
        changes = status_data.get("changes", [])

        # ----------------------------------------------
        # --- 3.4 Sync Workspace with Git Repository ---
        print(f"\n=== Start sync Workspace ←→ GitHub: {target} ===\n")
        
        sync_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/updateFromGit"

        payload = {
            "remoteCommitHash": remote_commit,
            "workspaceHead": workspace_head,
            "options": {
                "allowOverrideItems": True
            }
        }

        sync_response = requests.post(sync_url, headers=headers, json=payload)

        print("Sync response:", sync_response.text)

        # ---------------------------------
        # --- 3.5 Wait Sync to complete ---
        for i in range(10):
            status_check = requests.get(status_url, headers=headers).json()

            workspace_head = status_check.get("workspaceHead")
            remote_head = status_check.get("remoteCommitHash")

            if workspace_head == remote_head:
                print(f"✅ Sync completed → {workspace_head}")
                break

            if i == 0:
                print(f"🔄 Sync started → {workspace_head} → {remote_head}")

            time.sleep(5)

        # ---------------------------------------------------
        # --- 3.6 Store Workspace Commit Head before sync ---
        print(f"WORKSPACE_HEAD_BEFORE={workspace_head}")

        with open(os.environ['GITHUB_ENV'], 'a') as f:
            f.write(f"WORKSPACE_HEAD_BEFORE={workspace_head}\n")

        if not workspace_head:
            raise Exception("WORKSPACE_HEAD_BEFORE not found")

        # ---------------------------------------------------
        # --- 3.7. Build the list of Items for Deployment ---
        # Load the item type mapping from file
        with open("ci/config/item_type_mapping.json") as f:
            ITEM_TYPE_MAP = json.load(f)

        # Prepare items list
        items_to_deploy = []

        # Request the workspace existing items to use in case of Added objects from the Git repo
        workspace_items = get_items(workspace_id, token)

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

            # Scenario 1 → Workspace new items Added from Git repo 
            # Items source → get_items function
            elif remote_change == "Added":
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
                # Debug Output
                if not found:
                    print(f"⚠️ No match found for: {display_name} ({mapped_type})")

        print("Items to deploy:", items_to_deploy)

        # Delte Debug ❌
        for change in changes:
            print("RAW CHANGE:", change)

        if changes:
            print(f"RAW TYPE: {raw_type}")
            print(f"MAPPED TYPE: {mapped_type}")

        # -----------------------------------------------------
        # --- 3.8 Executing the deployment from Dev to Test ---
        # Create the deployment note from the commit message
        note = f"commit={remote_commit[:7]} | branch={branch} | approver={approver} | author={author} | msg={message}"
        print("Deployment note:", note)

        # Execute Deploy
        has_items = len(items_to_deploy) > 0
        if not has_items:
            print("No items to deploy → skipping")
        else:
            url = f"https://api.fabric.microsoft.com/v1/deploymentPipelines/{pipeline_id}/deploy"

            payload = {
                "sourceStageId": dev_stage_id,
                "targetStageId": test_stage_id,
                "items": items_to_deploy,
                "note": note
            }

            response = requests.post(url, headers=headers, json=payload)

            deployment_id = None
            for key, value in response.headers.items():
                if key.lower() == "deployment-id":
                    deployment_id = value.strip()
                    break
            
            # Delete - debug only ❌
            print("All headers:", dict(response.headers))
            print("Deployment ID:", deployment_id)
            
            if deployment_id:
                print(f"Deployment ID for {target}: {deployment_id}")
                with open(os.environ["GITHUB_ENV"], "a") as f:
                    f.write(f"OPERATION_ID_{target.upper()}={deployment_id}\n")

            # Delete - debug only ❌
            print(response.status_code)
            print(response.headers)
            print("FINAL PAYLOAD:", payload)

            results.append((target, "SUCCESS"))

    except Exception as e:
        print(f"❌ Error in {target}: {str(e)}")
        results.append((target, "FAILED"))


# ======================
# 4. EXECUTION SUMMARY
# =====================
print("\n=== Execution Summary ===")

failures = [r for r in results if r[1] == "FAILED"]

for target, status in results:
    print(f"{target}: {status}")

if failures:
    print("\n❌ Some targets failed:")
    for f in failures:
        print(f"- {f[0]}")
    exit(1)
else:
    print("\n✅ All targets succeeded")
    exit(0)