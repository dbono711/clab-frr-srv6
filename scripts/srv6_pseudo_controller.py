#!/usr/bin/env python3
"""Interactive pseudo-controller for ad hoc SRv6 L3VPN services.

This is a standalone operator tool. It provisions one additional VRF service on
top of an already-running lab by driving `pe1`, `pe2`, `c1` and `c2` configuration over
`docker exec`, Linux plumbing (VLAN subinterface + VRF device) via `sh`, and FRR
state (interface addressing, a static uDT4/uDT6/uDT46 SID, and the static SRv6 routes
that steer traffic down an operator-chosen path) via `vtysh`.

Unlike the RED/BLUE services in the base lab, which learn each other's prefixes
through BGP L3VPN, the services created here are statically steered. Meaning, the
operator picks the forward and reverse core paths and those hops are encoded directly
into a SRv6 uSID segment list, making it a convenient way to demonstrate explicit
traffic engineering.

Run with `--dry-run` (or answer yes to the "Dry run only?" prompt) to print the
exact command set without touching the lab.
"""

import argparse
import ipaddress
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TypeVar

LAB_NAME = "clab-frr-srv6"

# Lab short name -> container name. Short names are what the rest of this module
# passes around; the mapping is applied only at the docker boundary.
CONTAINERS = {
    "pe1": f"{LAB_NAME}-pe1",
    "pe2": f"{LAB_NAME}-pe2",
    "c1": f"{LAB_NAME}-c1",
    "c2": f"{LAB_NAME}-c2",
}

# Each PE serves exactly one client container in this lab (see lab.yml). Iterating
# this also gives the set of PEs to probe for already-allocated resources.
PE_TO_CLIENT = {"pe1": "c1", "pe2": "c2"}

# Run on each PE to collect the state the next_* allocators gather for what is
# already in use.
PROBE_COMMAND = "ip -d link show; ip -br addr; vtysh -c 'show running-config'"

# SRv6 uSID f3216 format: a 32-bit block followed by 16-bit uSIDs. Every node's
# locator is <block>:<node id>::/48, so a segment list is just the block plus one
# group per hop. See the "SRv6 locators" section of README.md.
SRV6_BLOCK = "fcdd:dd00"
LOCATOR_NAME = "MAIN"

NODE_USID_IDS = {
    "pe1": "101",
    "p1": "102",
    "p2": "103",
    "p3": "104",
    "p4": "105",
    "pe2": "106",
}

# Only the P routers may appear in a transit path; the PEs are implied as the
# endpoints.
CORE_NODES = {"p1", "p2", "p3", "p4"}

# Address-family mode -> the SRv6 decapsulation endpoint behavior the egress PE
# binds to the service SID. Also the menu of modes offered to the operator.
AF_BEHAVIORS = {"ipv4": "uDT4", "ipv6": "uDT6", "dual": "uDT46"}
AF_MODES = tuple(AF_BEHAVIORS)

# Physical link map from lab.yml, used to reject paths that ask for a hop which
# does not exist.
ADJACENCY = {
    "pe1": {"p1"},
    "p1": {"pe1", "p2", "p3", "rrv6"},
    "p2": {"p1", "p4", "bdr1"},
    "p3": {"p1", "p4"},
    "p4": {"p2", "p3", "pe2"},
    "pe2": {"p4"},
}

# A VRF name becomes a Linux device name via `ip link add dev <name> type vrf`,
# and the kernel caps those at IFNAMSIZ - 1 (net/if.h). Anything longer is
# rejected by `ip` rather than truncated, so it has to be caught before the first
# command is sent.
MAX_VRF_NAME_LEN = 15

# Resources the base lab already owns. These seed the allocators below so a new
# service can never be handed a VLAN, table or subnet that RED or BLUE is already
# using. SID functions need no seed: the base lab's are auto-allocated by FRR from
# a disjoint range (see next_function_id).
BASE_VLANS = {10, 20}
BASE_VRFS = {"RED", "BLUE"}
BASE_TABLES = {10, 20}
# Fourth octet of the 10.10.1.x/10.10.2.x /30s used by RED (.0) and BLUE (.4).
BASE_IPV4_OFFSETS = {0, 4}
# Subnet IDs of the 2001:c0de:10:X::/64s used by RED (1, 2) and BLUE (3, 4).
BASE_IPV6_SUBNET_IDS = {1, 2, 3, 4}

T = TypeVar("T")


