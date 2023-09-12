import argparse
import os
import re

from .wlm import WLM
from ..dlogging import util as dlogutil
from ..infrastructure.facts import TransportAgentOptions


# The argparse module automatically formats the help strings below so you don't have to
# worry about formatting them when editing.

VERSION = f'''
Dragon Version {os.environ.get('DRAGON_VERSION', '(unknown)')}
'''

PROGRAM_HELP = '''PROG specifies an executable program to be run on the primary
compute node. In this case, the file may be either executable or not.
If PROG is not executable, then Python version 3 will be used to
interpret it. All command-line arguments after PROG are passed
to the program as its arguments. The PROG and ARGS are optional.'''

ARG_HELP = '''Zero or more program arguments may be specified.'''

SINGLE_MODE_HELP = '''Override automatic launcher selection to force use of the
single node launcher'''

MULTI_MODE_HELP = '''Override automatic launcher selection to force use of the
multi-node launcher'''

NODES_HELP = '''NODE_COUNT specifies the number of nodes to use. NODE_COUNT must
be less or equal to the number of available nodes within the WLM allocation.
A value of zero (0) indicates that all available nodes should be used (the default).'''

NETWORK_HELP = '''NETWORK_PREFIX specifies the network prefix the dragon runtime will
use to determine which IP addresses it should use to build multinode connections from.
By default the regular expression r'^(hsn|ipogif|ib)\d+$' is used -- the prefix for known
HPE-Cray XC and EX high speed networks. If uncertain which networks are available,
the following will return them in pretty formatting:
`dragon-network-ifaddrs --ip --no-loopback --up --running | jq`.
Prepending with `srun` may be necessary to get networks available on backend
compute nodes'''

NETWORK_CONFIG_HELP = '''NETWORK_CONFIG specifies a YAML or JSON file generated via a call to the
launcher's network config tool that successfully generated a corresponding YAML
or JSON file (eg: `dragon-network-config --output-to-yaml`)
describing the available backend compute nodes specified either by a workload
manager (this is what the tool provides). Alternatively, one can be generated
manually as is needed in the case of ssh-only launch. An example with keywords
and formatting can be found in the documentation'''

HOSTFILE_HELP = \
    '''
    Specify a list of hostnames to connect to via SSH launch. The file
    should be a newline character separated list of hostnames.
    `--hostfile` or `--hostlist` is a required argument for WLM SSH
    and is only used for SSH
    '''

HOSTLIST_HELP = \
    '''
    Specify backend hostnames as a comma-separated list, eg:
    `--hostlist host_1,host_2,host_3`.
    `--hostfile` or `--hostlist` is a required argument for WLM SSH
    and is only used for SSH
    '''

WLM_HELP = f"""Specify what workload manager is used. Currently supported WLMs are: {', '.join([wlm.value for wlm in WLM])}"""

# NOTE: port 7575 is hardcoded rather than grabbed from facts.py because we
# NOTE: DO NOT want to import dragon when launchargs is imported.
PORT_HELP = '''PORT specifies the port to be used for multinode communication. By
default, 7575 is used.'''

LOGGING_HELP = '''The Dragon runtime enables the output of diagnostic log messages to multiple
different output devices. Diagnotic log messages can be seen on the Dragon stderr
console, via a combined 'dragon_*.log' file, or via individual log files created by
each of the Dragon 'actors' (Global Services, Local Services, etc).

By default, the Dragon runtime disables all diagnostic log messaging.

Passing one of NONE, DEBUG, INFO, WARNING, ERROR, or CRITICAL to this option,
the Dragon runtime will enable the specified log verbosity. When enabling DEBUG
level logging, the Dragon runtime will limit the stderr and combined dragon log file
to INFO level messages. Each actor's log file will contain the complete log history,
including DEBUG messages. This is done to help limit the number of messages sent
between the Dragon frontend and the Dragon backend at scale.

To override the default logging behavior and enable specific logging to one or
more Dragon output devices, the LOG_LEVEL option can be formatted as a keyword=value
pair, where the KEYWORD is one of the Dragon log output devices (stderr, dragon_file
or actor_file), and the VALUE is one of NONE, DEBUG, INFO, WARNING, ERROR or
CRITICAL (eg `-l dragon_file=INFO -l actor_file=DEBUG`). Multiple -l|--log-level
options may be passed to enable the logging desired.'''

TRANSPORT_HELP = f'''TRANSPORT_AGENT selects which transport agent will be used for
backend node-to-node communication. By default, the TCP transport agent
is selected. Currently supported agents are: {', '.join([ta.value for ta in TransportAgentOptions])}'''


class SplitArgsAtComma(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, [v.strip() for v in values.split(',')])


