"""Syntax/contract checks only; these do not substitute for a workspace run."""
import ast
from pathlib import Path

import sqlglot
import yaml


ROOT = Path(__file__).resolve().parents[2] / "databricks"


def test_notebook_python_and_embedded_sql_parse():
    substitutions={"ns":"workspace.appliance_energy","namespace":"workspace.appliance_energy","max_gap":"120","catalog":"workspace","schema":"appliance_energy"}
    checked=0
    for notebook in (ROOT/"notebooks").glob("*.py"):
        tree=ast.parse(notebook.read_text(encoding="utf-8"),filename=str(notebook))
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute) or node.func.attr!="sql" or not node.args:
                continue
            argument=node.args[0]
            if isinstance(argument,ast.Constant) and isinstance(argument.value,str):
                sql=argument.value
            elif isinstance(argument,ast.JoinedStr):
                parts=[]
                for value in argument.values:
                    if isinstance(value,ast.Constant):parts.append(value.value)
                    elif isinstance(value,ast.FormattedValue) and isinstance(value.value,ast.Name):parts.append(substitutions[value.value.id])
                    else:break
                else:
                    sql="".join(parts)
                    sqlglot.parse(sql,read="databricks")
                    checked+=1
                continue
            else:
                continue
            sqlglot.parse(sql,read="databricks")
            checked+=1
    assert checked>=10


def test_bundle_references_real_notebooks_and_has_no_running_schedule():
    bundle=yaml.safe_load((ROOT/"databricks.yml").read_text())
    job=bundle["resources"]["jobs"]["appliance_lakehouse"]
    assert job["max_concurrent_runs"]==1
    assert "schedule" not in job and "continuous" not in job
    assert "default" not in bundle["variables"]["landing_path"]
    for task in job["tasks"]:
        assert (ROOT/task["notebook_task"]["notebook_path"]).is_file()
        assert "new_cluster" not in task
