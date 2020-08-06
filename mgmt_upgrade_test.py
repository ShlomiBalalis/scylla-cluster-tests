import logging
from time import sleep

from sdcm.tester import ClusterTester
from sdcm.mgmt import get_scylla_manager_tool, TaskStatus, update_config_file
from mgmt_cli_test import BackupFunctionsMixIn


LOGGER = logging.getLogger(__name__)


class ManagerUpgradeTest(BackupFunctionsMixIn, ClusterTester):
    DESTINATION = '/tmp/backup'
    CLUSTER_NAME = "cluster_under_test"

    def create_simple_table(self, table_name, keyspace_name="ks1"):
        with self.cql_connection_patient(self.db_cluster.nodes[0]) as session:
            session.execute(f"""CREATE KEYSPACE IF NOT EXISTS {keyspace_name}
                WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': '3'}};""")
            session.execute(f"""CREATE table IF NOT EXISTS {keyspace_name}.{table_name} (
                                key varchar PRIMARY KEY,
                                c1 text,
                                c2 text);""")

    def write_multiple_rows(self, table_name, key_range, keyspace_name="ks1"):
        with self.cql_connection_patient(self.db_cluster.nodes[0]) as session:
            for num in range(*key_range):
                session.execute(f"insert into {keyspace_name}.{table_name} (key, c1, c2) "
                                f"VALUES ('k_{num}', 'v_{num}', 'v_{num}');")

    def _create_and_add_cluster(self):
        manager_node = self.monitors.nodes[0]
        manager_tool = get_scylla_manager_tool(manager_node=manager_node)
        self.update_all_agent_config_files()
        current_manager_version = manager_tool.version
        mgr_cluster = manager_tool.add_cluster(name=ManagerUpgradeTest.CLUSTER_NAME, db_cluster=self.db_cluster,
                                               auth_token=self.monitors.mgmt_auth_token)
        return mgr_cluster, current_manager_version

    def test_upgrade(self):  # pylint: disable=too-many-locals,too-many-statements
        target_upgrade_server_version = self.params.get('target_scylla_mgmt_server_repo')
        target_upgrade_agent_version = self.params.get('target_scylla_mgmt_agent_repo')
        manager_node = self.monitors.nodes[0]
        manager_tool = get_scylla_manager_tool(manager_node=manager_node)
        manager_tool.add_cluster(name="cluster_under_test", db_cluster=self.db_cluster,
                                 auth_token=self.monitors.mgmt_auth_token)
        current_manager_version = manager_tool.version
        LOGGER.debug("TRY VERSION")
        manager_tool.version

    def update_all_agent_config_files(self):
        config_file = '/etc/scylla-manager-agent/scylla-manager-agent.yaml'
        region_name = self.params.get('region_name').split()[0]
        for node in self.db_cluster.nodes:
            update_config_file(node=node, region=region_name, config_file=config_file)
        sleep(60)


def wait_until_task_finishes_return_details(task, wait=True, timeout=1000, step=10):
    if wait:
        task.wait_and_get_final_status(timeout=timeout, step=step)
    task_history = task.history
    latest_run_id = task.latest_run_id
    task_details = {"next run": task.next_run,
                    "latest run id": latest_run_id,
                    "start time": task.sctool.get_table_value(parsed_table=task_history, column_name="start time",
                                                              identifier=latest_run_id),
                    "end time": task.sctool.get_table_value(parsed_table=task_history, column_name="end time",
                                                            identifier=latest_run_id),
                    "duration": task.sctool.get_table_value(parsed_table=task_history, column_name="duration",
                                                            identifier=latest_run_id)}
    return task_details


def validate_previous_task_details(task, previous_task_details):
    """
    Compares the details of the task next run and history to the previously extracted next run and history
    """
    current_task_details = wait_until_task_finishes_return_details(task, wait=False)
    for detail_name in current_task_details:
        assert current_task_details[detail_name] == previous_task_details[detail_name],\
            f"previous task {detail_name} is not identical to the current history"


def upgrade_scylla_manager(pre_upgrade_manager_version, target_upgrade_server_version, target_upgrade_agent_version,
                           manager_node, db_cluster):
    LOGGER.debug("Stopping manager server")
    if manager_node.is_docker():
        manager_node.remoter.run('sudo supervisorctl stop scylla-manager')
    else:
        manager_node.remoter.run("sudo systemctl stop scylla-manager")

    LOGGER.debug("Stopping manager agents")
    for node in db_cluster.nodes:
        node.remoter.run("sudo systemctl stop scylla-manager-agent")

    LOGGER.debug("Upgrading manager server")
    manager_node.upgrade_mgmt(target_upgrade_server_version, start_manager_after_upgrade=False)

    LOGGER.debug("Upgrading and starting manager agents")
    for node in db_cluster.nodes:
        node.upgrade_manager_agent(target_upgrade_agent_version)

    LOGGER.debug("Starting manager server")
    if manager_node.is_docker():
        manager_node.remoter.run('sudo supervisorctl start scylla-manager')
    else:
        manager_node.remoter.run("sudo systemctl start scylla-manager")
    time_to_sleep = 30
    LOGGER.debug('Sleep {} seconds, waiting for manager service ready to respond'.format(time_to_sleep))
    sleep(time_to_sleep)

    LOGGER.debug("Comparing the new manager versions")
    manager_tool = get_scylla_manager_tool(manager_node=manager_node)
    new_manager_version = manager_tool.version
    assert new_manager_version != pre_upgrade_manager_version, "Manager failed to upgrade - " \
                                                               "previous and new versions are the same. Test failed!"
