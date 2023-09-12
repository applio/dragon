import os
import traceback
import time
import logging
import queue
import threading
import io
import subprocess
import json
import collections
import selectors
import signal
import socket

from .. import channels as dch
from .. import managed_memory as dmm

from .. import pmod
from .. import utils as dutils
from ..infrastructure import messages as dmsg
from ..infrastructure import util as dutil
from ..infrastructure import facts as dfacts
from ..infrastructure import parameters as parms
from ..infrastructure import connection as dconn
from ..infrastructure import parameters as dp

from ..dlogging import util as dlog
from ..dlogging.util import DragonLoggingServices as dls
from ..utils import B64

_TAG = 0
_TAG_LOCK = threading.Lock()

def get_new_tag():
    global _TAG
    with _TAG_LOCK:
        tmp = _TAG
        _TAG += 1
    return tmp

ProcessProps = collections.namedtuple('ProcessProps', ['p_uid', 'critical', 'r_c_uid',
                                      'stdin_req', 'stdout_req', 'stderr_req',
                                      'stdin_connector', 'stdout_connector', 'stderr_connector'])

class PopenProps(subprocess.Popen):

    def __init__(self, props: ProcessProps, *args, **kwds):
        assert isinstance(props, ProcessProps)
        super().__init__(*args, **kwds)
        self.props = props
        # TODO Add affinity control to the process options. To be on the safe
        # TODO side for now, open affinity to all cores.
        os.sched_setaffinity(self.pid, range(os.cpu_count()))
        # XXX Affinity settings are only inherited by grandchild processes
        # XXX created after this point in time. Any grandchild processes
        # XXX started when the child process starts up most certainly will
        # XXX not have the desired affinity. To guarantee CPU affinity settings
        # XXX processes should be launched with e.g. taskset(1) or otherwise
        # XXX be configured to set their own affinity as appropriate.

class TerminationException(Exception):
    pass

class InputConnector:
    def __init__(self, conn:dconn.Connection):
        self._proc = None
        self._conn = conn
        self._log = logging.getLogger('input connector')
        self._closed = False

    def add_proc_info(self, proc:PopenProps):
        self._proc = proc

    def poll(self):
        return self._conn.poll()

    def forward(self):
        try:
            data = None
            while self._conn.poll(timeout=0):
                data = self._conn.recv()
                self._proc.stdin.write(data.encode('utf-8'))
                self._proc.stdin.flush()
                self._log.info(f'Stdin data that was written:{data}')
        except EOFError as ex:
            return True
        except TimeoutError:
            return False
        except:
            self._log.info(f'The input could not be forwarded from cuid={self._conn.inbound_chan.cuid} to process pid={self._proc.pid}')

        return False

    def __hash__(self):
        return hash(self._conn.inbound_channel.cuid)

    def __eq__(self, other):
        # since all cuid's are unique we can compare cuids. In addition,
        # if we want we can ask if a cuid is in a set of connectors in O(1) time.
        return hash(self) == hash(other)

    def close(self):
        if self._closed:
            return

        try:
            if self._conn is not None:
                if self.poll():
                    self.forward()
                self._conn.close()
        except:
            pass

        try:
            self._proc.stdin.flush()
            self._proc.stdin.close()
        except:
            pass

        self._closed = True

    @property
    def proc_is_alive(self):
        return self._proc.returncode is None

    @property
    def conn(self):
        return self._conn

    @property
    def cuid(self):
        if self._conn is None:
            return None

        return self._conn.inbound_channel.cuid

class OutputConnector:
    def __init__(self, be_in, puid, hostname, out_err, conn:dconn.Connection = None, root_proc=None, critical_proc=False):
        self._be_in = be_in
        self._puid = puid
        self._hostname = hostname
        self._out_err = out_err
        self._conn = conn
        self._root_proc = root_proc
        self._log = logging.getLogger('output connector')
        self._writtenTo = False
        self._critical_proc = critical_proc
        self._closed = False
        self._proc = None

    def __hash__(self):
        return hash(self._conn.outbound_channel.cuid)

    def __eq__(self, other):
        # since all cuid's are unique we can compare cuids. In addition,
        # if we want we can ask if a cuid is in a set of connectors in O(1) time.
        return hash(self) == hash(other)

    def _sendit(self, block):
        if len(block) > 0:
            self._writtenTo = True

        if self._conn is None:
            self._be_in.send(dmsg.SHFwdOutput(tag=get_new_tag(), idx=parms.this_process.index,
                    p_uid=self._puid, data=block,
                    fd_num=self._out_err,
                    pid=self._proc.pid, hostname=self._hostname).serialize())
            return

        try:
            # A process has requested that output be forwarded from this process to it.
            # Because a connection could be owned by a parent and if the parent
            # exits the connection could be destroyed, we'll use exception handling
            # here and as a backup, we'll forward lost output to the launcher.
            self._conn.send(block)
        except:
            self._be_in.send(dmsg.SHFwdOutput(tag=get_new_tag(), idx=parms.this_process.index,
                        p_uid=self._puid, data='[orphaned output]: '+block,
                        fd_num=self._out_err,
                        pid=self._proc.pid, hostname=self._hostname).serialize())

    def add_proc_info(self, proc):
        self._proc = proc

    def forward(self, data):
        if self._conn is not None:
            while len(data) > 300:
                chunk = data[:300]
                self._sendit(chunk)
                data = data[300:]

            if len(data) > 0:
                self._sendit(data)
        else:
            self._sendit(data)

    def flush(self):

        is_stderr = self._out_err == dmsg.SHFwdOutput.FDNum.STDERR.value

        try:
            file_obj = self.file_obj

            if file_obj is not None:
                io_data = file_obj.read(dmsg.SHFwdOutput.MAX)
            else:
                io_data = None

        except EOFError:
            io_data = None
        except ValueError:  # race, file could be closed
            io_data = None
        except OSError: # race, file is closed
            io_data = None

        if not io_data:  # at EOF because we just selected
            return True # To indicate EOF

        str_data = io_data.decode()

        if not is_stderr and self._puid == dfacts.GS_PUID:
            raise TerminationException(str_data)
        else:
            self.forward(str_data)

        if self._critical_proc and is_stderr:
            raise TerminationException(str_data)

        return False

    def close(self):
        if self._closed:
            return

        self.flush()

        try:
            self.file_obj.close()
        except:
            pass

        if not self._root_proc:
            # Don't call close on the connection unless a root proc.
            # Children share the same connection so we don't want to
            # close it from a child.
            self._closed = True
            return

        if self._conn is not None and not self._writtenTo:
            # If it is not written to yet, the connection must be
            # written to before it is closed so that EOF gets signaled
            # for the receiving process.
            try:
                self._conn.send('')
            except:
                pass
            self._writtenTo = True

        if self._conn is not None:
            try:
                self._conn.close()
            except:
                pass

        self._closed = True

    @property
    def file_obj(self):
        is_stderr = self._out_err == dmsg.SHFwdOutput.FDNum.STDERR.value

        if is_stderr:
            return self._proc.stderr

        return self._proc.stdout

    @property
    def proc_is_alive(self):
        return self._proc.returncode is None

    @property
    def puid(self):
        return self._puid

    @property
    def conn(self):
        return self._conn

    @property
    def cuid(self):
        if self._conn is None:
            return None
        return self._conn.outbound_channel.cuid

