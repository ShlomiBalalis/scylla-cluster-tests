import yaml

from sdcm.utils.version_utils import ComparableScyllaVersion
from sdcm.sct_events import Severity
from sdcm.sct_events.system import PerftuneResultEvent


PERFTUNE_LOCATION = "/opt/scylladb/scripts/perftune.py"
# instance_type_size = {
#     "": ""
# }
# Should be flexible


# def get_ram_size(node) -> int:
#     # Size in KB
#     result = node.remoter.run("grep MemTotal /proc/meminfo | awk '{print $2}'")
#     ram_size = int(result.stdout)
#     return ram_size


def get_number_of_cpu_cores(node) -> int:
    result = node.remoter.run("grep -c ^processor /proc/cpuinfo")
    cores_num = int(result.stdout)
    return cores_num


class PerftuneExpectedResult:
    def __init__(self, number_of_cpu_cores, nic_name, scylla_version, is_enterprise):
        self.number_of_cpu_cores = number_of_cpu_cores
        self.nic_name = nic_name
        self.comparable_scylla_version = ComparableScyllaVersion(scylla_version)
        self.is_enterprise = is_enterprise

    def get_expected_cpu_mask(self) -> str:
        if self.number_of_cpu_cores <= 4:
            return "0x0000000f"
        elif 5 <= self.number_of_cpu_cores <= 8:
            return "0x0000003e"
        elif 9 <= self.number_of_cpu_cores <= 32:
            return "0x00000fbe"
        elif self.number_of_cpu_cores == 48:
            return "0x0000ffef,0xfeffeffe"
        elif self.number_of_cpu_cores == 64:
            return "0xfffefffe,0xfffefffe"
        elif self.number_of_cpu_cores == 96:
            return "0xfffffcff,0xfffcffff,0xfcfffffc"
        raise ValueError(f"Unrecognized number of CPUs: {self.number_of_cpu_cores}")

    def get_expected_irq_cpu_mask(self) -> str:  # Only if the command available:
        # "only for the perftune.py that has “perftune.py: introduce --get-irq-cpu-mask command line parameter”"
        if self.number_of_cpu_cores <= 4:
            return "0x0000000f"
        elif 5 <= self.number_of_cpu_cores <= 8:
            return "0x00000001"
        elif 9 <= self.number_of_cpu_cores <= 32:
            return "0x00000041"
        elif self.number_of_cpu_cores == 48:
            return "0x00000010,0x01001001"
        elif self.number_of_cpu_cores == 64:
            return "0x00010001,0x00010001"
        elif self.number_of_cpu_cores == 96:
            return "0x00000300,0x00030000,0x03000003"
        raise ValueError(f"Unrecognized number of CPUs: {self.number_of_cpu_cores}")

    def get_expected_options_file_contents(self) -> dict:
        base_result_dict = {"cpu_mask": self.get_expected_cpu_mask(),
                            "tune": ["net"]}
        if (self.is_enterprise and self.comparable_scylla_version >= "2022.2.7)")\
                or self.comparable_scylla_version >= "5.2":
            attach_values = {"irq_core_auto_detection_ratio": 16,
                             "irq_cpu_mask": self.get_expected_irq_cpu_mask(),
                             "nic": [self.nic_name],
                             }
        elif (self.is_enterprise and self.comparable_scylla_version >= "2022.1")\
                or self.comparable_scylla_version >= "5.0":
            attach_values = {"mode": "mq",
                             "nic": [self.nic_name],
                             }
        elif (self.is_enterprise and self.comparable_scylla_version >= "2021.1")\
                or self.comparable_scylla_version >= "4.6":
            attach_values = {"mode": "mq",
                             "nic": self.nic_name,
                             }
        else:
            raise ValueError(f"Unfamiliar scylla version: {self.comparable_scylla_version}")
        base_result_dict.update(attach_values)
        return base_result_dict


class PerftuneExecutor:
    def __init__(self, remoter, nic_name):
        self.remoter = remoter
        self.nic_name = nic_name

    def get_cpu_mask(self) -> str:
        result = self.remoter.run(f"{PERFTUNE_LOCATION} --tune net --nic {self.nic_name} --get-cpu-mask")
        return result.stdout.strip()

    def get_irq_cpu_mask(self) -> str:
        result = self.remoter.run(f"{PERFTUNE_LOCATION} --tune net --nic {self.nic_name} --get-irq-cpu-mask")
        return result.stdout.strip()

    def get_options_file_contents(self) -> dict:  # , file_path=None
        result = self.remoter.run(f"{PERFTUNE_LOCATION} --tune net --nic {self.nic_name} –mode mq --dump-options-file")
        result_as_yaml = yaml.safe_load(result.stdout)
        return result_as_yaml


class PerftuneOutputChecker:  # pylint: disable=too-few-public-methods
    def __init__(self, node):
        self.node = node
        nic_name = node.get_nic_devices()[0]
        self.executor = PerftuneExecutor(node.remoter, nic_name)
        self.expected_result = PerftuneExpectedResult(
            get_number_of_cpu_cores(node=node), nic_name, node.scylla_version, node.is_enterprise)

    def compare_perftune_results(self) -> None:
        PerftuneResultEvent(
            message="Checking the output of perftune.py",
            severity=Severity.NORMAL).publish()
        try:
            cpu_mask = self.executor.get_cpu_mask()
            if cpu_mask != self.expected_result.get_expected_cpu_mask():
                PerftuneResultEvent(
                    message=f"Mismatched results when testing the output of the 'get-cpu-mask' command on {self.node}"
                            f"\nActual result: '{cpu_mask}'"
                            f"\nExpected output: '{self.expected_result.get_expected_cpu_mask()}'",
                    severity=Severity.ERROR).publish()
            irq_cpu_mask = self.executor.get_irq_cpu_mask()
            if irq_cpu_mask != self.expected_result.get_expected_irq_cpu_mask():
                PerftuneResultEvent(
                    message=f"Mismatched results when testing the output of the 'get-irq-cpu-mask' command on "
                            f"{self.node}"
                            f"\nActual result: '{irq_cpu_mask}'"
                            f"\nExpected output: '{self.expected_result.get_expected_irq_cpu_mask()}'",
                    severity=Severity.ERROR).publish()
            option_file_dict = self.executor.get_options_file_contents()
            if option_file_dict != self.expected_result.get_expected_options_file_contents():
                PerftuneResultEvent(
                    message=f"Mismatched results when testing the output of the 'dump-options-file' command on "
                            f"{self.node}"
                            f"\nActual result: '{option_file_dict}'"
                            f"\nExpected output: '{self.expected_result.get_expected_options_file_contents()}'",
                    severity=Severity.ERROR).publish()
        except Exception as error:  # pylint: disable=broad-except
            PerftuneResultEvent(
                message=f"Unexpected error when verifying the output of Perftune: {error}",
                severity=Severity.ERROR).publish()
