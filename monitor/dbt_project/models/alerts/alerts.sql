{{
  config(
    materialized = 'incremental',
    unique_key = 'alert_id',
    merge_update_columns = ['alert_id'],
    on_schema_change = 'append_new_columns'
  )
}}

{% set anomaly_detection_relation = adapter.get_relation(this.database, this.schema, 'alerts_anomaly_detection') %}
// Backwards compatibility support for a renamed model.
{% set data_monitoring_relation = adapter.get_relation(this.database, this.schema, 'alerts_data_monitoring') %}

with failed_tests as (
     select * from {{ ref('elementary', 'alerts_schema_changes') }}
     union all
     select * from {{ ref('elementary', 'alerts_dbt_tests') }}

    {% if anomaly_detection_relation %}
        union all
        select * from {{ anomaly_detection_relation }}
    {% endif %}

    {% if data_monitoring_relation %}
        union all
        select * from {{ data_monitoring_relation }}
    {% endif %}
)

select *, false as alert_sent from failed_tests

{%- if is_incremental() %}
    where {{ get_new_alerts_where_clause(this) }}
{%- endif %}
