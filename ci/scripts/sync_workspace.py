
import os
import requests
import time
import json

token = os.getenv("TOKEN")
connection_id = os.getenv("GIT_CONNECTION_ID")
remote_commit = os.getenv("GITHUB_SHA")
branch = os.getenv("GITHUB_REF_NAME")
actor = os.getenv("GITHUB_ACTOR")
message = os.getenv("COMMIT_MESSAGE")
targets = os.getenv("TARGETS", "").split()

# Debug Detele ❌
print("Targets detected:", targets)

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

results = []

for target in targets:
    print(f"\n=== Processing target: {target} ===\n")

    try:
        # map target → pipeline/workspace
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

        # dEBUG dELETE ❌
        print(f"""
        TARGET: {target}
        PIPELINE: {pipeline_id}
        WORKSPACE: {workspace_id}
        DEV_STAGE: {dev_stage_id}
        TEST_STAGE: {test_stage_id}
        """)

        # 1. Configure Credentials
        cred_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/myGitCredentials"

        cred_payload = {
            "source": "ConfiguredConnection",
            "connectionId": connection_id
        }

        cred_response = requests.patch(cred_url, headers=headers, json=cred_payload)
        print("Git credentials configured:", cred_response.text)

        # 2. Get Status
        status_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/status"

        status_response = requests.get(status_url, headers=headers)
        status_data = status_response.json()

        print("Workspace status BEFORE sync:", status_data)

        workspace_head = status_data.get("workspaceHead") or ""

        # 2.1. Capture the status changes for the deploy operation
        changes = status_data.get("changes", [])

        # 3. Sync Workspace with Git Repository
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

        # 4. Wait sync to complete
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

        # 5. Workspace commit head before sync
        print(f"WORKSPACE_HEAD_BEFORE={workspace_head}")

        with open(os.environ['GITHUB_ENV'], 'a') as f:
            f.write(f"WORKSPACE_HEAD_BEFORE={workspace_head}\n")

        if not workspace_head:
            raise Exception("WORKSPACE_HEAD_BEFORE not found")

        # 6. Items to deploy
        # 6.1 Load the item type mapping from file
        with open("ci/config/item_type_mapping.json") as f:
            ITEM_TYPE_MAP = json.load(f)

        # 6.2 Prepare items list
        items_to_deploy = []

        for change in changes:
            metadata = change.get("itemMetadata", {})
            identifier = metadata.get("itemIdentifier", {})

            raw_type = metadata.get("itemType")

            if "objectId" in identifier and change.get("remoteChange") in ["Added", "Modified"]:
                mapped_type = ITEM_TYPE_MAP.get((raw_type or "").lower(), raw_type)
                item = {
                    "sourceItemId": identifier["objectId"],
                    "itemType": mapped_type
                }
                items_to_deploy.append(item)

        print("Items to deploy", items_to_deploy)

        # Delte Debug ❌
        for change in changes:
            print("RAW CHANGE:", change)

        print(f"RAW TYPE: {raw_type}")
        print(f"MAPPED TYPE: {mapped_type}")

        # 7. Deploy the artifacts stored in the list
        # 7.1. Create the commit note
        note = f"commit={remote_commit[:7]} | branch={branch} | by={actor} | msg={message}"
        print("Deployment note:", note)

        # 7.2. Run the deploy
        if not items_to_deploy:
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

# Final block - Execution Summary
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