def mk_response_pairs(resp_cl, ref):
    err_cl = resp_cl.Errors

    def success_resp(desc=None, **kwargs):
        if desc is not None:
            return resp_cl(tag=get_new_tag(), ref=ref, err=err_cl.SUCCESS, desc=desc, **kwargs)
        else:
            return resp_cl(tag=get_new_tag(), ref=ref, err=err_cl.SUCCESS, **kwargs)


    def fail_resp(msg):
        return resp_cl(tag=get_new_tag(), ref=ref, err=err_cl.FAIL, err_info=msg)

    return success_resp, fail_resp


def mk_output_connection_over_channel(ch_desc):

    channel_descriptor = B64.str_to_bytes(ch_desc)
    the_channel = dch.Channel.attach(channel_descriptor)
    return dconn.Connection(outbound_initializer=the_channel,
                            options=dconn.ConnectionOptions(min_block_size=512), policy=dp.POLICY_INFRASTRUCTURE)

def mk_input_connection_over_channel(ch_desc):

    channel_descriptor = B64.str_to_bytes(ch_desc)
    the_channel = dch.Channel.attach(channel_descriptor)
    return dconn.Connection(inbound_initializer=the_channel,
                            options=dconn.ConnectionOptions(min_block_size=512), policy=dp.POLICY_INFRASTRUCTURE)