@dataclass
class ServiceDefinition:
    """Everything needed to render the command set for one new VRF service.

    Subnets come in pe1/pe2 pairs so each PE-to-client link gets its own subnet,
    with the first address on the PE and the second on the client. The `forward_segment`
    steers pe1 -> pe2 and `reverse_segment` steers pe2 -> pe1; both terminate in the same
    `function_id`, since each PE installs that function under its own locator.
    """

    vrf_name: str
    vlan_id: int
    af_mode: str
    use_h_encaps_red: bool
    table_id: int
    function_id: str
    pe1_ipv4_subnet: ipaddress.IPv4Network
    pe2_ipv4_subnet: ipaddress.IPv4Network
    pe1_ipv6_subnet: ipaddress.IPv6Network
    pe2_ipv6_subnet: ipaddress.IPv6Network
    forward_core_nodes: list[str]
    reverse_core_nodes: list[str]
    forward_segment: str
    reverse_segment: str

    @property
    def has_ipv4(self) -> bool:
        """True when the service carries IPv4."""
        return self.af_mode in {"ipv4", "dual"}

    @property
    def has_ipv6(self) -> bool:
        """True when the service carries IPv6."""
        return self.af_mode in {"ipv6", "dual"}


class ControllerError(Exception):
    """An operator-facing failure: bad input, a missing container, or a failed command."""


