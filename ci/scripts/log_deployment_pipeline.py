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
github_run_url = f"{base}/{repo}/actions/runs/{run_id}"


# Debug delete ❌
print("Targets for logging:", targets)

# Install Pipelines client 
pl = pipelines.Pipelines(token)

# Function to check the pipeline operation status
def wait_for_completion(pl, pipeline_id, operation_id, max_retries=15, wait_seconds=10):
    for i in range(max_retries):
        data = pl.get_pipeline_operation(pipeline_id, operation_id)
        df = pd.DataFrame(data)

        if df.empty:
            print(f"Attempt {i+1}: empty response")
            time.sleep(wait_seconds)
            continue

        status = df["operationStatus"].iloc[0]

        print(f"Attempt {i+1}: {status}")

        if status not in ["NotStarted", "InProgress"]:
            print("✅ Deployment finished")
            return df

        time.sleep(wait_seconds)

    print("⚠️ Timeout waiting for deployment")
    return df

# ========================
# 2. Loop por target
# ========================
results = []

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
        df = wait_for_completion(pl, pipeline_id, operation_id)

        log_entry = {
            "operationId": operation_id,
            "target": target,
            "commit": commit,
            "github_run": github_run_url
        }

        print("✅ LOG ENTRY:", log_entry)

        results.append(log_entry)

    except Exception as e:
        print(f"❌ Error logging {target}: {str(e)}")