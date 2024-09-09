use std::sync::Arc;

use datafusion::common::config::ConfigOptions;
use datafusion::common::tree_node::{Transformed, TransformedResult};
use datafusion::common::{plan_err, Result};
use datafusion::logical_expr::{
    col, ident, Aggregate, Distinct, DistinctOn, Extension, Projection, SubqueryAlias,
    UserDefinedLogicalNodeCore, Window,
};
use datafusion::logical_expr::{Expr, LogicalPlan, LogicalPlanBuilder};
use datafusion::optimizer::analyzer::AnalyzerRule;
use datafusion::sql::TableReference;

use crate::logical_plan::analyze::plan::{
    CalculationPlanNode, ModelPlanNode, ModelSourceNode, PartialModelPlanNode,
};
use crate::logical_plan::utils::create_remote_table_source;
use crate::mdl::manifest::Model;
use crate::mdl::utils::quoted;
use crate::mdl::AnalyzedWrenMDL;

/// [ModelGenerationRule] is responsible for generating the model plan node.
pub struct ModelGenerationRule {
    analyzed_wren_mdl: Arc<AnalyzedWrenMDL>,
}

impl ModelGenerationRule {
    pub fn new(mdl: Arc<AnalyzedWrenMDL>) -> Self {
        Self {
            analyzed_wren_mdl: mdl,
        }
    }

