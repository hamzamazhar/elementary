import pytest
import os
import shutil
import json
from unittest import mock
from datetime import datetime

from monitor.alerts import Alert
from snowflake.connector.connection import SnowflakeConnection, SnowflakeCursor
from monitor.dbt_runner import DbtRunner
from config.config import Config
from monitor.data_monitoring import SnowflakeDataMonitoring, DataMonitoring

WEBHOOK_URL = 'https://my_webhook'
ALERT_ROW = ['123', datetime.now(), 'db', 'sc', 't1', 'c1', 'schema_change', 'column_added', 'Column was added']


@pytest.fixture
def snowflake_con_mock():
    snowflake_con = mock.create_autospec(SnowflakeConnection)
    snowflake_cur = mock.create_autospec(SnowflakeCursor)
    # Cursor is a context manager so we need to mock the function __enter__
    snowflake_con.cursor.return_value.__enter__.return_value = snowflake_cur
    return snowflake_con


@pytest.fixture
def config_mock():
    config_mock = mock.create_autospec(Config)
    config_mock.profiles_dir = 'profiles_dir_path'
    config_mock.slack_notification_webhook = WEBHOOK_URL
    config_mock.is_slack_workflow = False
    config_mock.monitoring_configuration_in_dbt_sources_to_csv.return_value = None
    return config_mock

@pytest.fixture
def slack_workflows_config_mock():
    config_mock = mock.create_autospec(Config)
    config_mock.profiles_dir = 'profiles_dir_path'
    config_mock.slack_notification_webhook = WEBHOOK_URL
    config_mock.is_slack_workflow = True
    config_mock.monitoring_configuration_in_dbt_sources_to_csv.return_value = None
    return config_mock

@pytest.fixture
def dbt_runner_mock():
    return mock.create_autospec(DbtRunner)


@pytest.fixture
def snowflake_data_monitoring_with_empty_config_in_db(config_mock, snowflake_con_mock, dbt_runner_mock):
    # This mock cursor returns empty list to simulate empty configuration
    snowflake_cursor_context_manager_return_value = snowflake_con_mock.cursor.return_value.__enter__.return_value
    snowflake_cursor_context_manager_return_value.fetchall.return_value = []

    snowflake_data_mon = SnowflakeDataMonitoring(config_mock, snowflake_con_mock)
    snowflake_data_mon.dbt_runner = dbt_runner_mock
    snowflake_data_mon._dbt_package_exists = lambda: True
    return snowflake_data_mon


def create_snowflake_data_mon(config_mock, snowflake_con_mock, dbt_runner_mock):
    # This cursor mock will use the side effect to return non empty configuration
    snowflake_cursor_context_manager_return_value = snowflake_con_mock.cursor.return_value.__enter__.return_value

    def execute_query_side_effect(*args, **kwargs):
        if 'count(*)' in args[0].lower():
            snowflake_cursor_context_manager_return_value.fetchall.return_value = [[1]]
        else:
            snowflake_cursor_context_manager_return_value.fetchall.return_value = []

    snowflake_cursor_context_manager_return_value.execute.side_effect = execute_query_side_effect

    snowflake_data_mon = SnowflakeDataMonitoring(config_mock, snowflake_con_mock)
    snowflake_data_mon.dbt_runner = dbt_runner_mock
    return snowflake_data_mon    


@pytest.fixture
def snowflake_data_monitoring(config_mock, snowflake_con_mock, dbt_runner_mock):
    return create_snowflake_data_mon(config_mock, snowflake_con_mock, dbt_runner_mock)


@pytest.fixture
def snowflake_data_monitoring_slack_workflow(slack_workflows_config_mock, snowflake_con_mock, dbt_runner_mock):
    return create_snowflake_data_mon(slack_workflows_config_mock, snowflake_con_mock, dbt_runner_mock)


