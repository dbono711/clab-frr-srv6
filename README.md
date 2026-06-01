# clab-frr-srv6

## Overview

A Segment Routing IPv6 (SRv6) network using [CONTAINERlab](https://containerlab.dev/) and [FRRouting (FRR)](https://frrouting.org/) nodes to demonstrate [SRv6](https://docs.frrouting.org/en/latest/zebra.html#segment-routing-ipv6) capabilities in a controlled lab environment. This lab provides a practical environment for learning and testing basic SRv6 concepts including locator blocks, SRv6 transport for BGP L3VPN (IPv4 & IPv6) services, and SRv6 functions and behaviors.

## Requirements

- [CONTAINERlab](https://containerlab.dev/install/)
  - _The [CONTAINERlab](https://containerlab.dev/install/) installation guide outlines various installation methods. This lab assumes all [pre-requisites](https://containerlab.dev/install/#pre-requisites) (including Docker) are met and CONTAINERlab is installed via the [install script](https://containerlab.dev/install/#install-script)._
- Docker FRR image: `quay.io/frrouting/frr:master` (will be downloaded automatically)
- Docker Network Multitool image: `wbitt/network-multitool:alpine-extra` (for client nodes) (will be downloaded automatically)

## Topology

```mermaid
graph TD
  pe1---p1
  p1---p2
  p1---p3
  p1---rrv4
  p2---p4
  p3---p4
  p2---rrv6
  pe2---p4
  pe1---c1
  pe2---c2
```

## Network Resources

- SRv6 uSID locator ("Loc0") for Flex-Algo 0 (IGP SPF) in uSID format f3216 (max of 6 uSIDs can be encoded in a single IPv6 address):
  - fcdd:dd00:01xx::/48, where x is the node identifier (e.g., fcdd:dd00:0101::/48 for pe1)
    - uSID block (32 bits) (fcdd:dd00::/32)
      - Base SRv6 locator prefix (network wide) (24 bits) (fcdd:dd::/24)
      - General use identifier (4 bits) (fcdd:dd0::/28)
      - Flex-Algo identifier (4 bits) (fcdd:dd00::/32)
    - Domain identifier (8 bits) (fcdd:dd00:01::/40)
    - Node identifier (8 bits) (fcdd:dd00:0101::/48)
    - This allows our domain's SRv6 SIDs to be summarized per flex-algo at the /40 prefix length
- The IPv4 loopback addresses are allocated from the 172.16.0.0/24 subnet and follow the format:
  - 172.16.0.y/32 where y is assigned incrementally per device (e.g., 172.16.0.1/32 for pe1)
- The IPv6 loopback addresses are derived from the Flex-Algo 0 ("Loc0") locator block incrementally
  - So, if the locator block on router pe1 is fcdd:dd00:0101::/48, then the IPv6 loopback address is fcdd:dd00:0101::1/128
- The IPv4 interface addresses are allocated from the 172.16.10.0/24 subnet and follow the format:
  - 172.16.10.y/31 where x variez per link
- The IPv6 interface addresses are allocated from the 2001:c0de:1::/48 subnet follow the format:
  - 2001:c0de:1:y::z/64 where y and z vary per link
- All routers are part of IS-IS Level 2 with IS-IS NET addresses following the format, based on the IPv4 loopback:
  - 49.0001.xxxx.xxxx.xxxx.00 (e.g., 49.0001.1721.6000.0001.00 for pe1)
- BGP is configured on the PEs (pe1 and pe2) with ASN 65000

### Management Network

The following IP addresses are assigned to the containerLAB nodes for management:

| Node      | Management IP   |
|-----------|----------------|
| pe1       | 172.28.1.2/24  |
| pe2       | 172.28.1.3/24  |
| p1        | 172.28.1.4/24  |
| p2        | 172.28.1.5/24  |
| p3        | 172.28.1.6/24  |
| p4        | 172.28.1.7/24  |
| rrv6      | 172.28.1.8/24  |
| bdr1      | 172.28.1.15/24 |
| c1        | 172.28.1.9/24  |
| c2        | 172.28.1.10/24 |
| c3        | 172.28.1.11/24 |
| promtail  | 172.28.1.12/24 |
| loki      | 172.28.1.13/24 |
| grafana   | 172.28.1.14/24 |
| prometheus| 172.28.1.15/24 |

## SRv6-based L3VPN Services

This lab demonstrates SRv6 as a transport for L3VPN services, showcasing how SRv6 can replace traditional MPLS-based transport:

- One single SID is needed
- No new protcol (just BGP)
  - No new SAFI
- Automated
  - No tunnel to configure
- SRv6 for everything
  - No other protocol, just IPv6 with SRv6 (not even SRH required due to use of uSID)

### SRv6 Setup

- **SRv6 Locators**: Each SRv6 particpating router (pe1 and pe2) have a unique SRv6 locator block that serves as the foundation for SRv6 functions
- **uSID Format**: The lab uses micro-segment identifiers (uSID) with block-len 32, node-len 16, func-bits 16 format for efficient segment encoding
- **SRv6 Encapsulation Behavior**: The main BGP process includes `segment-routing srv6` with `locator Loc0` and `encap-behavior H_Encaps_Red` configuration, which defines how VPN traffic is encapsulated into SRv6 packets. The `H_Encaps_Red` behavior specifically indicates that the router performs SRv6 header encapsulation with reduced SRH (Segment Routing Header) for VPN traffic
- **VPN SID Generation**: PE routers (pe1 and pe2) use `sid vpn per-vrf export auto` under each BGP VRF process to automatically generate SRv6 SIDs for VPN services

### BGP L3VPN Setup

- **VRF Configuration**: The RED VRF is configured on both PE routers (pe1 and pe2) for IPv4 address family.
- **Client Connectivity**: Clients c1 and c2 connect to pe1 and pe2 respectively through VLAN interfaces assigned to the RED VRF.
- **Route Distinguishers**: VRF routes use router-specific RDs and share the same RT, one per VRF.
- **End-to-End Service**: The BGP L3VPN control plane exchanges routes between the VRFs, while SRv6 provides the data plane transport across the network

## Monitoring

A logging stack is deployed to collect and aggregate logs from the FRR routers and clients. The logging stack is deployed using [CONTAINERlab](https://containerlab.dev/), [Promtail](https://grafana.com/docs/loki/latest/clients/promtail/), [Loki](https://grafana.com/docs/loki/latest/), and [Grafana](https://grafana.com/).

Once the lab is deployed, the logging stack can be accessed at `http://localhost:3000`. Then navigate to the `Network Logs` dashboard.

## Deployment

Clone this repository and start the lab:

```shell
git clone https://github.com/dbono711/clab-frr-srv6.git
cd clab-frr-srv6
sudo clab deploy -t lab.yml
```

**_NOTE: CONTAINERlab requires SUDO privileges in order to execute_**

The deployment process:

- Creates the [CONTAINERlab network](lab.yml) based on the topology definition
- Applies the FRR configuration files from the respective router folders on each node
- Executes the initialization scripts for each router and client

## Accessing the Container Shell

The container shell can be accessed by using the `docker exec` command, as follows:

```shell
docker exec -it <container> bash
```

For example, to access the shell on the `pe1` FRR container:

```shell
docker exec -it clab-frr-srv6-pe1 bash
```

## Accessing the FRR CLI (vtysh)

The FRR CLI can be accessed by using the `docker exec` command, as follows:

```shell
docker exec -it <container> vtysh
```

For example, to access the FRR CLI on the `pe1` container:

```shell
docker exec -it clab-frr-srv6-pe1 vtysh
```

## Capturing Packets

Here is an example on how to capture packets directly on the host which CONTAINERlab is running:

```shell
sudo ip netns exec clab-frr-srv6-pe1 tcpdump -nni eth1
```

## Cleanup

Stop the lab and tear down the CONTAINERlab containers:

```shell
clab destroy -t lab.yml
```

## Author

- Darren Bono - [darren.bono@att.net](mailto://darren.bono@att.net)

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details
