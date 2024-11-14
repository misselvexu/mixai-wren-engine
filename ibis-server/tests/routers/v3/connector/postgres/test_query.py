import base64

import orjson
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.routers.v3.connector.postgres.conftest import base_url

manifest = {
    "catalog": "wren",
    "schema": "public",
    "models": [
        {
            "name": "orders",
            "tableReference": {
                "schema": "public",
                "table": "orders",
            },
            "columns": [
                {"name": "o_orderkey", "type": "integer"},
                {"name": "o_custkey", "type": "integer"},
                {
                    "name": "o_orderstatus",
                    "type": "varchar",
                },
                {
                    "name": "o_totalprice",
                    "type": "double",
                },
                {"name": "o_orderdate", "type": "date"},
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
                    "type": "timestamptz",
                },
                {
                    "name": "dst_utc_minus_5",
                    "expression": "cast('2024-01-15 23:00:00 America/New_York' as timestamp with time zone)",
                    "type": "timestamptz",
                },
                {
                    "name": "dst_utc_minus_4",
                    "expression": "cast('2024-07-15 23:00:00 America/New_York' as timestamp with time zone)",
                    "type": "timestamptz",
                },
            ],
            "primaryKey": "o_orderkey",
        },
    ],
}


@pytest.fixture
def manifest_str():
    return base64.b64encode(orjson.dumps(manifest)).decode("utf-8")


with TestClient(app) as client:

    def test_query(manifest_str, connection_info):
        response = client.post(
            url=f"{base_url}/query",
            json={
                "connectionInfo": connection_info,
                "manifestStr": manifest_str,
                "sql": "SELECT * FROM wren.public.orders LIMIT 1",
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert len(result["columns"]) == len(manifest["models"][0]["columns"])
        assert len(result["data"]) == 1
        assert result["data"][0] == [
            "2024-01-01 23:59:59.000000",
            "2024-01-01 23:59:59.000000 UTC",
            "2024-01-16 04:00:00.000000 UTC",  # utc-5
            "2024-07-16 03:00:00.000000 UTC",  # utc-4
            "1_370",
            370,
            "1996-01-02",
            1,
            "O",
            "172799.49",
        ]
        assert result["dtypes"] == {
            "o_orderkey": "int32",
            "o_custkey": "int32",
            "o_orderstatus": "object",
            "o_totalprice": "object",
            "o_orderdate": "object",
            "order_cust_key": "object",
            "timestamp": "object",
            "timestamptz": "object",
            "dst_utc_minus_5": "object",
            "dst_utc_minus_4": "object",
        }

    def test_query_with_connection_url(manifest_str, connection_url):
        response = client.post(
            url=f"{base_url}/query",
            json={
                "connectionInfo": {"connectionUrl": connection_url},
                "manifestStr": manifest_str,
                "sql": "SELECT * FROM wren.public.orders LIMIT 1",
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert len(result["columns"]) == len(manifest["models"][0]["columns"])
        assert len(result["data"]) == 1
        assert result["data"][0][0] == "2024-01-01 23:59:59.000000"
        assert result["dtypes"] is not None

    def test_query_with_limit(manifest_str, connection_info):
        response = client.post(
            url=f"{base_url}/query",
            params={"limit": 1},
            json={
                "connectionInfo": connection_info,
                "manifestStr": manifest_str,
                "sql": "SELECT * FROM wren.public.orders",
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert len(result["data"]) == 1

        response = client.post(
            url=f"{base_url}/query",
            params={"limit": 1},
            json={
                "connectionInfo": connection_info,
                "manifestStr": manifest_str,
                "sql": "SELECT * FROM wren.public.orders LIMIT 10",
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert len(result["data"]) == 1

    def test_query_with_invalid_manifest_str(connection_info):
        response = client.post(
            url=f"{base_url}/query",
            json={
                "connectionInfo": connection_info,
                "manifestStr": "xxx",
                "sql": "SELECT * FROM wren.public.orders LIMIT 1",
            },
        )
        assert response.status_code == 422
        assert response.text == "Base64 decode error: Invalid padding"

    def test_query_without_manifest(connection_info):
        response = client.post(
            url=f"{base_url}/query",
            json={
                "connectionInfo": connection_info,
                "sql": "SELECT * FROM wren.public.orders LIMIT 1",
            },
        )
        assert response.status_code == 422
        result = response.json()
        assert result["detail"][0] is not None
        assert result["detail"][0]["type"] == "missing"
        assert result["detail"][0]["loc"] == ["body", "manifestStr"]
        assert result["detail"][0]["msg"] == "Field required"

    def test_query_without_sql(manifest_str, connection_info):
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
                "sql": "SELECT * FROM wren.public.orders LIMIT 1",
            },
        )
        assert response.status_code == 422
        result = response.json()
        assert result["detail"][0] is not None
        assert result["detail"][0]["type"] == "missing"
        assert result["detail"][0]["loc"] == ["body", "connectionInfo"]
        assert result["detail"][0]["msg"] == "Field required"

    def test_query_with_dry_run(manifest_str, connection_info):
        response = client.post(
            url=f"{base_url}/query",
            params={"dryRun": True},
            json={
                "connectionInfo": connection_info,
                "manifestStr": manifest_str,
                "sql": "SELECT * FROM wren.public.orders LIMIT 1",
            },
        )
        assert response.status_code == 204

    def test_query_with_dry_run_and_invalid_sql(manifest_str, connection_info):
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
        assert response.text is not None