def non_negative_int(value):
    nvalue = int(value)
    if nvalue < 0:
        raise argparse.ArgumentTypeError(f"{value} must be zero or a positive int value")
    return nvalue


def valid_port_int(value):
    port = int(value)
    if port < 1024 or port > 65536:
        raise argparse.ArgumentTypeError(f"{value} must be in port range 1024-65535")
    return port


def is_hostname_valid(hostname):
    """Confirm hostname conforms to POSIX rules"""
    if len(hostname) > 255:
        return False
    if hostname[-1] == ".":
        hostname = hostname[:-1]  # strip exactly one dot from the right, if present
    allowed = re.compile(r"(?!-)[A-Z\d-]{1,63}(?<!-)$", re.IGNORECASE)
    return all(allowed.match(x) for x in hostname.split("."))


def parse_hosts(hostlist, hostfile):
    """Parse the hostfile if one is given and hostnames are valid"""

    if hostlist is None and hostfile is None:
        raise argparse.ArgumentError(hostlist, "When using WLM SSH, hostlist, hostfile, or existing network configuration is required.")
    else:
        # parse the hostfile if its set
        if hostfile is not None:
            try:
                with open(hostfile, 'r') as f:
                    hostlist = [line.strip() for line in f.readlines()]
            except Exception:
                raise argparse.ArgumentError(hostfile, f'Unable to parse {hostfile}')

    # Do a basic sanity check that the hostnames make sense
    try:
        for host in hostlist:
            if not is_hostname_valid(host):
                raise ValueError(f"Hostname is invalid: {host}")
    except Exception:
        raise

    return hostlist


def get_parser():

    from .network_config import WLM_HELP

    parser = argparse.ArgumentParser(prog='dragon',
                                     description='Dragon Launcher Arguments and Options')
    parser.add_argument('-N', '--nodes', metavar='NODE_COUNT', dest='node_count',
                        type=non_negative_int, help=NODES_HELP)

    host_group = parser.add_mutually_exclusive_group()
    host_group.add_argument('--hostlist', action=SplitArgsAtComma, metavar='HOSTLIST', type=str, help=HOSTLIST_HELP)
    host_group.add_argument('--hostfile', type=str, metavar='HOSTFILE', help=HOSTFILE_HELP)

    parser.add_argument('--network-prefix', metavar='NETWORK_PREFIX',
                        type=str, help=NETWORK_HELP)
    parser.add_argument('--network-config', metavar='NETWORK_CONFIG',
                        type=str, help=NETWORK_CONFIG_HELP)
    parser.add_argument('--wlm', '-w', metavar='WORKLOAD_MANAGER', type=WLM.from_str, choices=list(WLM), help=WLM_HELP)
    parser.add_argument('-p', '--port', metavar='PORT', type=valid_port_int, help=PORT_HELP)

    parser.add_argument('--transport', '-t', metavar='TRANSPORT_AGENT',
                        type=TransportAgentOptions.from_str, choices=list(TransportAgentOptions), help=TRANSPORT_HELP)

    group = parser.add_mutually_exclusive_group()
    group.add_argument('-s', '--single-node-override',
                       action='store_true', help=SINGLE_MODE_HELP)
    group.add_argument('-m', '--multi-node-override', action='store_true', help=MULTI_MODE_HELP)

    parser.add_argument('-l', '--log-level', nargs=1, default=dict(), action=dlogutil.LoggingValue,
                        dest='log_device_level_map', metavar='LOG_LEVEL', help=LOGGING_HELP)
    parser.add_argument('--no-label', action='store_true', default=True)
    parser.add_argument('--basic-label', action='store_true')
    parser.add_argument('--verbose-label', action='store_true')

    parser.add_argument('--version', action='version', version=VERSION)

    parser.add_argument('prog', type=str, nargs='?', metavar='PROG', help=PROGRAM_HELP)
    parser.add_argument('args', type=str, metavar='ARG', nargs=argparse.REMAINDER,
                        default=[], help=ARG_HELP)

    parser.set_defaults(
        transport=TransportAgentOptions.TCP,
    )

    return parser


def get_args(args_input=None):
    try:
        parser = get_parser()
        if args_input is None:
            args = parser.parse_args()
        else:
            args = parser.parse_args(args_input)

        # Override default no-label if higher verbosity selected
        if args.basic_label or args.verbose_label:
            args.no_label = False

        return {key: value for key, value in vars(args).items() if value is not None}

    except Exception:
        raise


def head_proc_args(args_map=None):
    if args_map is None:
        args_map = get_args()
    head_proc = args_map.get('prog')
    head_args = [head_proc]
    head_args.extend(args_map.get('args'))
    return head_proc, head_args
