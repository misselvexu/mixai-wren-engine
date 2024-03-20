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

package io.accio.server.module;

import com.google.inject.Binder;
import com.google.inject.Scopes;
import io.accio.main.PreviewService;
import io.accio.main.pgcatalog.PgCatalogManager;
import io.accio.main.web.AccioExceptionMapper;
import io.accio.main.web.AnalysisResource;
import io.accio.main.web.CacheResource;
import io.accio.main.web.ConfigResource;
import io.accio.main.web.DuckDBResource;
import io.accio.main.web.LineageResource;
import io.accio.main.web.MDLResource;
import io.airlift.configuration.AbstractConfigurationAwareModule;

import static io.airlift.jaxrs.JaxrsBinder.jaxrsBinder;

public class WebModule
        extends AbstractConfigurationAwareModule
{
    @Override
    protected void setup(Binder binder)
    {
        jaxrsBinder(binder).bind(MDLResource.class);
        jaxrsBinder(binder).bind(LineageResource.class);
        jaxrsBinder(binder).bind(CacheResource.class);
        jaxrsBinder(binder).bind(AnalysisResource.class);
        jaxrsBinder(binder).bind(ConfigResource.class);
        jaxrsBinder(binder).bind(DuckDBResource.class);
        jaxrsBinder(binder).bindInstance(new AccioExceptionMapper());
        binder.bind(PreviewService.class).in(Scopes.SINGLETON);
        binder.bind(PgCatalogManager.class).in(Scopes.SINGLETON);
    }
}
