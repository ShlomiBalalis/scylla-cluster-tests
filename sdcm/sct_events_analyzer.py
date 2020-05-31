import os
import sys
import threading
import signal
import logging

from sdcm.sct_events import EVENTS_PROCESSES, Severity, raise_event_on_failure
from sdcm.cluster import Setup

LOGGER = logging.getLogger(__name__)


class TestFailure(Exception):
    pass


class EventsAnalyzer(threading.Thread):

    def __init__(self):
        self.stop_event = threading.Event()
        super().__init__()

    @raise_event_on_failure
    def run(self):
        for event_class, message_data in EVENTS_PROCESSES['MainDevice'].subscribe_events(
                stop_event=self.stop_event):
            try:
                if event_class == 'TestResultEvent':
                    # don't send kill test cause of those event, test is already done when those are sent out
                    continue

                if event_class in ['CassandraStressEvent', 'ScyllaBenchEvent', 'YcsbStressEvent', 'NdbenchStressEvent'] \
                        and message_data.type == 'failure':
                    raise TestFailure(f"Stress Command failed: {message_data}")

                if message_data.severity == Severity.CRITICAL:
                    raise TestFailure(f"Got critical event: {message_data}")

            except TestFailure:
                self.kill_test(sys.exc_info())

            except Exception:  # pylint: disable=broad-except
                LOGGER.exception("analyzer logic failed")

    def terminate(self):
        self.stop_event.set()

    def kill_test(self, backtrace_with_reason):
        if not Setup.tester_obj():
            LOGGER.error("no test was register using 'Setup.set_tester_obj()', not killing")
            return
        test_pid = os.getpid()
        Setup.tester_obj().result.addFailure(Setup.tester_obj(), backtrace_with_reason)
        os.kill(test_pid, signal.SIGUSR2)
        self.terminate()