    pub(crate) fn generate_model_internal(
        &self,
        plan: LogicalPlan,
    ) -> Result<Transformed<LogicalPlan>> {
        match plan {
            LogicalPlan::Projection(Projection { expr, input, .. }) => {
                Ok(Transformed::yes(LogicalPlan::Projection(
                    Projection::try_new(expr, input)?,
                )))
            }
            LogicalPlan::SubqueryAlias(SubqueryAlias { input, alias, .. }) => {
                Ok(Transformed::yes(LogicalPlan::SubqueryAlias(
                    SubqueryAlias::try_new(input, alias)?,
                )))
            }
            LogicalPlan::Aggregate(Aggregate {
                input,
                group_expr,
                aggr_expr,
                ..
            }) => Ok(Transformed::yes(LogicalPlan::Aggregate(
                Aggregate::try_new(input, group_expr, aggr_expr)?,
            ))),
            LogicalPlan::Distinct(Distinct::On(DistinctOn {
                on_expr,
                select_expr,
                sort_expr,
                input,
                ..
            })) => Ok(Transformed::yes(LogicalPlan::Distinct(Distinct::On(
                DistinctOn::try_new(on_expr, select_expr, sort_expr, input)?,
            )))),
            LogicalPlan::Window(Window {
                input, window_expr, ..
            }) => Ok(Transformed::yes(LogicalPlan::Window(Window::try_new(
                window_expr,
                input,
            )?))),
            LogicalPlan::Extension(extension) => {
                if let Some(model_plan) =
                    extension.node.as_any().downcast_ref::<ModelPlanNode>()
                {
                    let source_plan = model_plan.relation_chain.clone().plan(
                        ModelGenerationRule::new(Arc::clone(&self.analyzed_wren_mdl)),
                    )?;
                    let result = match source_plan {
                        Some(plan) => {
                            if model_plan.required_exprs.is_empty() {
                                plan
                            } else {
                                LogicalPlanBuilder::from(plan)
                                    .project(model_plan.required_exprs.clone())?
                                    .build()?
                            }
                        }
                        _ => {
                            return plan_err!("Failed to generate source plan");
                        }
                    };
                    // calculated field scope
                    Ok(Transformed::yes(result))
                } else if let Some(model_plan) =
                    extension.node.as_any().downcast_ref::<ModelSourceNode>()
                {
                    let model: Arc<Model> = Arc::clone(
                        &self
                            .analyzed_wren_mdl
                            .wren_mdl()
                            .get_model(&model_plan.model_name)
                            .expect("Model not found"),
                    );
                    // support table reference
                    let table_scan = match &model_plan.original_table_scan {
                        Some(LogicalPlan::TableScan(original_scan)) => {
                            LogicalPlanBuilder::scan_with_filters(
                                TableReference::from(&model.table_reference),
                                create_remote_table_source(
                                    &model,
                                    &self.analyzed_wren_mdl.wren_mdl(),
                                ),
                                None,
                                original_scan.filters.clone(),
                            ).expect("Failed to create table scan")
                                .project(model_plan.required_exprs.clone())?
                                .build()
                        }
                        Some(_) => Err(datafusion::error::DataFusionError::Internal(
                            "ModelPlanNode should have a TableScan as original_table_scan"
                                .to_string(),
                        )),
                        None => {
                            LogicalPlanBuilder::scan(
                                TableReference::from(&model.table_reference),
                                create_remote_table_source(&model, &self.analyzed_wren_mdl.wren_mdl()),
                                None,
                            ).expect("Failed to create table scan")
                                .project(model_plan.required_exprs.clone())?
                                .build()
                        },
                    }?;

                    // it could be count(*) query
                    if model_plan.required_exprs.is_empty() {
                        return Ok(Transformed::no(table_scan));
                    }
                    let result = LogicalPlanBuilder::from(table_scan)
                        .alias(quoted(model.name()))?
                        .build()?;
                    Ok(Transformed::yes(result))
                } else if let Some(calculation_plan) = extension
                    .node
                    .as_any()
                    .downcast_ref::<CalculationPlanNode>(
                ) {
                    let source_plan = calculation_plan.relation_chain.clone().plan(
                        ModelGenerationRule::new(Arc::clone(&self.analyzed_wren_mdl)),
                    )?;

                    if let Expr::Alias(alias) = calculation_plan.measures[0].clone() {
                        let measure: Expr = *alias.expr.clone();
                        let name = alias.name.clone();
                        let ident = ident(measure.to_string()).alias(name);
                        let project = vec![calculation_plan.dimensions[0].clone(), ident];
                        let result = match source_plan {
                            Some(plan) => LogicalPlanBuilder::from(plan)
                                .aggregate(
                                    calculation_plan.dimensions.clone(),
                                    vec![measure],
                                )?
                                .project(project)?
                                .build()?,
                            _ => {
                                return plan_err!("Failed to generate source plan");
                            }
                        };
                        let alias = LogicalPlanBuilder::from(result)
                            .alias(quoted(calculation_plan.calculation.column.name()))?
                            .build()?;
                        Ok(Transformed::yes(alias))
                    } else {
                        return plan_err!("measures should have an alias");
                    }
                } else if let Some(partial_model) = extension
                    .node
                    .as_any()
                    .downcast_ref::<PartialModelPlanNode>(
                ) {
                    let plan = LogicalPlan::Extension(Extension {
                        node: Arc::new(partial_model.model_node.clone()),
                    });

                    let subquery = LogicalPlanBuilder::from(plan)
                        .alias(quoted(partial_model.model_node.plan_name()))?
                        .build()?;
                    let source_plan = self.generate_model_internal(subquery)?.data;
                    let projection: Vec<_> = partial_model
                        .schema()
                        .fields()
                        .iter()
                        .map(|f| col(datafusion::common::Column::from((None, f))))
                        .collect();
                    let alias = LogicalPlanBuilder::from(source_plan)
                        .project(projection)?
                        .alias(quoted(&partial_model.model_node.plan_name))?
                        .build()?;
                    Ok(Transformed::yes(alias))
                } else {
                    Ok(Transformed::no(LogicalPlan::Extension(extension)))
                }
            }
            _ => Ok(Transformed::no(plan)),
        }
    }
}

impl AnalyzerRule for ModelGenerationRule {
    fn analyze(&self, plan: LogicalPlan, _: &ConfigOptions) -> Result<LogicalPlan> {
        let transformed_up = plan
            .transform_up_with_subqueries(&|plan| -> Result<Transformed<LogicalPlan>> {
                self.generate_model_internal(plan)
            })
            .data()?;
        transformed_up
            .transform_down_with_subqueries(
                &|plan| -> Result<Transformed<LogicalPlan>> {
                    self.generate_model_internal(plan)
                },
            )?
            .map_data(|plan| plan.recompute_schema())
            .data()
    }

    fn name(&self) -> &str {
        "ModelGenerationRule"
    }
}
