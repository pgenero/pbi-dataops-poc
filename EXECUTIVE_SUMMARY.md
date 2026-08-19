# Fabric CI/CD Integration

## 📌 Key points of the framework

- The Git `main` branch is synchronized with each current Dev workspace.

- The Test workspace has no branch; it only contains artifacts that are deployed to Test via automated deployment tasks from Dev.

- The Prod workspace copies the code (*via a synchronization operation*) to a special Git `snapshot branch`. This branch contains the production code. This occurs after deployment to Prod.

- Each developer must have their own set of `feature workspaces` (**fw**).  

    Example:

        fw-anna-sales, fw-anna-finance, fw-anna-..., fw-john-..., fw-lisa-...

- All changes must be managed using `feature branches`. Changes are merged into the `main branc` (Dev) ***ONLY*** via `pull requests` from `feature branch` to `main`.

- Dataflows Gen1 are not supported in Git. Deploying these artifacts is still a manual process. 

    *Alternatives, from best to worst*: 
        
    - move the logic to Snowflake 
    - add the logic to the Lakehouse (the one used by the “2.0”)
    - migrate all to Dataflow Gen 2. 
    
    **Any of these options requires reworking models and reports to adapt them to the new architecture.**

---

## ♻️ Architecture Flow

![Flow Summary](../pbi-dataops-poc/docs/assets/executive_summary_flow.png)

---

## 📝 High-Level Description of the Workflow 

1. **Developer Scope**

    All changes must be developed on feature branches. The process was designed so that each request in HALO (SR) results in a feature branch. As a best practice, we can include the SR number in the branch name. Example: fb-SR00112233.

    Each developer must have their own set of `feature workspaces` to test the changes in the Service. There are different strategies for how to proceed at this stage (perform changes in the desktop, or in the service, etc.). 
    
    > A common approach would be to update a Power BI report and publish it (via Git) to the feature workspace. This allows the user to test the report’s functionality.

2. **Merge Pull Request**

    When all changes are complete, the developer must open a `Pull Request` on **GitHub** so that the code in the feature branch is added to the main branch. To move the changes, `another user` must approve the `Pull Request`. This action merges the changes between the feature branch and the main branch. The feature branch remains open in case additional changes are required.

3. **Git Action Deploy Dev to Test**

    Once the `PR` is approved on GitHub, the code is merged into the `main branch`. The merge triggers an automated workflow with **GitHub Actions** that does the following:

    - **Git ↔ Dev Workspace Sync:** 
    
        The code in the main branch is synced with Fabric. This way, all the changes that have been pushed to main will be visible in the Dev Workspace.

    - **Deploy to Test:** 
    
        Deploy the artifacts with changes (or added artifacts) to Test. The deployment is automatic and generates a note containing: 
        
        - commit HASH of the merge PR (short version, 7 digits)
        - the name of the feature branch (which should contain the Halo SR) 
        - Git approver of the PR 
        - developer who opened the PR
        - PR message
            
                commit=a905977 | branch=fb-SR00112233 | approver= ravishm | author=pgenero | msg=Update Sales Report SR-00112233

    - **App update:** 
    
        We need to switch from the traditional Power BI app we’re currently using to an **OrgApp**, which is a new version in Fabric. It works differently, and the advantage is that it doesn’t require an update.

    - **Semantic Model Refresh:** 
    
        If changes are made to a Semantic Model, the data model in Test is also refreshed. The refresh can cover the entire model or just the affected tables (to save resources). The developers have the option when they open the PR to choose whether or not to refresh the model when it reaches the Test workspace. The process automatically decides whether to refresh the entire model or just the affected tables, depending on the changes made.

4. **Git Action Deploy to Prod – Manual trigger**

    In Git Actions, there is another workflow that is triggered manually. Once the changes have been approved by the requestor (end user), we have to trigger the action **manually**. This action requires an input parameter, which is the name of the feature branch (for example, SR-00112233). This process was designed to be run manually only by users authorized to deploy to production. Simply enter the branch, and then the automated workflow begins.

5. **Git Action Deploy to Prod – Automatic flow**

    Once the action is triggered, the workflow begins to deploy to Prod (from Test) the changes made to the feature branch specified as a parameter. 
    
    - The action deploys only the relevant artifacts to Prod.  The deployment note contains this message:  Deploy from branch feature-e012

    - Once the deployment is complete, the Fabric Prod workspace is synchronized with Git on the snapshot branch containing the versioned backup of the production code.

    - Finally, the feature branch is deleted. It is assumed that the changes have been completed, and the branch is deleted as a safety measure. 

