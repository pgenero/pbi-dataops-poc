
import os
import requests
import time

token = os.getenv("TOKEN")
pipeline_id = os.getenv("PIPELINE_ID")
workspace_id = os.getenv("WORKSPACE_ID")
dev_stage_id = os.getenv("DEV_STAGE_ID")
test_stage_id = os.getenv("TEST_STAGE_ID")
connection_id = os.getenv("GIT_CONNECTION_ID")
remote_commit = os.getenv("GITHUB_SHA")
branch = os.getenv("GITHUB_REF_NAME")
actor = os.getenv("GITHUB_ACTOR")
message = os.getenv("COMMIT_MESSAGE")


headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

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

# 6. Prepare the list of artifacts for the deploy
items_to_deploy = []

for change in changes:
    metadata = change.get("itemMetadata", {})
    identifier = metadata.get("itemIdentifier", {})

    if "objectId" in identifier and change.get("remoteChange") in ["Added", "Modified"]:
        items_to_deploy.append({
            "sourceItemId": identifier["objectId"],
            "itemType": metadata.get("itemType")
        })

print(f"Items to deploy: {items_to_deploy}")

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

    deployment_id = response.headers.get("deployment-id")

    print("Operation ID:", deployment_id)

    if deployment_id:
        with open(os.environ["GITHUB_ENV"], "a") as f:
            f.write(f"OPERATION_ID={deployment_id}\n")
