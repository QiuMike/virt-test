import logging
import time
from autotest.client.shared import error
from virttest import guest_agent
from virttest import utils_misc
from virttest import aexpect


class BaseVirtTest(object):
    def __init__(self, test, params, env):
        self.test = test
        self.params = params
        self.env = env


    def initialize(self, test, params, env):
        if test:
            self.test = test
        if params:
            self.params = params
        if env:
            self.env = env


    def setup(self, test, params, env):
        if test:
            self.test = test
        if params:
            self.params = params
        if env:
            self.env = env


    def run_once(self, test, params, env):
        if test:
            self.test = test
        if params:
            self.params = params
        if env:
            self.env = env


    def before_run_once(self, test, params, env):
        pass


    def after_run_once(self, test, params, env):
        pass

    def cleanup(self, test, params, env):
        pass


    def execute(self, test, params, env):
        self.initialize(test, params, env)
        self.setup(test, params, env)
        try:
            self.before_run_once(test, params, env)
            self.run_once(test, params, env)
            self.after_run_once(test, params, env)
        finally:
            self.cleanup(test, params, env)


class QemuGuestAgentTest(BaseVirtTest):

    def __init__(self, test, params, env):
        BaseVirtTest.__init__(self, test, params, env)

        self._open_session_list = []
        self.gagent = None
        self.vm = None


    def _get_session(self, params, vm):
        if not vm:
            vm = self.vm
        vm.verify_alive()
        timeout = int(params.get("login_timeout", 360))
        session = vm.wait_for_login(timeout=timeout)
        return session


    def _session_cmd_close(self, session, cmd):
        try:
            return session.cmd_status_output(cmd)
        finally:
            try:
                session.close()
            except Exception:
                pass


    def _cleanup_open_session(self):
        try:
            for s in self._open_session_list:
                if s:
                    s.close()
        except Exception:
            pass


    @error.context_aware
    def gagent_install(self, params, vm, *args):
        if args and isinstance(args, tuple):
            gagent_install_cmd = args[0]
        else:
            raise error.TestError("Missing config 'gagent_install_cmd'")

        if not gagent_install_cmd:
            return

        error.context("Try to install 'qemu-guest-agent' package.",
                      logging.info)
        session = self._get_session(params, vm)
        s, _ = self._session_cmd_close(session, gagent_install_cmd)
        if bool(s):
            raise error.TestError("Could not install qemu-guest-agent package")


    @error.context_aware
    def gagent_start(self, params, vm, *args):
        if args and isinstance(args, tuple):
            gagent_start_cmd = args[0]
        else:
            raise error.TestError("Missing config 'gagent_start_cmd'")

        if not gagent_start_cmd:
            return

        error.context("Try to start 'qemu-guest-agent'.", logging.info)
        session = self._get_session(params, vm)
        s, _ = self._session_cmd_close(session, gagent_start_cmd)
        if bool(s):
            raise error.TestError("Could not start qemu-guest-agent in VM '%s'",
                                  vm.name)


    @error.context_aware
    def gagent_create(self, params, vm, *args):
        if self.gagent:
            return self.gagent

        error.context("Create a QemuAgent object.", logging.info)
        if not (args and isinstance(args, tuple) and len(args) == 2):
            raise error.TestError("Got invalid arguments for guest agent")

        gagent_serial_type = args[0]
        gagent_name = args[1]
        gagent = guest_agent.QemuAgent(vm, gagent_name, gagent_serial_type,
                                       get_supported_cmds=True)
        self.gagent = gagent

        return self.gagent


    @error.context_aware
    def setup_gagent_in_guest(self, params, vm):
        error.context("Setup guest agent in VM '%s'" % vm.name)
        self.gagent_install(params, vm, *[params.get("gagent_install_cmd")])
        self.gagent_start(params, vm, *[params.get("gagent_start_cmd")])
        args = [params.get("gagent_serial_type"), params.get("gagent_name")]
        self.gagent_create(params, vm, *args)


    @error.context_aware
    def gagent_verify(self, params, vm):
        error.context("Check if guest agent work.", logging.info)

        if not self.gagent:
            raise error.TestError("Could not find guest agent object"
                                  "for VM '%s'" % vm.name)

        self.gagent.verify_responsive()
        logging.info(self.gagent.cmd("guest-info"))


    def setup(self, test, params, env):
        BaseVirtTest.setup(self, test, params, env)

        if not self.vm:
            vm = self.env.get_vm(params["main_vm"])
            vm.verify_alive()
            self.vm = vm
        self.setup_gagent_in_guest(params, self.vm)


    def run_once(self, test, params, env):
        BaseVirtTest.run_once(self, test, params, env)

        if not self.vm:
            vm = self.env.get_vm(params["main_vm"])
            vm.verify_alive()
            self.vm = vm

        self.gagent_verify(self.params, self.vm)


    def cleanup(self, test, params, env):
        self._cleanup_open_session()


