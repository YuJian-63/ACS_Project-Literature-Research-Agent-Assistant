def automatic_budget(task) -> bool:
    return task.workflow_version == "langgraph-review-v2" or task.run_config.get("budget_mode") == "automatic"