def run(command: Sequence[str]) -> subprocess.CompletedProcess:
    """Run `command`, raising ControllerError with both streams attached on failure.

    Failure is never tolerated: a command that exits non-zero has left the lab
    half-configured, so the run stops rather than continuing on partial state.
    subprocess's own `check` is declined so the error can carry stdout and stderr.
    """
    proc = subprocess.run(command, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise ControllerError(
            f"Command failed: {' '.join(command)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc


def docker_exec(container: str, shell_command: str) -> subprocess.CompletedProcess:
    """Run a shell command inside `container`."""
    return run(["docker", "exec", container, "sh", "-lc", shell_command])


def vtysh(container: str, commands: Sequence[str]) -> subprocess.CompletedProcess:
    """Run FRR commands inside `container` as a single vtysh session.

    All commands share one invocation because vtysh carries the configuration
    node across successive `-c` arguments. `configure terminal` at the front
    puts the rest of the list into config mode.
    """
    cmd = ["docker", "exec", container, "vtysh"]
    for c in commands:
        cmd.extend(["-c", c])
    return run(cmd)


def prompt(text: str, parse: Callable[[str], T]) -> T:
    """Ask until `parse` accepts the answer, then return the parsed value.

    `parse` both validates and normalises (upper-casing a VRF name, converting a
    VLAN to int); it signals bad input by raising ControllerError, whose message
    is shown to the operator before re-prompting. Anything that can be retyped
    should therefore raise ControllerError rather than ValueError, or the run
    aborts instead of asking again.

    Only free-text answers come through here. Anything with a known set of valid
    answers uses choose() instead, so there is no default to fall back to.
    """
    while True:
        value = input(f"{text}: ").strip()
        if not value:
            print("Value required.")
            continue
        try:
            return parse(value)
        except ControllerError as e:
            print(f"Invalid input: {e}")


def yes_no(text: str, default: bool = False) -> bool:
    """Ask a yes/no question, returning `default` on an empty answer."""
    d = "Y/n" if default else "y/N"
    while True:
        value = input(f"{text} [{d}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Enter yes or no.")


def choose(text: str, options: Sequence[T], label: Callable[[T], str] = str, default: int = 0) -> T:
    """Present a numbered menu and return the chosen option; Enter takes `default`.

    Used wherever the valid answers are a short known set. Offering them by number
    makes an invalid answer unrepresentable, rather than accepting free text and
    rejecting it afterwards.
    """
    if not options:
        raise ControllerError(f"No options available for: {text}")
    print(f"\n{text}")
    for index, option in enumerate(options, 1):
        marker = " (default)" if index - 1 == default else ""
        print(f"  {index}) {label(option)}{marker}")
    while True:
        value = input(f"Select [1-{len(options)}]: ").strip()
        if not value:
            return options[default]
        if value.isdigit() and 1 <= int(value) <= len(options):
            return options[int(value) - 1]
        print(f"Enter a number between 1 and {len(options)}.")


def parse_vrf_name(value: str) -> str:
    """Normalise a VRF name to upper case, rejecting bad syntax, over-length names and lab collisions.

    The character rule is not only cosmetic: the name is interpolated into a
    `docker exec ... sh -lc` string, so restricting it to letters, digits, '_'
    and '-' is what keeps shell metacharacters out of that command.
    """
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value):
        raise ControllerError("VRF name must start with a letter and contain only letters, numbers, '_' or '-'.")
    if len(value) > MAX_VRF_NAME_LEN:
        raise ControllerError(
            f"VRF name must be at most {MAX_VRF_NAME_LEN} characters "
            f"(Linux interface name limit); got {len(value)}."
        )
    name = value.upper()
    if name in BASE_VRFS:
        raise ControllerError("VRF name collides with an existing lab VRF.")
    return name


def parse_vlan_id(value: str) -> int:
    """Parse a VLAN ID, rejecting out-of-range values and the base lab's VLANs."""
    try:
        vlan = int(value)
    except ValueError:
        raise ControllerError("VLAN must be a number.") from None
    if not 2 <= vlan <= 4094:
        raise ControllerError("VLAN must be between 2 and 4094.")
    if vlan in BASE_VLANS:
        raise ControllerError("VLAN collides with existing RED/BLUE VLANs.")
    return vlan


def transit_paths(source: str, destination: str) -> list[list[str]]:
    """Enumerate every loop-free core path from `source` to `destination`.

    Returns just the P routers traversed; the PE endpoints are implied and left
    out, matching what build_segment expects. The topology is tiny -- two paths
    each way, since pe1 only reaches p1 and pe2 only reaches p4 -- so a plain
    depth-first walk of ADJACENCY is exhaustive, and enumerating up front is what
    lets the operator pick a path instead of typing one to be validated.
    """
    paths: list[list[str]] = []

    def walk(node: str, visited: tuple[str, ...], core_nodes: list[str]) -> None:
        for neighbor in sorted(ADJACENCY[node]):
            if neighbor == destination:
                paths.append(core_nodes)
            elif neighbor in CORE_NODES and neighbor not in visited:
                walk(neighbor, visited + (neighbor,), core_nodes + [neighbor])

    walk(source, (source,), [])
    return paths


def ensure_containers_running(containers: Iterable[str]) -> None:
    """Verify every named container is up, using a single `docker ps` call."""
    running = set(run(["docker", "ps", "--format", "{{.Names}}"]).stdout.splitlines())
    missing = [c for c in containers if c not in running]
    if missing:
        raise ControllerError(f"Containers not running: {', '.join(missing)}")


def get_existing_pe_runtime() -> str:
    """Scrape both PEs' live state as one text blob for the next_* allocators to mine.

    Link detail, addressing and FRR running-config are concatenated so a single
    pass of regexes can find already-consumed VRF tables, SID functions and
    subnets.

    Both PEs are unioned into one blob rather than tracked separately, because
    every resource allocated here is shared between them (the same table ID, the
    same SID function (installed under each node's own locator), and one half of
    each subnet pair). A combined view can only widen the used-set, so it can never
    hand out something already in service on either PE. Probing pe2 as well is
    what catches configuration applied to pe2 out of band, which pe1's state would
    otherwise never reveal.
    """
    return "\n".join(docker_exec(CONTAINERS[pe], PROBE_COMMAND).stdout for pe in PE_TO_CLIENT)


def next_table_id(runtime_text: str) -> int:
    """Return the next free Linux VRF table ID, counting up from 30 in tens.

    Matches the `vrf table N` token that `ip -d link show` prints for every VRF
    device, which also covers the `ip link add dev X type vrf table N` form should
    the probe ever include shell text. Enslaved interfaces report `vrf_slave
    table N` and are correctly skipped.
    """
    used = set(BASE_TABLES)
    used.update(int(match.group(1)) for match in re.finditer(r"\bvrf table\s+(\d+)", runtime_text))
    candidate = 30
    while candidate in used:
        candidate += 10
    return candidate


def next_function_id(runtime_text: str) -> str:
    """Return the next free feXX SID function, scanning static SIDs under either PE's locator.

    A service installs the same function on both PEs, each under its own locator,
    so a SID seen beneath either node's uSID marks that function as consumed.

    Nothing is reserved up front. The base lab's RED/BLUE SIDs are auto-allocated
    by FRR (`sid vpn per-vrf export auto`) from a separate range starting at e000
    -- see the remoteTransposedSid values in ROUTE-EXPORT-VALIDATION.md -- so the
    feXX space this walks is free by construction, and only static SIDs already
    placed here can take a slot.
    """
    pe_usids = "|".join(NODE_USID_IDS[pe] for pe in PE_TO_CLIENT)
    pattern = re.compile(rf"sid\s+{SRV6_BLOCK}:(?:{pe_usids}):(fe[0-9a-f][0-9a-f])::/64", re.IGNORECASE)
    used = {match.group(1).lower() for match in pattern.finditer(runtime_text)}
    for idx in range(0x100):
        candidate = f"fe{idx:02x}"
        if candidate not in used:
            return candidate
    raise ControllerError("Exhausted feXX function allocation space.")


def next_ipv4_pair(runtime_text: str) -> tuple[ipaddress.IPv4Network, ipaddress.IPv4Network]:
    """Return the next free (pe1, pe2) IPv4 /30 pair from 10.10.1.x / 10.10.2.x.

    Both sides share the same fourth-octet offset, so RED is .0 on each PE, BLUE
    is .4, and new services continue in steps of four.
    """
    used_offsets = set(BASE_IPV4_OFFSETS)
    used_offsets.update(
        int(match.group(1)) for match in re.finditer(r"\b10\.10\.[12]\.(\d+)/30\b", runtime_text)
    )
    offset = 8
    while offset in used_offsets:
        offset += 4
    return (
        ipaddress.ip_network(f"10.10.1.{offset}/30"),
        ipaddress.ip_network(f"10.10.2.{offset}/30"),
    )


def next_ipv6_pair(runtime_text: str) -> tuple[ipaddress.IPv6Network, ipaddress.IPv6Network]:
    """Return the next free (pe1, pe2) IPv6 /64 pair from 2001:c0de:10:X::/64.

    Unlike IPv4 the two sides take consecutive subnet IDs (RED is 1 and 2, BLUE
    is 3 and 4), so this walks forward until both halves of a pair are free.

    The pattern needs a literal `X::/64`, which an interface address such as
    `2001:c0de:10:5::1/64` does not match -- a subnet is only seen where it
    appears as a static route destination, i.e. in the *other* PE's config. Since
    both PEs are probed, each half is found that way; the pair-check then also
    covers the case where only one half is visible.
    """
    used_ids = set(BASE_IPV6_SUBNET_IDS)
    pattern = re.compile(r"2001:c0de:10:([0-9a-f]+)::/64", re.IGNORECASE)
    used_ids.update(int(match.group(1), 16) for match in pattern.finditer(runtime_text))
    current = 5
    while current in used_ids or (current + 1) in used_ids:
        current += 2
    return (
        ipaddress.ip_network(f"2001:c0de:10:{current:x}::/64"),
        ipaddress.ip_network(f"2001:c0de:10:{current + 1:x}::/64"),
    )


def build_segment(nodes: list[str], remote_pe: str, function_id: str) -> str:
    """Encode a uSID segment list: SRv6 block, one uSID per transit hop, then the egress PE and its function."""
    ids = [NODE_USID_IDS[n] for n in nodes]
    ids.append(NODE_USID_IDS[remote_pe])
    ids.append(function_id)
    return f"{SRV6_BLOCK}:{':'.join(ids)}::"


def route_commands(service: ServiceDefinition, pe: str) -> list[str]:
    """Static routes on `pe` sending the far end's subnets down the encoded segment list.

    H_Encaps_Red omits the first segment from the pushed SRH. So, it is carried in
    the outer IPv6 destination address instead, which is optional here and left
    to the operator.
    """
    encap = " encap-behavior H_Encaps_Red" if service.use_h_encaps_red else ""
    if pe == "pe1":
        ipv4_remote, ipv6_remote, segment = (
            service.pe2_ipv4_subnet,
            service.pe2_ipv6_subnet,
            service.forward_segment,
        )
    else:
        ipv4_remote, ipv6_remote, segment = (
            service.pe1_ipv4_subnet,
            service.pe1_ipv6_subnet,
            service.reverse_segment,
        )

    commands: list[str] = []
    if service.has_ipv4:
        commands.append(f"ip route {ipv4_remote} sr0 vrf {service.vrf_name} segments {segment}{encap} nexthop-vrf default")
    if service.has_ipv6:
        commands.append(f"ipv6 route {ipv6_remote} sr0 vrf {service.vrf_name} segments {segment}{encap} nexthop-vrf default")
    return commands


def linux_pe_commands(service: ServiceDefinition) -> list[str]:
    """Linux plumbing for the new service on a PE; identical on both PEs.

    Creates a VLAN subinterface off the client-facing interface, enslaved to a fresh
    VRF device. strict_mode has to be re-applied because the kernel resets it to 0 whenever a
    VRF is created, which would otherwise block FRR from installing End.DT4/uDT4.
    """
    return [
        f"ip link add name eth3.{service.vlan_id} link eth3 type vlan id {service.vlan_id}",
        f"ip link set dev eth3.{service.vlan_id} up",
        f"ip link add dev {service.vrf_name} type vrf table {service.table_id}",
        f"ip link set dev {service.vrf_name} up",
        f"ip link set dev eth3.{service.vlan_id} master {service.vrf_name}",
        "sysctl -w net.vrf.strict_mode=1",
    ]


def linux_client_commands(service: ServiceDefinition, client: str) -> list[str]:
    """VLAN subinterface, addressing and a route to the far-end subnet on a client."""
    if client == "c1":
        local_ipv4, remote_ipv4 = service.pe1_ipv4_subnet, service.pe2_ipv4_subnet
        local_ipv6, remote_ipv6 = service.pe1_ipv6_subnet, service.pe2_ipv6_subnet
    else:
        local_ipv4, remote_ipv4 = service.pe2_ipv4_subnet, service.pe1_ipv4_subnet
        local_ipv6, remote_ipv6 = service.pe2_ipv6_subnet, service.pe1_ipv6_subnet

    commands = [
        f"ip link add name eth1.{service.vlan_id} link eth1 type vlan id {service.vlan_id}",
        f"ip link set dev eth1.{service.vlan_id} up",
    ]
    if service.has_ipv4:
        commands.extend([
            f"ip addr add {local_ipv4[2]}/{local_ipv4.prefixlen} dev eth1.{service.vlan_id}",
            f"ip route add {remote_ipv4} via {local_ipv4[1]}",
        ])
    if service.has_ipv6:
        commands.extend([
            f"ip addr add {local_ipv6[2]}/{local_ipv6.prefixlen} dev eth1.{service.vlan_id}",
            f"ip route add {remote_ipv6} via {local_ipv6[1]}",
        ])
    return commands


def frr_pe_commands(service: ServiceDefinition, pe: str) -> list[str]:
    """FRR configuration for the new service on `pe`.

    Declares the VRF, addresses the client-facing subinterface with the first
    address of the local subnet, installs the decap SID for this service under
    the node's own locator, and finally adds the steered routes.
    """
    sid = f"{SRV6_BLOCK}:{NODE_USID_IDS[pe]}:{service.function_id}::/64"
    local_ipv4 = service.pe1_ipv4_subnet if pe == "pe1" else service.pe2_ipv4_subnet
    local_ipv6 = service.pe1_ipv6_subnet if pe == "pe1" else service.pe2_ipv6_subnet

    commands = [
        "configure terminal",
        f"vrf {service.vrf_name}",
        "exit-vrf",
        f"interface eth3.{service.vlan_id}",
        f" description to_{PE_TO_CLIENT[pe]}_eth1.{service.vlan_id}_VRF_{service.vrf_name}",
    ]
    if service.has_ipv4:
        commands.append(f" ip address {local_ipv4[1]}/{local_ipv4.prefixlen}")
    if service.has_ipv6:
        commands.append(f" ipv6 address {local_ipv6[1]}/{local_ipv6.prefixlen}")
    commands.extend([
        "exit",
        "segment-routing",
        " srv6",
        "  static-sids",
        f"   sid {sid} locator {LOCATOR_NAME} behavior {AF_BEHAVIORS[service.af_mode]} vrf {service.vrf_name}",
        "  exit",
        " exit",
        "exit",
    ])
    commands.extend(route_commands(service, pe))
    return commands


def summarize(service: ServiceDefinition) -> None:
    """Print the resolved service for the operator to review before anything is applied."""
    print(
        f"""
=== Service Summary ===
VRF: {service.vrf_name}
VLAN: {service.vlan_id}
AF mode: {service.af_mode}
VRF table: {service.table_id}
SID function: {service.function_id}
PE1 IPv4 subnet: {service.pe1_ipv4_subnet}
PE2 IPv4 subnet: {service.pe2_ipv4_subnet}
PE1 IPv6 subnet: {service.pe1_ipv6_subnet}
PE2 IPv6 subnet: {service.pe2_ipv6_subnet}
Forward core nodes: {','.join(service.forward_core_nodes)}
Reverse core nodes: {','.join(service.reverse_core_nodes)}
Forward segment: {service.forward_segment}
Reverse segment: {service.reverse_segment}
Use H_Encaps_Red: {service.use_h_encaps_red}"""
    )


def apply_shell_commands(node: str, commands: list[str], dry_run: bool) -> None:
    """Echo and, unless dry running, execute shell commands on `node` one at a time.

    `node` is a lab short name ("pe1", "c1"); CONTAINERS maps it to the container
    at the docker boundary so the echoed transcript stays readable.
    """
    for command in commands:
        print(f"[{node}] $ {command}")
        if not dry_run:
            docker_exec(CONTAINERS[node], command)


def apply_vtysh_commands(node: str, commands: list[str], dry_run: bool) -> None:
    """Echo FRR commands for `node` individually, but apply them as one vtysh session.

    They cannot be sent separately: the config node set up by `configure terminal`
    and the `interface`/`segment-routing` stanzas only persists within a session.
    Takes the same lab short name as apply_shell_commands.
    """
    for command in commands:
        print(f"[{node}] vtysh -c {command}")
    if not dry_run:
        vtysh(CONTAINERS[node], commands)


def build_service_definition() -> ServiceDefinition:
    """Interview the operator and allocate the resources for one new service."""
    runtime = get_existing_pe_runtime()

    vrf_name = prompt("VRF name", parse_vrf_name)
    vlan_id = prompt("VLAN ID", parse_vlan_id)
    af_mode = choose("Address-family mode", AF_MODES, default=AF_MODES.index("dual"))
    use_h_encaps_red = yes_no("Use encap-behavior H_Encaps_Red?", default=False)

    forward_core_nodes = choose(
        "Forward transit path from pe1 to pe2", transit_paths("pe1", "pe2"), label=",".join
    )
    reverse_core_nodes = choose(
        "Reverse transit path from pe2 to pe1", transit_paths("pe2", "pe1"), label=",".join
    )

    table_id = next_table_id(runtime)
    function_id = next_function_id(runtime)
    pe1_ipv4_subnet, pe2_ipv4_subnet = next_ipv4_pair(runtime)
    pe1_ipv6_subnet, pe2_ipv6_subnet = next_ipv6_pair(runtime)

    return ServiceDefinition(
        vrf_name=vrf_name,
        vlan_id=vlan_id,
        af_mode=af_mode,
        use_h_encaps_red=use_h_encaps_red,
        table_id=table_id,
        function_id=function_id,
        pe1_ipv4_subnet=pe1_ipv4_subnet,
        pe2_ipv4_subnet=pe2_ipv4_subnet,
        pe1_ipv6_subnet=pe1_ipv6_subnet,
        pe2_ipv6_subnet=pe2_ipv6_subnet,
        forward_core_nodes=forward_core_nodes,
        reverse_core_nodes=reverse_core_nodes,
        forward_segment=build_segment(forward_core_nodes, remote_pe="pe2", function_id=function_id),
        reverse_segment=build_segment(reverse_core_nodes, remote_pe="pe1", function_id=function_id),
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="SRv6 pseudo-controller for live static VRF services")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the exact commands that would be executed without applying them",
    )
    return parser.parse_args()


