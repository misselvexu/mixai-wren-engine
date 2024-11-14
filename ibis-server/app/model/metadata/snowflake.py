from contextlib import closing

import ibis

from app.model import SnowflakeConnectionInfo
from app.model.data_source import DataSource
from app.model.metadata.dto import (
    Column,
    Constraint,
    ConstraintType,
    Table,
    TableProperties,
    WrenEngineColumnType,
)
from app.model.metadata.metadata import Metadata


class SnowflakeMetadata(Metadata):
    def __init__(self, connection_info: SnowflakeConnectionInfo):
        super().__init__(connection_info)
        self.connection = DataSource.snowflake.get_connection(connection_info)

    def get_table_list(self) -> list[Table]:
        schema = self._get_schema_name()
        sql = f"""
            SELECT
                c.TABLE_CATALOG AS TABLE_CATALOG,
                c.TABLE_SCHEMA AS TABLE_SCHEMA,
                c.TABLE_NAME AS TABLE_NAME,
                c.COLUMN_NAME AS COLUMN_NAME,
                c.DATA_TYPE AS DATA_TYPE,
                c.IS_NULLABLE AS IS_NULLABLE,
                c.COMMENT AS COLUMN_COMMENT,
                t.COMMENT AS TABLE_COMMENT
            FROM
                INFORMATION_SCHEMA.COLUMNS c
            JOIN
                INFORMATION_SCHEMA.TABLES t
                ON c.TABLE_SCHEMA = t.TABLE_SCHEMA
                AND c.TABLE_NAME = t.TABLE_NAME
            WHERE
                c.TABLE_SCHEMA = '{schema}';
        """
        response = self.connection.sql(sql).to_pandas().to_dict(orient="records")

        unique_tables = {}
        for row in response:
            # generate unique table name
            schema_table = self._format_compact_table_name(
                row["TABLE_SCHEMA"], row["TABLE_NAME"]
            )
            # init table if not exists
            if schema_table not in unique_tables:
                unique_tables[schema_table] = Table(
                    name=schema_table,
                    description=row["TABLE_COMMENT"],
                    columns=[],
                    properties=TableProperties(
                        schema=row["TABLE_SCHEMA"],
                        catalog=row["TABLE_CATALOG"],
                        table=row["TABLE_NAME"],
                    ),
                    primaryKey="",
                )

            # table exists, and add column to the table
            unique_tables[schema_table].columns.append(
                Column(
                    name=row["COLUMN_NAME"],
                    type=self._transform_column_type(row["DATA_TYPE"]),
                    notNull=row["IS_NULLABLE"].lower() == "no",
                    description=row["COLUMN_COMMENT"],
                    properties=None,
                )
            )
        return list(unique_tables.values())

    def get_constraints(self) -> list[Constraint]:
        database = self._get_database_name()
        schema = self._get_schema_name()
        sql = f"""
            SHOW IMPORTED KEYS IN SCHEMA {database}.{schema};
        """
        with closing(self.connection.raw_sql(sql)) as cur:
            fields = [field[0] for field in cur.description]
            result = [dict(zip(fields, row)) for row in cur.fetchall()]
            res = (
                ibis.memtable(result).to_pandas().to_dict(orient="records")
                if len(result) > 0
                else []
            )
            constraints = []
            for row in res:
                constraints.append(
                    Constraint(
                        constraintName=self._format_constraint_name(
                            row["pk_table_name"],
                            row["pk_column_name"],
                            row["fk_table_name"],
                            row["fk_column_name"],
                        ),
                        constraintTable=self._format_compact_table_name(
                            row["pk_schema_name"], row["pk_table_name"]
                        ),
                        constraintColumn=row["pk_column_name"],
                        constraintedTable=self._format_compact_table_name(
                            row["fk_schema_name"], row["fk_table_name"]
                        ),
                        constraintedColumn=row["fk_column_name"],
                        constraintType=ConstraintType.FOREIGN_KEY,
                    )
                )
            return constraints

    def get_version(self) -> str:
        return self.connection.sql("SELECT CURRENT_VERSION()").to_pandas().iloc[0, 0]

    def _get_database_name(self):
        return self.connection_info.database.get_secret_value()

    def _get_schema_name(self):
        return self.connection_info.sf_schema.get_secret_value()

    def _format_compact_table_name(self, schema: str, table: str):
        return f"{schema}.{table}"

    def _format_constraint_name(
        self, table_name, column_name, referenced_table_name, referenced_column_name
    ):
        return f"{table_name}_{column_name}_{referenced_table_name}_{referenced_column_name}"

    def _transform_column_type(self, data_type):
        # all possible types listed here: https://docs.snowflake.com/en/sql-reference/intro-summary-data-types
        switcher = {
            # Numeric Types
            "number": WrenEngineColumnType.NUMERIC,
            "decimal": WrenEngineColumnType.NUMERIC,
            "numeric": WrenEngineColumnType.NUMERIC,
            "int": WrenEngineColumnType.INTEGER,
            "integer": WrenEngineColumnType.INTEGER,
            "bigint": WrenEngineColumnType.BIGINT,
            "smallint": WrenEngineColumnType.SMALLINT,
            "tinyint": WrenEngineColumnType.TINYINT,
            "byteint": WrenEngineColumnType.TINYINT,
            # Float
            "float4": WrenEngineColumnType.FLOAT4,
            "float": WrenEngineColumnType.FLOAT8,
            "float8": WrenEngineColumnType.FLOAT8,
            "double": WrenEngineColumnType.DOUBLE,
            "double precision": WrenEngineColumnType.DOUBLE,
            "real": WrenEngineColumnType.REAL,
            # String Types
            "varchar": WrenEngineColumnType.VARCHAR,
            "char": WrenEngineColumnType.CHAR,
            "character": WrenEngineColumnType.CHAR,
            "string": WrenEngineColumnType.STRING,
            "text": WrenEngineColumnType.TEXT,
            # Boolean
            "boolean": WrenEngineColumnType.BOOLEAN,
            # Date and Time Types
            "date": WrenEngineColumnType.DATE,
            "datetime": WrenEngineColumnType.TIMESTAMP,
            "timestamp": WrenEngineColumnType.TIMESTAMP,
            "timestamp_ntz": WrenEngineColumnType.TIMESTAMP,
            "timestamp_tz": WrenEngineColumnType.TIMESTAMPTZ,
        }

        return switcher.get(data_type.lower(), WrenEngineColumnType.UNKNOWN)
