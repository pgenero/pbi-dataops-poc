import os
import json
from datetime import datetime
import pandas as pd
# simplepbi for Power BI API REST
from simplepbi import pipelines

# Variables
token = os.getenv("TOKEN")
# workspace_id = os.getenv("WORKSPACE_ID")
# pipeline_id = os.getenv("PIPELINE_ID")
targets = os.getenv("TARGETS", "").split()
# operation_id = os.getenv("OPERATION_ID")
gitHub_runId = os.getenv("GITHUB_RUN_URL")

# Debug delete ❌
print("Targets for logging:", targets)

# Install Pipelines client 
pl = pipelines.Pipelines(token)

results = []


# ========================
# 2. Loop por target
# ========================
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

        # 2.3 Capture the Pipeline Name
        pipelineName = pl.get_pipeline(pipeline_id).get('displayName',{})

        # 2.4 Empty list to store operations outputs
        pipelineOperationData = []

        # 2.5 Get the deatils for the pipeline operation
        pipelineOperationRaw = pl.get_pipeline_operation(pipeline_id, operation_id)

        # 2.6 Navigate the json output and extract the operation details
        # executionPlan > steps: enumerates the artifacts deployed
        # executionPlan > steps > sourceAndTarget: contains the detail of the artifact deployed
        for step in pipelineOperationRaw.get("executionPlan", {}).get("steps", []):
            source_target = step.get("sourceAndTarget", {})
            # Extract the operation details
            details = {
                "gitHubRunId": gitHub_runId,
                "pipeline_id": pipeline_id,
                "pipelineName": pipelineName,
                "operationId": operation_id,
                "operationStatus": pipelineOperationRaw.get("status"),
                "executionStartTime": pipelineOperationRaw.get("executionStartTime"),
                "executionEndTime": pipelineOperationRaw.get("executionEndTime"),
                "sourceStageOrder": pipelineOperationRaw.get("sourceStageOrder"),
                "targetStageOrder": pipelineOperationRaw.get("targetStageOrder"),
                "executionIndex": step.get("index"),
                "executionStatus": step.get("status"),
                "itemType": source_target.get("type"),
                "sourceItemId": source_target.get("source"),
                "sourceItemName": source_target.get("sourceDisplayName"),
                "targetItemId": source_target.get("target"),
                "targetItemName": source_target.get("targetDisplayName"),
                "preDeploymentDiffState": step.get("preDeploymentDiffState"),
                "deploymentNote": pipelineOperationRaw.get("note", {}).get("content",{}),
                "newArtifactsCount": pipelineOperationRaw.get("preDeploymentDiffInformation", {}).get("newArtifactsCount",{}),
                "differentArtifactsCount": pipelineOperationRaw.get("preDeploymentDiffInformation", {}).get("differentArtifactsCount",{}),
                "noDifferenceArtifactsCount": pipelineOperationRaw.get("preDeploymentDiffInformation", {}).get("noDifferenceArtifactsCount",{}),
                "userPrincipalName": pipelineOperationRaw.get("performedBy", {}).get("userPrincipalName",{}),
                "principalType": pipelineOperationRaw.get("performedBy", {}).get("principalType",{}),
            }
            pipelineOperationData.append(details)

        # 2.7 Create a Pandas DataFrame
        df=pd.DataFrame(pipelineOperationData)

        if df.empty:
            print(f"⚠️ No data returned for {target}")
            results.append((target, "EMPTY"))
            continue

        # 2.8 Create columns to display time in US Central Time
        # Convert to datetime
        df["executionStartTime"] = pd.to_datetime(df["executionStartTime"], utc=True)
        df["executionEndTime"] = pd.to_datetime(df["executionEndTime"], utc=True)
        # Convert to US Central Time
        df["executionStartTime_CT"] = df["executionStartTime"].dt.tz_convert("America/Chicago")
        df["executionEndTime_CT"] = df["executionEndTime"].dt.tz_convert("America/Chicago")
        # Add deploy duration in seconds
        df["durationSeconds"] = ( df["executionEndTime"] - df["executionStartTime"] ).dt.total_seconds()

        # Adjust Print in Git Actions
        pd.set_option("display.max_columns", None)
        print(df.to_string())

        results.append((target, "SUCCESS"))

    except Exception as e:
        print(f"❌ Error logging {target}: {str(e)}")
        results.append((target, "FAILED"))

# ========================
# 3. Final Summary
# ========================
print("\n=== Execution Summary ===")

for target, status in results:
    print(f"{target}: {status}")

failures = [r for r in results if r[1] == "FAILED"]

if failures:
    print("\n❌ Some targets failed")
    exit(1)
else:
    print("\n✅ Logging completed successfully")
    exit(0)