def main() -> int:
    """Interview, summarise, then apply (or print) the service across all four nodes."""
    args = parse_args()
    try:
        ensure_containers_running(CONTAINERS.values())

        service = build_service_definition()
        summarize(service)

        dry_run = args.dry_run or yes_no("Dry run only?", default=True)
        if dry_run:
            print("\n=== DRY RUN: commands will be printed but not executed ===\n")
        elif not yes_no("Proceed with live configuration?", default=False):
            print("Aborted.")
            return 0

        # Linux plumbing first: FRR can only address eth3.<vlan> and bind the SID
        # once the subinterface and VRF device exist.
        apply_shell_commands("pe1", linux_pe_commands(service), dry_run=dry_run)
        apply_shell_commands("pe2", linux_pe_commands(service), dry_run=dry_run)
        apply_shell_commands("c1", linux_client_commands(service, "c1"), dry_run=dry_run)
        apply_shell_commands("c2", linux_client_commands(service, "c2"), dry_run=dry_run)

        apply_vtysh_commands("pe1", frr_pe_commands(service, "pe1"), dry_run=dry_run)
        apply_vtysh_commands("pe2", frr_pe_commands(service, "pe2"), dry_run=dry_run)

        print("\nDry run completed." if dry_run else "\nService creation completed.")
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except (ControllerError, ValueError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