class QemuGuestAgentBasicCheck(QemuGuestAgentTest):

    def __init__(self, test, params, env):
        QemuGuestAgentTest.__init__(self, test, params, env)

        self.exception_list = []

    def gagent_check_install(self, test, params, env):
        pass


    @error.context_aware
    def gagent_check_sync(self, test, params, env):
        """
        Execute "guest-sync" command to guest agent

        Test steps:
        1) Send "guest-sync" command in the host side.

        @param test: kvm test object
        @param params: Dictionary with the test parameters
        @param env: Dictionary with test environmen.
        """
        error.context("Check guest agent command 'guest-sync'", logging.info)
        self.gagent.sync()


    @error.context_aware
    def __gagent_check_shutdown(self, shutdown_mode):
        error.context("Check guest agent command 'guest-shutdown'"
                      ", shutdown mode '%s'" % shutdown_mode, logging.info)
        if not self.env or not self.params:
            raise error.TestError("You should run 'setup' method before test")

        if not (self.vm and self.vm.is_alive()):
            vm = self.env.get_vm(self.params["main_vm"])
            vm.verify_alive()
            self.vm = vm
        self.gagent.shutdown(shutdown_mode)


    def __gagent_check_serial_output(self, pattern):
        start_time = time.time()
        while (time.time() - start_time) < self.vm.REBOOT_TIMEOUT:
            if pattern in self.vm.serial_console.get_output():
                return True
        return False


    def gagent_check_powerdown(self, test, params, env):
        """
        Shutdown guest with guest agent command "guest-shutdown"

        @param test: kvm test object
        @param params: Dictionary with the test parameters
        @param env: Dictionary with test environmen.
        """
        self.__gagent_check_shutdown(self.gagent.SHUTDOWN_MODE_POWERDOWN)
        if not utils_misc.wait_for(self.vm.is_dead, self.vm.REBOOT_TIMEOUT):
            raise error.TestFail("Could not shutdown VM via guest agent'")


    @error.context_aware
    def gagent_check_reboot(self, test, params, env):
        """
        Reboot guest with guest agent command "guest-shutdown"

        @param test: kvm test object
        @param params: Dictionary with the test parameters
        @param env: Dictionary with test environmen.
        """
        self.__gagent_check_shutdown(self.gagent.SHUTDOWN_MODE_REBOOT)
        # XXX: This way of checking if VM is rebooted can only work with
        # Linux guest, is there any way to check windows guest reboot?
        pattern = "machine restart"
        error.context("Verify serial output has '%s'" % pattern)
        rebooted = self.__gagent_check_serial_output(pattern)
        if not rebooted:
            raise error.TestFail("Could not reboot VM via guest agent")


    @error.context_aware
    def gagent_check_halt(self, test, params, env):
        """
        Halt guest with guest agent command "guest-shutdown"

        @param test: kvm test object
        @param params: Dictionary with the test parameters
        @param env: Dictionary with test environmen.
        """
        self.__gagent_check_shutdown(self.gagent.SHUTDOWN_MODE_HALT)
        # XXX: This way of checking if VM is halted can only work with
        # Linux guest, is there any way to check windows guest halt?
        pattern = "System halted"
        error.context("Verify serial output has '%s'" % pattern)
        halted = self.__gagent_check_serial_output(pattern)
        if not halted:
            raise error.TestFail("Could not halt VM via guest agent")
        # Since VM is halted, force shutdown it.
        try:
            self.vm.destroy(gracefully=False)
        except Exception:
            pass


    @error.context_aware
    def _action_before_fsfreeze(self, *args):
        session = self._get_session(self.params, None)
        self._open_session_list.append(session)


    @error.context_aware
    def _action_after_fsfreeze(self, *args):
        error.context("Verfiy FS is frozen in guest.")
        if not isinstance(args, tuple):
            return

        if not self._open_session_list:
            raise error.TestError("Could not find any opened session")
        # Use the last opened session to send cmd.
        session = self._open_session_list[-1]
        try:
            session.cmd(self.params["gagent_fs_test_cmd"])
        except aexpect.ShellTimeoutError:
            logging.debug("FS freeze successfully.")
        else:
            raise error.TestFail("FS freeze failed, guest still can"
                                 " write file")


    @error.context_aware
    def _action_before_fsthaw(self, *args):
        pass


    @error.context_aware
    def _action_after_fsthaw(self, *args):
        pass


    @error.context_aware
    def gagent_check_fsfreeze(self, test, params, env):
        """
        Test guest agent commands "guest-fsfreeze-freeze/status/thaw"

        Test steps:
        1) Check the FS is thawed.
        2) Freeze the FS.
        3) Check the FS is frozen from both guest agent side and guest os side.
        4) Thaw the FS.

        @param test: kvm test object
        @param params: Dictionary with the test parameters
        @param env: Dictionary with test environmen.
        """
        error.base_context("Check guest agent command 'guest-fsfreeze-freeze'",
                      logging.info)
        error.context("Verify FS is thawed and freeze the FS.")

        try:
            expect_status = self.gagent.FSFREEZE_STATUS_THAWED
            self.gagent.verify_fsfreeze_status(expect_status)
        except guest_agent.VAgentFreezeStatusError:
            # Thaw guest FS if the fs status is incorrect.
            self.gagent.fsthaw(check_status=False)

        self._action_before_fsfreeze(test, params, env)
        self.gagent.fsfreeze()
        try:
            self._action_after_fsfreeze(test, params, env)

            # Next, thaw guest fs.
            self._action_before_fsthaw(test, params, env)
            error.context("Thaw the FS.")
            self.gagent.fsthaw()
            self._action_after_fsthaw(test, params, env)
        finally:
            # Thaw fs finally, avoid problem in following cases.
            try:
                self.gagent.fsthaw(check_status=False)
            except Exception, detail:
                # Ignore exception for this thaw action.
                logging.warn("Finally failed to thaw guest fs,"
                             " detail: '%s'", detail)


    def run_once(self, test, params, env):
        QemuGuestAgentTest.run_once(self, test, params, env)

        gagent_check_type = self.params["gagent_check_type"]
        chk_type = "gagent_check_%s" % gagent_check_type
        if hasattr(self, chk_type):
            func = getattr(self, chk_type)
            func(test, params, env)
        else:
            raise error.TestError("Could not find matching test, check your"
                                  " config file")


def run_qemu_guest_agent(test, params, env):
    """
    Test qemu guest agent, this case will:
    1) Start VM with virtio serial port.
    2) Install qemu-guest-agent package in guest.
    3) Run some basic test for qemu guest agent.

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environmen.
    """
    gagent_test = QemuGuestAgentBasicCheck(test, params, env)
    gagent_test.execute(test, params, env)
