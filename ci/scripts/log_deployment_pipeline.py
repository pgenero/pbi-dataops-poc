import os
import json
from datetime import datetime
import pandas as pd
# simplepbi for Power BI API REST
from simplepbi import pipelines

# Variables
token = os.getenv("TOKEN")
workspace_id = os.getenv("WORKSPACE_ID")
pipeline_id = os.getenv("PIPELINE_ID")
target = os.getenv("TARGET")
operation_id = os.getenv("OPERATION_ID")
gitHub_runId = os.getenv("GITHUB_RUN_URL")

# Install Pipelines client 
pl = pipelines.Pipelines(token)

# 1. Capture the Pipeline Name
pipelineName = pl.get_pipeline(pipeline_id).get('displayName',{})

# 2.Empty list to store operations outputs
pipelineOperationData = []

# 3. Get the deatils for the pipeline operation
pipelineOperationRaw = pl.get_pipeline_operation(pipeline_id, operation_id)

# Navigate the json output and extract the operation details
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

# 4. Create a Pandas DataFrame
df=pd.DataFrame(pipelineOperationData)

# Create columns to display time in US Central Time
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