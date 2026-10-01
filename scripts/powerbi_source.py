"""Build parameterized Power Query imports for governed Databricks gold tables."""
import json
from pathlib import Path
import re


def m_text(value: str) -> str:
    return '"' + value.replace('#', '#(#)').replace('"', '""').replace('\r', '#(cr)').replace('\n', '#(lf)') + '"'


def m_parameter(name: str, value: str) -> dict:
    return {"name": name, "kind": "m", "expression": m_text(value) + ' meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'}


def connection_parameters(path: Path) -> dict:
    settings = json.loads(path.read_text(encoding="utf-8-sig"))
    allowed = {"host", "http_path", "catalog", "schema", "cloud"}
    if not isinstance(settings, dict) or set(settings) - allowed:
        raise ValueError("Connection JSON accepts only host, http_path, catalog, schema and cloud; credentials belong in Power BI")
    host = settings.get("host", "")
    http_path = settings.get("http_path", "")
    catalog = settings.get("catalog", "workspace")
    schema = settings.get("schema", "appliance_energy")
    cloud = settings.get("cloud", "aws")
    if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host):
        raise ValueError("host must be a hostname without scheme, path or credentials")
    if not isinstance(http_path, str) or not re.fullmatch(r"/sql/1\.0/warehouses/[A-Za-z0-9-]+", http_path):
        raise ValueError("http_path must identify a SQL warehouse")
    if any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v) for v in (catalog, schema)):
        raise ValueError("catalog and schema must be simple SQL identifiers")
    if cloud not in ("aws", "azure"):
        raise ValueError("cloud must be aws or azure")
    return {"DatabricksHost": host, "DatabricksHttpPath": http_path,
            "DatabricksCatalog": catalog, "DatabricksSchema": schema,
            "connector": "DatabricksMultiCloud" if cloud == "aws" else "Databricks"}


def native_source(table: str, headers: list[str], changes: list[str], connection: dict) -> list[str]:
    if table not in ("gold_device_daily", "forecast_daily"):
        raise ValueError("Only the report's approved gold tables may be imported")
    return ["let",
            f'    Source = {connection["connector"]}.Catalogs(DatabricksHost, DatabricksHttpPath, [Catalog=DatabricksCatalog, Database=DatabricksSchema, Implementation="2.0"]),',
            '    Catalog = Source{[Name=DatabricksCatalog, Kind="Database"]}[Data],',
            '    Schema = Catalog{[Name=DatabricksSchema, Kind="Schema"]}[Data],',
            f'    Gold = Schema{{[Name={m_text(table)}, Kind="Table"]}}[Data],',
            '    Headers = Table.SelectColumns(Gold, {' + ', '.join(m_text(h) for h in headers) + '}),',
            '    Typed = Table.TransformColumnTypes(Headers, {' + ', '.join(changes) + '}, "en-US"),',
            '    Cohort = Table.SelectRows(Typed, each [source_kind] = SourceKind)',
            "in", "    Cohort"]