class LocalServer:
    """Handles shepherd messages in normal processing.

    This object does not handle startup/teardown - instead
     it expects to be given whatever channels/pools have been made for it
     by startup, handles to what it needs to talk to in normal processing,
     and offers a 'run' and 'cleanup' method.
    """

    _DTBL = {}  # dispatch router, keyed by type of shepherd message

    SHUTDOWN_RESP_TIMEOUT = 0.010  # seconds, 10 ms
    QUIESCE_TIME = 1  # seconds, 1 second, join timeout for thread shutdown.

    def __init__(self, channels=None, pools=None,
                 transport_test_mode=False,
                 hostname='NONE'):

        self.transport_test_mode = transport_test_mode
        self.new_procs = queue.SimpleQueue()  # outbound PopenProps of newly started processes
        self.new_channel_input_monitors = queue.SimpleQueue()
        self.exited_channel_output_monitors = queue.SimpleQueue()
        self.hostname = hostname
        self.cuid_to_input_connector = {}

        if channels is None:
            self.channels = {}  # key c_uid value channel
        else:
            self.channels = channels
        if pools is None:
            self.pools = {}  # key m_uid value memory pool
        else:
            self.pools = pools

        self.apt = {}  # active process table. key: pid, value PopenProps obj
        self.puid2pid = {}  # key: p_uid, value pid
        self.apt_lock = threading.Lock()

        self.shutdown_sig = threading.Event()
        self.gs_shutdown_sig = threading.Event()
        self.ta_shutdown_sig = threading.Event()
        self.stashed_threading_excepthook = None
        self.exit_reason = None

    def _logging_ex_handler(self, args):
        log = logging.getLogger('fatal exception')
        ex_type, ex_value, ex_tb, thread = args
        if ex_type is SystemExit:
            return

        buf = io.BytesIO()
        wrap = io.TextIOWrapper(buf, write_through=True)
        traceback.print_exception(ex_type, ex_value, ex_tb, file=wrap)
        log.error(f'from {thread.name}:\n{buf.getvalue().decode()}')
        self._abnormal_termination(f'from {thread.name}:\n{buf.getvalue().decode()}')

    def set_shutdown(self, msg):
        log = logging.getLogger('shutdown event')
        self.shutdown_sig.set()
        log.info(f'shutdown called after receiving {repr(msg)}')

    def check_shutdown(self):
        return self.shutdown_sig.is_set()

    def set_gs_shutdown(self):
        log = logging.getLogger('gs shutdown event')
        self.gs_shutdown_sig.set()
        log.info('set GS shutdown')

    def check_gs_shutdown(self):
        return self.gs_shutdown_sig.is_set()

    def set_ta_shutdown(self):
        log = logging.getLogger('ta shutdown event')
        self.ta_shutdown_sig.set()
        log.info('set TA shutdown')

    def check_ta_shutdown(self):
        return self.ta_shutdown_sig.is_set()

    def __str__(self):
        with self.apt_lock:
            plist = [f'\t{p_uid}:{pid} {self.apt[pid]!s}'
                     for p_uid, pid in self.puid2pid.items()]

        procs = '\n'.join(plist)
        chans = ' '.join([f'{k!s}' for k in self.channels.keys()])
        pools = ' '.join([f'{k!s}' for k in self.pools.keys()])

        return f'Procs:\n{procs}\nChans:\n{chans}\nPools:\n{pools}'

    def add_proc(self, proc):
        with self.apt_lock:
            self.apt[proc.pid] = proc
            self.puid2pid[proc.props.p_uid] = proc.pid

        self.new_procs.put(proc)

    @staticmethod
    def clean_pools(pools, log):
        log.info(f'{len(pools)} pools outstanding')
        for m_uid, pool in pools.items():
            try:
                pool.destroy()
            except (dmm.DragonMemoryError, dmm.DragonPoolError) as dpe:
                log.warning(f'm_uid={m_uid} failed: {dpe!s}')

    def _clean_procs(self):
        log = logging.getLogger('kill procs')

        with self.apt_lock:
            log.info(f'{len(self.apt)} processes outstanding')
            for p_uid, pid in self.puid2pid.items():
                proc = self.apt[pid]
                try:
                    proc.kill()
                    log.info(f'kill sent to p_uid={p_uid}:proc.pid={proc.pid}')
                except (subprocess.SubprocessError, OSError) as ose:
                    log.warning(f'kill on p_uid={p_uid}: prod.pid={proc.pid} failed: {ose}')

            self.puid2pid = {}

            for proc in self.apt.values():
                try:
                    proc.wait(10)

                except subprocess.SubprocessError as spe:
                    log.warning(f'wait on puid={proc.props.p_uid} failed: {spe}')

            self.apt = {}

    def cleanup(self):
        """Tries to destroy channels and pools and kill outstanding processes.

        None of the other threads should be running at this point.
        """
        log = logging.getLogger('cleanup')

        log.info('start')

        # clean outstanding processes
        self._clean_procs()

        log.info(f'{len(self.channels)} channels outstanding')
        for c_uid, chan in self.channels.items():
            try:
                chan.destroy()
            except dch.ChannelError as cse:
                log.warning(f'c_uid={c_uid} failed: {cse!s}')
        self.channels = {}

        self.clean_pools(self.pools, log)
        self.pools = {}

        log.info('end')

    def _abnormal_termination(self, error_str):
        """Triggers LS abnormal termination.
        Sends AbnormalTermination message to Launcher BE and logs.

        :param error_str: error message with the cause of abnormal termination
        :type error_str: string
        """
        log = logging.getLogger('Abnormal termination')
        try:
            self.be_in.send(dmsg.AbnormalTermination(tag=get_new_tag(), err_info=error_str).serialize())
            log.critical(f"Abnormal termination sent to launcher be: {error_str}")
        except Exception as ex:
            log.exception(f'Abnormal termination exception: {ex}')

    def run(self, shep_in, gs_in, be_in, is_primary, ta_in=None, gw_channels=None):
        """Local services main function.

        :param shep_in: ls channel
        :type shep_in: Connection object
        :param gs_in: global services channel
        :type gs_in: Connection object
        :param be_in: launcher be channel
        :type be_in: Connection object
        :param is_primary: indicates if this is the primary LS or not
        :type is_primary: bool
        :param ta_in: transport agent channel, defaults to None
        :type ta_in: Connection object, optional
        :param gw_channels: list of gateway channels for multinode only, defaults to None
        :type gw_channels: list, optional
        """
        log = logging.getLogger('ls run')
        log.info('start')

        if gw_channels is None:
            gw_channels = []

        self.ta_in = ta_in
        self.be_in = be_in
        self.gs_in = gs_in
        self.is_primary = is_primary

        th = threading.Thread
        threads = [th(name='output mon', target=self.watch_output, daemon=True),
                   th(name='watch death', target=self.watch_death, daemon=True),
                   th(name='input mon', target=self.watch_input, daemon=True)]

        self.stashed_threading_excepthook = threading.excepthook
        threading.excepthook = self._logging_ex_handler

        try:
            log.info('starting runtime service threads')
            for th in threads:
                th.start()
            log.info('runtime service threads started')
        except Exception as ex:
            self._abnormal_termination(f'ls run starting threads exception: {ex}')

        try:
            self.main_loop(shep_in)
        except Exception as ex:
            tb = traceback.format_exc()
            self._abnormal_termination(f'ls main loop exception: {ex}\n{tb}')

        threading.excepthook = self.stashed_threading_excepthook

        try:
            for th in threads:
                th.join(self.QUIESCE_TIME)
            for th in threads:
                if th.is_alive():
                    log.error(f'thread {th.name} seems to have hung!')
        except Exception as ex:
            self._abnormal_termination(f'ls run joining threads exception: {ex}')

        if self.transport_test_mode and self.exit_reason is None:
            # In the transport test mode, normal set_shutdown was called.
            log.info('beginning normal shutdown during transport test mode run')

        try:
            # Destroy gateway channels
            gw_count = 0
            for id, gw_ch in enumerate(gw_channels):
                gw_ch.destroy()
                try:
                    del os.environ[dfacts.GW_ENV_PREFIX+str(id+1)]
                except KeyError:
                    pass
                gw_count += 1
            log.info(f'ls isPrimary={self.is_primary} destroyed {gw_count} gateway channels')
        except Exception as ex:
            self._abnormal_termination(f'ls run destroying gateway channels exception: {ex}')

        try:
            # m12 Send SHHaltBE to BE
            # tell launcher be to shut mrnet down and detach from logging
            log.info('m12 transmitting final messsage from ls SHHaltBE')
            dlog.detach_from_dragon_handler(dls.LS)
            self.be_in.send(dmsg.SHHaltBE(tag=get_new_tag()).serialize())
        except Exception as ex:
            self._abnormal_termination(f'ls run sending SHHaltBE exception: {ex}')

        log.info('exit')

    def main_loop(self, shep_rh):
        """Monitors the main LS input channel and receives messages.
        If the received message is not one of the expected that are
        handled by corresponding route decorators, then it signals
        abnormal termination of LS.

        :param shep_rh: ls input channel
        :type shep_rh: Connection object
        """
        log = logging.getLogger('main loop')
        log.info('start')

        while not self.check_shutdown():
            msg_pre = shep_rh.recv()

            if msg_pre is None:
                continue

            if isinstance(msg_pre, str):
                try:
                    msg = dmsg.parse(msg_pre)
                except (json.JSONDecodeError, KeyError, NotImplementedError, ValueError) as err:
                    self._abnormal_termination(f'msg\n{msg_pre}\nfailed parse!\n{err!s}')
                    continue
            else:
                msg = msg_pre

            if type(msg) in LocalServer._DTBL:
                resp_msg = self._DTBL[type(msg)][0](self, msg=msg)
                if resp_msg is not None:
                    self._send_response(target_uid=msg.r_c_uid, msg=resp_msg)
            else:
                self._abnormal_termination(f'unexpected msg type: {repr(msg)}')

        log.info('exit')

    def _send_response(self, target_uid, msg):
        """Sends response to either Global Services or Launcher BE
        depending on the target/return channel uid. Signals
        abnormal termination in the case of an unknown r_c_uid.

        :param target_uid: return channel uid, r_c_uid
        :type target_uid: int
        :param msg: message for the response
        :type msg: string
        """
        if target_uid == dfacts.GS_INPUT_CUID:
            self.gs_in.send(msg.serialize())
        elif target_uid == dfacts.launcher_cuid_from_index(parms.this_process.index):
            self.be_in.send(msg.serialize())
        else:
            self._abnormal_termination(f'unknown r_c_uid: {repr(msg)}')

    @dutil.route(dmsg.SHPoolCreate, _DTBL)
    def create_pool(self, msg: dmsg.SHPoolCreate) -> None:
        log = logging.getLogger('create pool')
        success, fail = mk_response_pairs(dmsg.SHPoolCreateResponse, msg.tag)

        error = ''
        if msg.m_uid in self.pools:
            error = f'msg.m_uid={msg.m_uid!s} already in use'

        if not error:
            try:
                mpool = dmm.MemoryPool(msg.size, msg.name, msg.m_uid)
            except (dmm.DragonPoolError, dmm.DragonMemoryError) as dme:
                error = f'{msg!r} failed: {dme!s}'

        if error:
            log.warning(error)
            resp_msg = fail(error)
        else:
            self.pools[msg.m_uid] = mpool
            encoded_desc = B64.bytes_to_str(mpool.serialize())
            resp_msg = success(encoded_desc)

        return resp_msg

    @dutil.route(dmsg.SHPoolDestroy, _DTBL)
    def destroy_pool(self, msg: dmsg.SHPoolDestroy) -> None:
        log = logging.getLogger('destroy pool')
        success, fail = mk_response_pairs(dmsg.SHPoolDestroyResponse, msg.tag)

        error = ''
        if msg.m_uid not in self.pools:
            error = f'msg.m_uid={msg.m_uid!s} does not exist'

        if not error:
            mpool = self.pools.pop(msg.m_uid)
            try:
                mpool.destroy()
            except (dmm.DragonPoolError, dmm.DragonMemoryError) as dme:
                error = f'{msg!r} failed: {dme!s}'

        if error:
            log.warning(error)
            resp_msg = fail(error)
        else:
            resp_msg = success()

        return resp_msg

    @dutil.route(dmsg.SHChannelCreate, _DTBL)
    def create_channel(self, msg: dmsg.SHChannelCreate) -> None:
        log = logging.getLogger('create channel')
        log.info("Received an SHChannelCreate")
        success, fail = mk_response_pairs(dmsg.SHChannelCreateResponse, msg.tag)

        error = ''
        if msg.c_uid in self.channels:
            error = f'msg.c_uid={msg.c_uid!s} already in use'

        if msg.m_uid not in self.pools:
            error = f'msg.m_uid={msg.m_uid!s} does not exist'

        if not error:
            try:
                ch = dch.Channel(mem_pool=self.pools[msg.m_uid], c_uid=msg.c_uid,
                                 block_size=msg.options.block_size,
                                 capacity=msg.options.capacity)
            except dch.ChannelError as cex:
                error = f'{msg!r} failed: {cex!s}'

        if error:
            log.warning(error)
            resp_msg=fail(error)
        else:
            self.channels[msg.c_uid] = ch
            encoded_desc = B64.bytes_to_str(ch.serialize())
            resp_msg = success(encoded_desc)
            log.info("Received and Created a channel via SHChannelCreate")

        return resp_msg

    @dutil.route(dmsg.SHChannelDestroy, _DTBL)
    def destroy_channel(self, msg: dmsg.SHChannelDestroy) -> None:
        log = logging.getLogger('destroy channel')
        success, fail = mk_response_pairs(dmsg.SHChannelDestroyResponse, msg.tag)

        error = ''
        if msg.c_uid not in self.channels:
            error = f'{msg.c_uid} does not exist'

        if not error:
            ch = self.channels.pop(msg.c_uid)
            try:
                ch.destroy()
            except dch.ChannelError as cex:
                error = f'{msg!r} failed: {cex!s}'

        if error:
            log.warning(error)
            resp_msg = fail(error)
        else:
            resp_msg = success()

        return resp_msg

    @dutil.route(dmsg.SHProcessCreate, _DTBL)
    def create_process(self, msg: dmsg.SHProcessCreate) -> None:
        log = logging.getLogger('create process')
        success, fail = mk_response_pairs(dmsg.SHProcessCreateResponse, msg.tag)

        if msg.t_p_uid in self.puid2pid:
            error = f'msg.t_p_uid={msg.t_p_uid} already exists'
            log.warning(error)
            self._send_response(target_uid=msg.r_c_uid, msg=fail(error))
            return

        if not msg.rundir:
            working_dir = None
        else:
            working_dir = msg.rundir

        # TODO for multinode: whose job is it to update which parameters?
        log.debug(f'The number of gateways per node is configured to {parms.this_process.num_gw_channels_per_node}')
        log.debug(f'Removing these from environment: {parms.LaunchParameters.NODE_LOCAL_PARAMS}')
        req_env = dict(msg.env)
        parms.LaunchParameters.remove_node_local_evars(req_env)
        the_env = dict(os.environ)
        the_env.update(req_env)

        stdin_conn = None
        stdin_resp = None
        stdout_conn = None
        stdout_resp = None
        stderr_conn = None
        stderr_resp = None
        stdout_root = False
        stderr_root = False

        if msg.stdin_msg is not None:
            stdin_resp = self.create_channel(msg.stdin_msg)
            if stdin_resp.err != dmsg.SHChannelCreateResponse.Errors.SUCCESS:
                resp_msg = fail(f'Failed creating the stdin channel for new process: {stdin_resp.err_info}')
                return resp_msg
            stdin_conn = mk_input_connection_over_channel(stdin_resp.desc)

        if msg.stdout_msg is not None:
            stdout_resp = self.create_channel(msg.stdout_msg)
            if stdout_resp.err != dmsg.SHChannelCreateResponse.Errors.SUCCESS:
                # TBD: We need to destroy the stdin channel if it exists
                resp_msg = fail(f'Failed creating the stdout channel for new process: {stdout_resp.err_info}')
                return resp_msg
            stdout_conn = mk_output_connection_over_channel(stdout_resp.desc)
            stdout_root = True
            the_env[dfacts.STDOUT_DESC] = stdout_resp.desc
        elif dfacts.STDOUT_DESC in the_env:
            # Finding the STDOUT descriptor in the environment
            # means a parent requested PIPE and so all children
            # inherit this as well. If a child of the parent requested
            # PIPE itself, then it would have been caught above.
            stdout_conn = mk_output_connection_over_channel(the_env[dfacts.STDOUT_DESC])

        if msg.stderr_msg is not None:
            stderr_resp = self.create_channel(msg.stderr_msg)
            if stderr_resp.err != dmsg.SHChannelCreateResponse.Errors.SUCCESS:
                # TBD: We need to destroy the stdin and stdout channels if they exist
                resp_msg = fail(f'Failed creating the stderr channel for new process: {stderr_resp.err_info}')
                return resp_msg
            stderr_conn = mk_output_connection_over_channel(stderr_resp.desc)
            stderr_root = True
            the_env[dfacts.STDERR_DESC] = stderr_resp.desc
        elif msg.stderr == dmsg.STDOUT:
            # We put stderr connection in environment so any subprocesses
            # will also write to the stdout connection.
            stderr_conn = stdout_conn
            the_env[dfacts.STDERR_DESC] = stdout_resp.desc
        elif dfacts.STDERR_DESC in the_env:
            # Finding the STDERR descriptor in the environment
            # means inherit it. See above for STDOUT explanation.
            stderr_conn = mk_output_connection_over_channel(the_env[dfacts.STDERR_DESC])

        real_args = [msg.exe] + msg.args

        try:
            stdout = subprocess.PIPE
            if msg.stdout == subprocess.DEVNULL:
                # if user is requesting devnull, then we'll start
                # process that way. Otherwise, LS gets output
                # via PIPE forwards it where requested.
                stdout = subprocess.DEVNULL

            stderr = subprocess.PIPE
            if msg.stderr == subprocess.DEVNULL:
                # Same handling as stdout explanation above.
                stderr = subprocess.DEVNULL

            if msg.stderr == subprocess.STDOUT:
                stderr = subprocess.STDOUT

            if msg.pmi_info:
                log.debug(f'{msg.pmi_info}')
                log.info(f'p_uid {msg.t_p_uid} looking up pmod launch cuid')
                pmod_launch_cuid = dfacts.pmod_launch_cuid_from_jobinfo(
                    dutils.host_id(),
                    msg.pmi_info.job_id,
                    msg.pmi_info.lrank
                )

                log.info(f'p_uid {msg.t_p_uid} Creating pmod launch channel using {pmod_launch_cuid=}')
                node_index = parms.this_process.index
                inf_muid = dfacts.infrastructure_pool_muid_from_index(node_index)
                pmod_launch_ch = dch.Channel(self.pools[inf_muid], pmod_launch_cuid)
                the_env['DRAGON_PMOD_CHILD_CHANNEL'] = str(dutils.B64(pmod_launch_ch.serialize()))

                log.info(f'p_uid {msg.t_p_uid} Setting required PMI environment variables')
                the_env['PMI_CONTROL_PORT'] = str(msg.pmi_info.control_port)
                the_env['MPICH_OFI_CXI_PID_BASE'] = str(msg.pmi_info.pid_base)
                the_env['DL_PLUGIN_RESILIENCY'] = "1"
                the_env['LD_PRELOAD'] = 'libdragon.so'
                the_env['_DRAGON_PALS_ENABLED'] = '1'
                the_env['FI_CXI_RX_MATCH_MODE'] = 'hybrid'
                # the_env['DRAGON_DEBUG'] = '1'
                # the_env['PMI_DEBUG'] = '1'

            stdin_connector = InputConnector(stdin_conn)

            stdout_connector = OutputConnector(be_in = self.be_in, puid=msg.t_p_uid,
                    hostname=self.hostname, out_err=dmsg.SHFwdOutput.FDNum.STDOUT.value,
                    conn=stdout_conn, root_proc=stdout_root, critical_proc=False)

            stderr_connector = OutputConnector(be_in = self.be_in, puid=msg.t_p_uid,
                    hostname=self.hostname, out_err=dmsg.SHFwdOutput.FDNum.STDERR.value,
                    conn=stderr_conn, root_proc=stderr_root, critical_proc=False)

            with self.apt_lock:  # race with death watcher; hold lock to get process in table.
                # The stdout_conn and stderr_conn will be filled in just below.
                the_proc = PopenProps(
                    ProcessProps(p_uid=msg.t_p_uid, critical=False, r_c_uid=msg.r_c_uid,
                        stdin_req=msg.stdin, stdout_req=msg.stdout, stderr_req=msg.stderr,
                        stdin_connector=stdin_connector, stdout_connector=stdout_connector,
                        stderr_connector=stderr_connector),
                    real_args,
                    bufsize=0,
                    stdin=subprocess.PIPE,
                    stdout=stdout,
                    stderr=stderr,
                    cwd=working_dir,
                    env=the_env
                )

                stdout_connector.add_proc_info(the_proc)
                stderr_connector.add_proc_info(the_proc)
                stdin_connector.add_proc_info(the_proc)

                if msg.stdin == dmsg.PIPE:
                    self.cuid_to_input_connector[msg.stdin_msg.c_uid] = stdin_connector
                    self.new_channel_input_monitors.put(stdin_connector)

                self.puid2pid[msg.t_p_uid] = the_proc.pid
                self.apt[the_proc.pid] = the_proc
                log.info(f'Now created process with args {real_args} and pid={the_proc.pid}')

            if msg.pmi_info:
                log.info(f'p_uid {msg.t_p_uid} sending mpi data for {msg.pmi_info.lrank}')
                pmod.PMOD(
                    msg.pmi_info.ppn,
                    msg.pmi_info.nid,
                    msg.pmi_info.nnodes,
                    msg.pmi_info.nranks,
                    msg.pmi_info.nidlist,
                    msg.pmi_info.hostlist,
                    msg.pmi_info.job_id
                ).send_mpi_data(msg.pmi_info.lrank, pmod_launch_ch)
                log.info(f'p_uid {msg.t_p_uid} DONE: sending mpi data for {msg.pmi_info.lrank}')

            log.info(f'p_uid {msg.t_p_uid} created as {the_proc.pid}')
            self.new_procs.put(the_proc)
            if msg.initial_stdin is not None and msg.initial_stdin != '':
                # we are asked to provide a string to the started process.
                log.info(f'Writing {msg.initial_stdin} to newly created process')
                proc_stdin = os.fdopen(the_proc.stdin.fileno(), 'wb')
                proc_stdin_send = dutil.NewlineStreamWrapper(proc_stdin, read_intent=False)
                proc_stdin_send.send(msg.initial_stdin)
                log.info('The provided string was written to stdin of the process by local services.')

            resp_msg = success(stdin_resp=stdin_resp, stdout_resp=stdout_resp, stderr_resp=stderr_resp)
        except (OSError, ValueError) as popen_err:
            error = f'{msg!r} encountered {popen_err}'
            log.warning(error)
            resp_msg = fail(error)

        return resp_msg

    @dutil.route(dmsg.SHProcessKill, _DTBL)
    def kill_process(self, msg: dmsg.SHProcessKill) -> None:
        log = logging.getLogger('kill process')
        success, fail = mk_response_pairs(dmsg.SHProcessKillResponse, msg.tag)

        try:
            target = self.puid2pid[msg.t_p_uid]
        except KeyError:
            error = f'{msg.t_p_uid} not present'
            log.warning(error)
            self._send_response(target_uid=msg.r_c_uid, msg=fail(error))
            return

        try:
            os.kill(target, msg.sig)
            log.info(f'{msg!r} delivered to pid {target}')
            resp_msg = success()
        except OSError as ose:
            error = f'delivering {msg!r} to pid {target} encountered {ose}'
            log.warning(error)
            resp_msg = fail(error)

        return resp_msg

    @dutil.route(dmsg.SHFwdInput, _DTBL)
    def fwd_input(self, msg: dmsg.SHFwdInput) -> None:
        log = logging.getLogger('fwd input handler')

        target = msg.t_p_uid
        error = ''
        with self.apt_lock:
            if target in self.puid2pid:
                targ_proc = self.apt[self.puid2pid[target]]
                if targ_proc.stdin is None:
                    error = f'p_uid {target} has no stdin'
            else:
                targ_proc = None
                error = f'p_uid {target} does not exist here and now'

        if not error:
            input_sel = selectors.DefaultSelector()
            input_sel.register(targ_proc.stdin, selectors.EVENT_WRITE)
            sel = input_sel.select(timeout=self.SHUTDOWN_RESP_TIMEOUT)
            if sel:
                try:
                    output_data = msg.input.encode()
                    if len(output_data) > dmsg.SHFwdInput.MAX:
                        log.warning(f'truncating request of {len(output_data)} to {dmsg.SHFwdInput.MAX}')

                    fh = sel[0][0].fileobj
                    fh.write(output_data[:dmsg.SHFwdInput.MAX])
                except (OSError, BlockingIOError) as err:
                    error = f'{err!s}'
            else:
                error = f'input of target={target} not ready for writing'
            input_sel.close()

        if error:
            log.warning(f'error={error} from {msg!s}')
            if targ_proc is not None and targ_proc.stdin is not None:
                targ_proc.stdin.close()
                targ_proc.stdin = None

        if msg.confirm:
            success, fail = mk_response_pairs(dmsg.SHFwdInputErr, msg.tag)
            if error:
                resp_msg = fail(error)
            else:
                resp_msg = success()

            return resp_msg

    @dutil.route(dmsg.AbnormalTermination, _DTBL)
    def handle_abnormal_term(self, msg: dmsg.AbnormalTermination) -> None:
        log = logging.getLogger('abnormal termination')
        log.info("received abnormal termination signal. starting shutdown process.")
        self._abnormal_termination(msg.err_info)

    @dutil.route(dmsg.GSHalted, _DTBL)
    def handle_gs_halted(self, msg: dmsg.GSHalted) -> None:
        self.set_gs_shutdown()
        log = logging.getLogger('forward GSHalted msg')
        log.info('is_primary=True and GSHalted recvd')
        self.be_in.send(msg.serialize())

    @dutil.route(dmsg.SHTeardown, _DTBL)
    def teardown_ls(self, msg: dmsg.SHTeardown) -> None:
        log = logging.getLogger('teardown LS')
        log.info(f'isPrimary={self.is_primary} handling SHTeardown')
        self.set_shutdown(msg)

    @dutil.route(dmsg.SHHaltTA, _DTBL)
    def handle_halting_ta(self, msg):
        log = logging.getLogger('forward SHHaltTA msg')
        log.info(f'handling {msg!s}')
        # m8 Forward SHHaltTA to TA
        self.ta_in.send(msg.serialize())

    @dutil.route(dmsg.TAHalted, _DTBL)
    def handle_ta_halted(self, msg):
        self.set_ta_shutdown()
        log = logging.getLogger('forward TAHalted msg')
        log.info(f'handling {msg!s}')
        self.be_in.send(msg.serialize())

    @dutil.route(dmsg.SHDumpState, _DTBL)
    def dump_state(self, msg: dmsg.SHDumpState) -> None:
        log = logging.getLogger('dump state')
        the_dump = f'{self!s}'
        if msg.filename is None:
            log.info('\n' + the_dump)
        else:
            try:
                with open(msg.filename, 'w') as dump_fh:
                    dump_fh.write(the_dump)

                log.info(f'to {msg.filename}')
            except (IOError, OSError) as e:
                log.warning(f'failed: {e!s}')

    def watch_death(self):
        """Thread monitors the demise of child processes of this process.

        Not all children do we care about; only the ones in our process group.

        :return: None, but exits on self.check_shutdown()
        """

        log = logging.getLogger('watch death')
        log.info('starting')

        while not self.check_shutdown():
            try:
                died_pid, exit_status = os.waitpid(0, os.WNOHANG)
            except ChildProcessError:  # no child processes at the moment
                # There is no error here. There just isn't a child process.
                died_pid, exit_status = (0, 0)

            if died_pid:
                with self.apt_lock:
                    try:
                        proc = self.apt.pop(died_pid)
                        self.puid2pid.pop(proc.props.p_uid)
                    except KeyError:
                        log.warning(f'unknown child pid {died_pid} exited!')
                        proc = None

                if proc is None:
                    continue

                ecode = os.waitstatus_to_exitcode(exit_status)
                log.info(f'p_uid: {proc.props.p_uid} pid: {died_pid} ecode={ecode}')
                resp = dmsg.SHProcessExit(tag=get_new_tag(), exit_code=ecode, p_uid=proc.props.p_uid)

                if proc.props.p_uid != dfacts.GS_PUID:
                    if proc.props.r_c_uid is None:
                        self.gs_in.send(resp.serialize())
                        log.info(f'transmit {repr(resp)} via gs_in')
                    else:
                        r_c_uid = proc.props.r_c_uid
                        self._send_response(target_uid=r_c_uid, msg=resp)
                        log.info(f'transmit {repr(resp)} via _send_response')

                # If we haven't received SHTeardown yet
                if proc.props.critical and not self.check_shutdown():
                    if proc.props.p_uid == dfacts.GS_PUID:
                        # if this is GS and we haven't received GSHalted yet and SHTeardown
                        # has not been received then this is an abnormal termination condition.
                        if self.is_primary and (not self.check_gs_shutdown()) and not self.check_shutdown():
                            # Signal abnormal termination and notify Launcher BE
                            err_msg = f'LS watch death - GS exited - puid {proc.props.p_uid}'
                            self._abnormal_termination(err_msg)
                    elif dfacts.is_transport_puid(proc.props.p_uid):
                        if (not self.check_ta_shutdown()) and (not self.check_shutdown()):
                            err_msg = f'LS watch death - TA exited - puid {proc.props.p_uid}'
                            self._abnormal_termination(err_msg)
                    else:
                        # Signal abnormal termination and notify Launcher BE
                        err_msg = f'LS watch death - critical process exited - puid {proc.props.p_uid}'
                        self._abnormal_termination(err_msg)

                try:  # keep subprocess from giving spurious ResourceWarning
                    proc.wait(0)
                    # Remember to close any open connections for stdout and stderr.
                    # If they weren't opened, the close methods will handle that. The
                    # underlying channel will be decref'ed when the SHProcessExit is
                    # received by global services (see server.py in GS).
                    if proc.props.stdout_connector is not None:
                        self.exited_channel_output_monitors.put(proc.props.stdout_connector)
                    if proc.props.stderr_connector is not None:
                        self.exited_channel_output_monitors.put(proc.props.stderr_connector)
                except OSError:
                    pass
            else:
                time.sleep(self.SHUTDOWN_RESP_TIMEOUT)

        log.info('exit')

    def update_watch_set(self, connectors, dead_connector):
        changed = False
        while not self.new_channel_input_monitors.empty():
            changed = True
            connector = self.new_channel_input_monitors.get()
            connectors.add(connector)

        if dead_connector is not None:
            changed = True
            connectors.discard(dead_connector)

        return changed

    def watch_input(self):
        """Thread monitors inbound traffic directed to stdin of a process."""

        log = logging.getLogger('watch input')

        log.info('starting')

        connectors = set()
        channel_set = None
        dead_connector = None

        # Gets us the default pool.
        node_index = parms.this_process.index
        def_muid = dfacts.default_pool_muid_from_index(node_index)
        def_pool = self.pools[def_muid]

        while not self.check_shutdown():
            EOF = False

            new_channel_set_needed = self.update_watch_set(connectors, dead_connector)

            if len(connectors) == 0:
                time.sleep(self.SHUTDOWN_RESP_TIMEOUT)
                if channel_set is not None:
                    del channel_set
                    channel_set = None
            else:
                try:
                    if new_channel_set_needed:
                        del channel_set
                        channel_list = [connector.conn.inbound_channel for connector in connectors]
                        channel_set = dch.ChannelSet(def_pool, channel_list)

                    dead_connector = None

                    connector = None
                    channel, event = channel_set.poll(self.SHUTDOWN_RESP_TIMEOUT)
                    connector = self.cuid_to_input_connector[channel.cuid]
                    if event == dch.POLLIN:
                        EOF = connector.forward()

                    if EOF or event == dch.POLLNOTHING or not connector.proc_is_alive:
                        dead_connector = connector
                        connector.close()


                except dch.ChannelSetTimeout:
                    pass
                except Exception as ex:
                    # Any error is likely due to the child exiting
                    log.info(f'InputConnector Error:{repr(ex)}')
                    try:
                        if connector is not None:
                            dead_connector = connector
                            connector.close()
                    except:
                        pass

        log.info('exiting')


    def watch_output(self):
        """Thread monitors outbound std* activity from processes we started.

            Any stderr activity on a 'critical' (e.g. infrastructure) process
            running under this shepherd will cause an error shutdown.

        :return: None, exits on self.check_shutdown()
        """
        log = logging.getLogger('watch output')

        log.info('starting')
        p_hostname = self.hostname

        class WatchingSelector(selectors.DefaultSelector):
            """Enhanced DefaultSelector to register stdout/stderr of PopenProps

            Automates registering the file handles with the selector base class
            and maps it to an OutputConnector object to handle the logic for
            forwarding data where it needs to go.
            """

            def add_proc_streams(self, server, proc: PopenProps):
                # carried data is (ProcessProps, closure to make SHFwdOutput, whether stderr or not)
                try:
                    self.register(proc.stdout, selectors.EVENT_READ,
                                  data=proc.props.stdout_connector)
                except ValueError:  # file handle could be closed or None: a race, so must catch
                    pass
                except KeyError as ke:  # already registered
                    self.unregister(proc.stdout)
                    #log.warning(f'ke={ke}, proc.stdout={proc.stdout}, new props={proc.props}')
                    self.register(proc.stdout, selectors.EVENT_READ,
                                  data=proc.props.stdout_connector)

                try:
                    self.register(proc.stderr, selectors.EVENT_READ,
                                  data=proc.props.stderr_connector)
                except ValueError:
                    pass
                except KeyError as ke:
                    self.unregister(proc.stderr)
                    #log.warning(f'ke={ke}, proc.stderr={proc.stderr}, new props={proc.props}')
                    self.register(proc.stderr, selectors.EVENT_READ,
                                  data=proc.props.stderr_connector)

        stream_sel = WatchingSelector()

        while not self.check_shutdown():
            work = stream_sel.select(timeout=self.SHUTDOWN_RESP_TIMEOUT)

            for sel_k, _ in work:
                output_connector = sel_k.data

                try:
                    EOF = output_connector.flush()
                except TerminationException as ex:
                    EOF = False
                    handled = False
                    str_data = str(ex)
                    try:  # did we get a GSHalted?
                        msg = dmsg.parse(str_data)
                        if isinstance(msg, dmsg.GSHalted):
                            handled = True
                            self._DTBL[dmsg.GSHalted][0](self, msg=msg)
                            EOF = True
                    except json.JSONDecodeError:
                        pass

                    if not handled:
                        err_msg = f'output from critical puid {output_connector.puid}'
                        log.error(err_msg)
                        log.error(f'output is:\n{str_data}\n')
                        # Signal abnormal termination and notify Launcher BE
                        self._abnormal_termination(err_msg)

                if EOF:
                    stream_sel.unregister(output_connector.file_obj)
                    output_connector.close()

            if self.check_shutdown():
                break

            try:
                while True:
                    new_proc = self.new_procs.get_nowait()
                    stream_sel.add_proc_streams(self, new_proc)
            except queue.Empty:
                pass
            except ValueError: # The file was closed, possible race condition.
                pass

            try:
                while True:
                    exited_proc_connector = self.exited_channel_output_monitors.get_nowait()
                    stream_sel.unregister(exited_proc_connector.file_obj)
                    exited_proc_connector.close()
            except queue.Empty:
                pass
            except ValueError: # The file was closed, possible race condition.
                pass

        stream_sel.close()
        log.info('exit')
