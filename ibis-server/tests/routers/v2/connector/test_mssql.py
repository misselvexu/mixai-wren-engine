import base64
import urllib

import orjson
import pandas as pd
import pytest
import sqlalchemy
from fastapi.testclient import TestClient
from sqlalchemy import text
from testcontainers.mssql import SqlServerContainer

from app.main import app
from app.model.validator import rules
from tests.conftest import file_path

pytestmark = pytest.mark.mssql

base_url = "/v2/connector/mssql"

manifest = {
    "catalog": "my_catalog",
    "schema": "my_schema",
    "models": [
        {
            "name": "Orders",
            "refSql": "select * from dbo.orders",
            "columns": [
                {"name": "orderkey", "expression": "o_orderkey", "type": "integer"},
                {"name": "custkey", "expression": "o_custkey", "type": "integer"},
                {
                    "name": "orderstatus",
                    "expression": "o_orderstatus",
                    "type": "varchar",
                },
                {
                    "name": "totalprice",
                    "expression": "o_totalprice",
                    "type": "float",
                },
                {"name": "orderdate", "expression": "o_orderdate", "type": "date"},
                {
                    "name": "order_cust_key",
                    "expression": "concat(o_orderkey, '_', o_custkey)",
                    "type": "varchar",
                },
                {
                    "name": "timestamp",
                    "expression": "cast('2024-01-01T23:59:59' as timestamp)",
                    "type": "timestamp",
                },
                {
                    "name": "timestamptz",
                    "expression": "cast('2024-01-01T23:59:59' as timestamp with time zone)",
                    "type": "timestamp",
                },
                {
                    "name": "test_null_time",
                    "expression": "cast(NULL as timestamp)",
                    "type": "timestamp",
                },
                {
                    "name": "bytea_column",
                    "expression": "cast('abc' as bytea)",
                    "type": "bytea",
                },
            ],
            "primaryKey": "orderkey",
        },
    ],
}


@pytest.fixture
def manifest_str():
    return base64.b64encode(orjson.dumps(manifest)).decode("utf-8")


@pytest.fixture(scope="module")
def mssql(request) -> SqlServerContainer:
    mssql = SqlServerContainer(
        "mcr.microsoft.com/mssql/server:2019-CU27-ubuntu-20.04",
        dialect="mssql+pyodbc",
        password="{R;3G1/8Al2AniRye",
    ).start()
    engine = sqlalchemy.create_engine(
        f"{mssql.get_connection_url()}?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=YES"
    )
    pd.read_parquet(file_path("resource/tpch/data/orders.parquet")).to_sql(
        "orders", engine, index=False
    )
    with engine.begin() as conn:
        conn.execute(
            text("""
                EXEC sys.sp_addextendedproperty
                    @name = N'MS_Description',
                    @value = N'This is a table comment',
                    @level0type = N'SCHEMA', @level0name = 'dbo',
                    @level1type = N'TABLE',  @level1name = 'orders';
            """)
        )
        conn.execute(
            text("""
                EXEC sys.sp_addextendedproperty 
                    @name = N'MS_Description', 
                    @value = N'This is a comment', 
                    @level0type = N'SCHEMA', @level0name = 'dbo',
                    @level1type = N'TABLE',  @level1name = 'orders',
                    @level2type = N'COLUMN', @level2name = 'o_comment';
            """)
        )
    request.addfinalizer(mssql.stop)
    return mssql


