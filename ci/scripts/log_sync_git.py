import os
import json
from datetime import datetime
import pandas as pd
# simplepbi for Power BI API REST
from simplepbi import pipelines

# Variables
workspace_id = os.getenv("WORKSPACE_ID")
target = os.getenv("TARGET")

remote_commit = os.getenv("GITHUB_SHA")
workspace_head_before = os.getenv("WORKSPACE_HEAD_BEFORE")

# Log structure
log_entry = {
    "timestamp": datetime.utcnow().isoformat(),
    "workspaceId": workspace_id,
    "environment": target,
    "fromCommit": workspace_head_before,
    "toCommit": remote_commit,
    "status": "SUCCESS"
}

print("SOX_LOG:", json.dumps(log_entry, indent=2))