@pytest.fixture
def snowflake_data_monitoring_with_alerts_in_db(config_mock, snowflake_con_mock, dbt_runner_mock):
    snowflake_cursor_context_manager_return_value = snowflake_con_mock.cursor.return_value.__enter__.return_value

    def execute_query_side_effect(*args, **kwargs):
        if args[0] == DataMonitoring.SELECT_NEW_ALERTS_QUERY:
            snowflake_cursor_context_manager_return_value.fetchall.return_value = [ALERT_ROW]
        else:
            snowflake_cursor_context_manager_return_value.fetchall.return_value = []

    snowflake_cursor_context_manager_return_value.execute.side_effect = execute_query_side_effect

    snowflake_data_mon = SnowflakeDataMonitoring(config_mock, snowflake_con_mock)
    snowflake_data_mon.dbt_runner = dbt_runner_mock
    return snowflake_data_mon


def delete_dbt_package(data_monitoring):
    if os.path.exists(data_monitoring.DBT_PROJECT_MODULES_PATH):
        shutil.rmtree(data_monitoring.DBT_PROJECT_MODULES_PATH)

    if os.path.exists(data_monitoring.DBT_PROJECT_PACKAGES_PATH):
        shutil.rmtree(data_monitoring.DBT_PROJECT_PACKAGES_PATH)



@pytest.mark.parametrize("full_refresh, update_dbt_package, dbt_package_exists", [
    (True, True, False),
    (True, False, False),
    (True, True, False),
    (True, False, False),
    (True, True, True),
    (True, False, True),
    (True, True, True),
    (True, False, True),
    (False, True, False),
    (False, False, False),
    (False, True, False),
    (False, False, False),
    (False, True, True),
    (False, False, True),
    (False, True, True),
    (False, False, True),
])
def test_data_monitoring_run(full_refresh, update_dbt_package, dbt_package_exists, snowflake_data_monitoring):
    delete_dbt_package(snowflake_data_monitoring)
    snowflake_data_monitoring._dbt_package_exists = lambda: dbt_package_exists
    dbt_runner_mock = snowflake_data_monitoring.dbt_runner

    # The test function
    snowflake_data_monitoring.run(dbt_full_refresh=full_refresh, force_update_dbt_package=update_dbt_package)

    if update_dbt_package or not dbt_package_exists:
        dbt_runner_mock.deps.assert_called()
    else:
        dbt_runner_mock.deps.assert_not_called()

    dbt_runner_mock.run.assert_called_with(select=snowflake_data_monitoring.DBT_PACKAGE_NAME, full_refresh=full_refresh)


@mock.patch('requests.post')
def test_data_monitoring_send_alert_to_slack(requests_post_mock, snowflake_data_monitoring):
    alert = Alert.create_alert_from_row(ALERT_ROW)
    # The test function
    snowflake_data_monitoring._send_to_slack([alert])
    requests_post_mock.assert_called_once_with(url=WEBHOOK_URL, headers={'Content-type': 'application/json'},
                                               data=json.dumps(alert.to_slack_message()))

@mock.patch('requests.post')
def test_data_monitoring_send_alert_to_slack_workflows(requests_post_mock, snowflake_data_monitoring_slack_workflow):
    alert = Alert.create_alert_from_row(ALERT_ROW)
    snowflake_data_monitoring_slack_workflow._send_to_slack([alert])
    requests_post_mock.assert_called_once_with(url=WEBHOOK_URL, headers={'Content-type': 'application/json'},
                                               data=json.dumps(alert.to_slack_workflows_message()))

def test_data_monitoring_send_alerts(snowflake_data_monitoring_with_alerts_in_db):
    snowflake_data_monitoring = snowflake_data_monitoring_with_alerts_in_db
    alerts = snowflake_data_monitoring._query_alerts()
    expected_alerts = [Alert.create_alert_from_row(ALERT_ROW)]
    assert len(alerts) == len(expected_alerts)
    assert alerts[0].id == expected_alerts[0].id
    assert type(alerts[0]) == type(expected_alerts[0])