with TestClient(app) as client:

    def test_query(manifest_str, mssql: SqlServerContainer):
        connection_info = _to_connection_info(mssql)
        response = client.post(
            url=f"{base_url}/query",
            json={
                "connectionInfo": connection_info,
                "manifestStr": manifest_str,
                "sql": 'SELECT * FROM "Orders" LIMIT 1',
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert len(result["columns"]) == len(manifest["models"][0]["columns"])
        assert len(result["data"]) == 1
        assert result["data"][0] == [
            1,
            370,
            "O",
            "172799.49",
            "1996-01-02",
            "1_370",
            "2024-01-01 23:59:59.000000",
            "2024-01-01 23:59:59.000000 UTC",
            None,
            "616263",
        ]
        assert result["dtypes"] == {
            "orderkey": "int32",
            "custkey": "int32",
            "orderstatus": "object",
            "totalprice": "object",
            "orderdate": "object",
            "order_cust_key": "object",
            "timestamp": "object",
            "timestamptz": "object",
            "test_null_time": "datetime64[ns]",
            "bytea_column": "object",
        }

    @pytest.mark.skip("Wait ibis handle special characters in connection string")
    def test_query_with_connection_url(manifest_str, mssql: SqlServerContainer):
        connection_url = _to_connection_url(mssql)
        response = client.post(
            url=f"{base_url}/query",
            json={
                "connectionInfo": {"connectionUrl": connection_url},
                "manifestStr": manifest_str,
                "sql": 'SELECT * FROM "Orders" LIMIT 1',
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert len(result["columns"]) == len(manifest["models"][0]["columns"])
        assert len(result["data"]) == 1
        assert result["data"][0][0] == 1
        assert result["dtypes"] is not None

    def test_query_without_manifest(mssql: SqlServerContainer):
        connection_info = _to_connection_info(mssql)
        response = client.post(
            url=f"{base_url}/query",
            json={
                "connectionInfo": connection_info,
                "sql": 'SELECT * FROM "Orders" LIMIT 1',
            },
        )
        assert response.status_code == 422
        result = response.json()
        assert result["detail"][0] is not None
        assert result["detail"][0]["type"] == "missing"
        assert result["detail"][0]["loc"] == ["body", "manifestStr"]
        assert result["detail"][0]["msg"] == "Field required"

    def test_query_without_sql(manifest_str, mssql: SqlServerContainer):
        connection_info = _to_connection_info(mssql)
        response = client.post(
            url=f"{base_url}/query",
            json={"connectionInfo": connection_info, "manifestStr": manifest_str},
        )
        assert response.status_code == 422
        result = response.json()
        assert result["detail"][0] is not None
        assert result["detail"][0]["type"] == "missing"
        assert result["detail"][0]["loc"] == ["body", "sql"]
        assert result["detail"][0]["msg"] == "Field required"

    def test_query_without_connection_info(manifest_str):
        response = client.post(
            url=f"{base_url}/query",
            json={
                "manifestStr": manifest_str,
                "sql": 'SELECT * FROM "Orders" LIMIT 1',
            },
        )
        assert response.status_code == 422
        result = response.json()
        assert result["detail"][0] is not None
        assert result["detail"][0]["type"] == "missing"
        assert result["detail"][0]["loc"] == ["body", "connectionInfo"]
        assert result["detail"][0]["msg"] == "Field required"

    def test_query_with_dry_run(manifest_str, mssql: SqlServerContainer):
        connection_info = _to_connection_info(mssql)
        response = client.post(
            url=f"{base_url}/query",
            params={"dryRun": True},
            json={
                "connectionInfo": connection_info,
                "manifestStr": manifest_str,
                "sql": 'SELECT * FROM "Orders" LIMIT 1',
            },
        )
        assert response.status_code == 204

    def test_query_with_dry_run_and_invalid_sql(
        manifest_str, mssql: SqlServerContainer
    ):
        connection_info = _to_connection_info(mssql)
        response = client.post(
            url=f"{base_url}/query",
            params={"dryRun": True},
            json={
                "connectionInfo": connection_info,
                "manifestStr": manifest_str,
                "sql": "SELECT * FROM X",
            },
        )
        assert response.status_code == 422
        assert "Invalid object name 'X'" in response.text

    def test_validate_with_unknown_rule(manifest_str, mssql: SqlServerContainer):
        connection_info = _to_connection_info(mssql)
        response = client.post(
            url=f"{base_url}/validate/unknown_rule",
            json={
                "connectionInfo": connection_info,
                "manifestStr": manifest_str,
                "parameters": {"modelName": "Orders", "columnName": "orderkey"},
            },
        )
        assert response.status_code == 404
        assert (
            response.text
            == f"The rule `unknown_rule` is not in the rules, rules: {rules}"
        )

    def test_validate_rule_column_is_valid(manifest_str, mssql: SqlServerContainer):
        connection_info = _to_connection_info(mssql)
        response = client.post(
            url=f"{base_url}/validate/column_is_valid",
            json={
                "connectionInfo": connection_info,
                "manifestStr": manifest_str,
                "parameters": {"modelName": "Orders", "columnName": "orderkey"},
            },
        )
        assert response.status_code == 204

    def test_validate_rule_column_is_valid_with_invalid_parameters(
        manifest_str, mssql: SqlServerContainer
    ):
        connection_info = _to_connection_info(mssql)
        response = client.post(
            url=f"{base_url}/validate/column_is_valid",
            json={
                "connectionInfo": connection_info,
                "manifestStr": manifest_str,
                "parameters": {"modelName": "X", "columnName": "orderkey"},
            },
        )
        assert response.status_code == 422

        response = client.post(
            url=f"{base_url}/validate/column_is_valid",
            json={
                "connectionInfo": connection_info,
                "manifestStr": manifest_str,
                "parameters": {"modelName": "Orders", "columnName": "X"},
            },
        )
        assert response.status_code == 422

    def test_validate_rule_column_is_valid_without_parameters(
        manifest_str, mssql: SqlServerContainer
    ):
        connection_info = _to_connection_info(mssql)
        response = client.post(
            url=f"{base_url}/validate/column_is_valid",
            json={"connectionInfo": connection_info, "manifestStr": manifest_str},
        )
        assert response.status_code == 422
        result = response.json()
        assert result["detail"][0] is not None
        assert result["detail"][0]["type"] == "missing"
        assert result["detail"][0]["loc"] == ["body", "parameters"]
        assert result["detail"][0]["msg"] == "Field required"

    def test_validate_rule_column_is_valid_without_one_parameter(
        manifest_str, mssql: SqlServerContainer
    ):
        connection_info = _to_connection_info(mssql)
        response = client.post(
            url=f"{base_url}/validate/column_is_valid",
            json={
                "connectionInfo": connection_info,
                "manifestStr": manifest_str,
                "parameters": {"modelName": "Orders"},
            },
        )
        assert response.status_code == 422
        assert response.text == "Missing required parameter: `columnName`"

        response = client.post(
            url=f"{base_url}/validate/column_is_valid",
            json={
                "connectionInfo": connection_info,
                "manifestStr": manifest_str,
                "parameters": {"columnName": "orderkey"},
            },
        )
        assert response.status_code == 422
        assert response.text == "Missing required parameter: `modelName`"

    def test_metadata_list_tables(mssql: SqlServerContainer):
        connection_info = _to_connection_info(mssql)
        response = client.post(
            url=f"{base_url}/metadata/tables",
            json={"connectionInfo": connection_info},
        )
        assert response.status_code == 200

        result = next(filter(lambda x: x["name"] == "dbo.orders", response.json()))
        assert result["name"] == "dbo.orders"
        assert result["primaryKey"] is not None
        assert result["description"] == "This is a table comment"
        assert result["properties"] == {
            "catalog": "tempdb",
            "schema": "dbo",
            "table": "orders",
        }
        assert len(result["columns"]) == 9
        assert result["columns"][8] == {
            "name": "o_comment",
            "nestedColumns": None,
            "type": "VARCHAR",
            "notNull": False,
            "description": "This is a comment",
            "properties": None,
        }

    def test_metadata_list_constraints(mssql: SqlServerContainer):
        connection_info = _to_connection_info(mssql)
        response = client.post(
            url=f"{base_url}/metadata/constraints",
            json={"connectionInfo": connection_info},
        )
        assert response.status_code == 200

    def test_metadata_db_version(mssql: SqlServerContainer):
        connection_info = _to_connection_info(mssql)
        response = client.post(
            url=f"{base_url}/metadata/version",
            json={"connectionInfo": connection_info},
        )
        assert response.status_code == 200
        assert "Microsoft SQL Server 2019" in response.text

    def _to_connection_info(mssql: SqlServerContainer):
        return {
            "host": mssql.get_container_host_ip(),
            "port": mssql.get_exposed_port(mssql.port),
            "user": mssql.username,
            "password": mssql.password,
            "database": mssql.dbname,
            "kwargs": {"TrustServerCertificate": "YES"},
        }

    def _to_connection_url(mssql: SqlServerContainer):
        info = _to_connection_info(mssql)
        return f"mssql://{info['user']}:{urllib.parse.quote_plus(info['password'])}@{info['host']}:{info['port']}/{info['database']}?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=YES"
