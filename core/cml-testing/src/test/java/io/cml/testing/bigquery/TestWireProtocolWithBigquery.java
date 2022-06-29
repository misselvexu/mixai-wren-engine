/*
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package io.cml.testing.bigquery;

import com.google.common.collect.ImmutableList;
import com.google.common.collect.ImmutableMap;
import io.cml.spi.type.PGType;
import io.cml.spi.type.PGTypes;
import io.cml.testing.AbstractWireProtocolTest;
import io.cml.testing.TestingWireProtocolClient;
import io.cml.testing.TestingWireProtocolServer;
import io.cml.wireprotocol.PostgresWireProtocol;
import org.assertj.core.api.AssertionsForClassTypes;
import org.testng.annotations.Test;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import static com.google.common.collect.ImmutableList.toImmutableList;
import static io.cml.spi.type.IntegerType.INTEGER;
import static io.cml.spi.type.VarcharType.VARCHAR;
import static io.cml.testing.TestingWireProtocolClient.DescribeType.PORTAL;
import static io.cml.testing.TestingWireProtocolClient.DescribeType.STATEMENT;
import static io.cml.testing.TestingWireProtocolClient.Parameter.textParameter;
import static java.lang.System.getenv;
import static org.assertj.core.api.Assertions.assertThat;

public class TestWireProtocolWithBigquery
        extends AbstractWireProtocolTest
{
    public static final String MOCK_PASSWORD = "ignored";

    @Override
    protected TestingWireProtocolServer createWireProtocolServer()
    {
        return TestingWireProtocolServer.builder()
                .setRequiredConfigs(
                        ImmutableMap.<String, String>builder()
                                .put("bigquery.project-id", getenv("TEST_BIG_QUERY_PROJECT_ID"))
                                .put("bigquery.location", "US")
                                .put("bigquery.credentials-key", getenv("TEST_BIG_QUERY_CREDENTIALS_BASE64_JSON"))
                                .build())
                .build();
    }

    @Test(enabled = false)
    public void testSimpleQuery()
            throws IOException
    {
        try (TestingWireProtocolClient protocolClient = wireProtocolClient()) {
            protocolClient.sendStartUpMessage(196608, MOCK_PASSWORD, "test", "canner");

            protocolClient.assertAuthOk();
            assertDefaultPgConfigResponse(protocolClient);
            protocolClient.assertReadyForQuery('I');

            protocolClient.sendSimpleQuery("select * from (values ('rows1', 10), ('rows2', 10), ('rows3', 10)) as t(col1, col2) where col2 = 10");

            List<TestingWireProtocolClient.Field> fields = protocolClient.assertAndGetRowDescriptionFields();
            List<PGType<?>> types = fields.stream().map(TestingWireProtocolClient.Field::getTypeId).map(PGTypes::oidToPgType).collect(Collectors.toList());
            assertThat(types).isEqualTo(ImmutableList.of(VARCHAR, INTEGER));

            protocolClient.assertDataRow("rows1,10");
            protocolClient.assertDataRow("rows2,10");
            protocolClient.assertDataRow("rows3,10");
            protocolClient.assertCommandComplete("SELECT 3");
            protocolClient.assertReadyForQuery('I');
        }
    }

    @Test
    public void testExtendedQuery()
            throws IOException
    {
        try (TestingWireProtocolClient protocolClient = wireProtocolClient()) {
            protocolClient.sendStartUpMessage(196608, MOCK_PASSWORD, "test", "canner");
            protocolClient.assertAuthOk();
            assertDefaultPgConfigResponse(protocolClient);
            protocolClient.assertReadyForQuery('I');

            List<PGType> paramTypes = ImmutableList.of(INTEGER);
            protocolClient.sendParse("teststmt", "select * from (values ('rows1', 10), ('rows2', 10)) as t(col1, col2) where col2 = ?",
                    paramTypes.stream().map(PGType::oid).collect(toImmutableList()));
            protocolClient.sendDescribe(TestingWireProtocolClient.DescribeType.STATEMENT, "teststmt");
            protocolClient.sendBind("exec1", "teststmt", ImmutableList.of(textParameter(10, INTEGER)));
            protocolClient.sendDescribe(TestingWireProtocolClient.DescribeType.PORTAL, "exec1");
            protocolClient.sendExecute("exec1", 0);
            protocolClient.sendSync();

            protocolClient.assertParseComplete();

            List<PGType<?>> actualParamTypes = protocolClient.assertAndGetParameterDescription();
            AssertionsForClassTypes.assertThat(actualParamTypes).isEqualTo(paramTypes);

            List<TestingWireProtocolClient.Field> fields = protocolClient.assertAndGetRowDescriptionFields();
            List<PGType> actualTypes = fields.stream().map(TestingWireProtocolClient.Field::getTypeId).map(PGTypes::oidToPgType).collect(toImmutableList());
            AssertionsForClassTypes.assertThat(actualTypes).isEqualTo(ImmutableList.of(VARCHAR, INTEGER));

            protocolClient.assertBindComplete();

            List<TestingWireProtocolClient.Field> fields2 = protocolClient.assertAndGetRowDescriptionFields();
            List<PGType> actualTypes2 = fields2.stream().map(TestingWireProtocolClient.Field::getTypeId).map(PGTypes::oidToPgType).collect(toImmutableList());
            AssertionsForClassTypes.assertThat(actualTypes2).isEqualTo(ImmutableList.of(VARCHAR, INTEGER));

            protocolClient.assertDataRow("rows1,10");
            protocolClient.assertDataRow("rows2,10");
            protocolClient.assertCommandComplete("SELECT 2");
            protocolClient.assertReadyForQuery('I');
        }
    }

    @Test
    public void testNullExtendedQuery()
            throws IOException
    {
        try (TestingWireProtocolClient protocolClient = wireProtocolClient()) {
            protocolClient.sendStartUpMessage(196608, MOCK_PASSWORD, "test", "canner");
            protocolClient.assertAuthOk();
            assertDefaultPgConfigResponse(protocolClient);
            protocolClient.assertReadyForQuery('I');
            protocolClient.sendNullParse("");
            protocolClient.assertErrorMessage("query can't be null");
        }
    }

    @Test
    public void testNotExistOid()
            throws IOException
    {
        try (TestingWireProtocolClient protocolClient = wireProtocolClient()) {
            protocolClient.sendStartUpMessage(196608, MOCK_PASSWORD, "test", "canner");
            protocolClient.assertAuthOk();
            assertDefaultPgConfigResponse(protocolClient);
            protocolClient.assertReadyForQuery('I');
            protocolClient.sendParse("teststmt", "select * from (values ('rows1', 10), ('rows2', 20)) as t(col1, col2) where col2 = ?",
                    ImmutableList.of(999));
            protocolClient.assertErrorMessage("No oid mapping from '999' to pg_type");

            protocolClient.sendBind("exec1", "teststmt", ImmutableList.of(textParameter("10", INTEGER)));
            protocolClient.assertErrorMessage("prepared statement teststmt not found");
        }
    }

    @Test
    public void testDescribeEmptyStatement()
            throws IOException
    {
        try (TestingWireProtocolClient protocolClient = wireProtocolClient()) {
            protocolClient.sendStartUpMessage(196608, MOCK_PASSWORD, "test", "canner");
            protocolClient.assertAuthOk();
            assertDefaultPgConfigResponse(protocolClient);
            protocolClient.assertReadyForQuery('I');
            protocolClient.sendParse("teststmt", "", ImmutableList.of());
            protocolClient.sendDescribe(STATEMENT, "teststmt");
            protocolClient.sendBind("exec1", "teststmt", ImmutableList.of());
            protocolClient.sendDescribe(PORTAL, "exec1");
            protocolClient.sendSync();

            protocolClient.assertParseComplete();
            List<PGType<?>> fields = protocolClient.assertAndGetParameterDescription();
            AssertionsForClassTypes.assertThat(fields.size()).isZero();
            protocolClient.assertNoData();

            protocolClient.assertBindComplete();
            protocolClient.assertNoData();

            protocolClient.assertReadyForQuery('I');
        }
    }

    // TODO: support suspendable result set
    @Test(enabled = false)
    public void testExtendedQueryWithMaxRow()
            throws IOException
    {
        try (TestingWireProtocolClient protocolClient = wireProtocolClient()) {
            protocolClient.sendStartUpMessage(196608, MOCK_PASSWORD, "test", "canner");

            protocolClient.assertAuthOk();
            assertDefaultPgConfigResponse(protocolClient);
            protocolClient.assertReadyForQuery('I');
            List<PGType<?>> paramTypes = ImmutableList.of(INTEGER);
            protocolClient.sendParse("teststmt", "select * from (values ('rows1', 10), ('rows2', 10)) as t(col1, col2) where col2 = ?",
                    paramTypes.stream().map(PGType::oid).collect(toImmutableList()));
            protocolClient.sendBind("exec1", "teststmt", ImmutableList.of(textParameter(10, INTEGER)));
            protocolClient.sendDescribe(PORTAL, "exec1");
            protocolClient.sendExecute("exec1", 1);
            protocolClient.sendSync();

            protocolClient.assertParseComplete();
            protocolClient.assertBindComplete();

            List<TestingWireProtocolClient.Field> fields = protocolClient.assertAndGetRowDescriptionFields();
            List<PGType<?>> actualTypes = fields.stream().map(TestingWireProtocolClient.Field::getTypeId).map(PGTypes::oidToPgType).collect(toImmutableList());
            AssertionsForClassTypes.assertThat(actualTypes).isEqualTo(ImmutableList.of(VARCHAR, INTEGER));

            protocolClient.assertDataRow("rows1,10");
            protocolClient.assertPortalPortalSuspended();
            protocolClient.assertReadyForQuery('I');

            protocolClient.sendExecute("exec1", 1);
            protocolClient.sendSync();

            protocolClient.assertDataRow("rows2,10");
            protocolClient.assertCommandComplete("SELECT 2");
            protocolClient.assertReadyForQuery('I');
        }
    }

    protected static void assertDefaultPgConfigResponse(TestingWireProtocolClient protocolClient)
            throws IOException
    {
        for (Map.Entry<String, String> config : PostgresWireProtocol.DEFAULT_PG_CONFIGS.entrySet()) {
            protocolClient.assertParameterStatus(config.getKey(), config.getValue());
        }
    }
}
