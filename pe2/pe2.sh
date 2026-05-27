#!/bin/bash

# create logs directory
mkdir -p /etc/frr/logs
chown -R frr:frr /etc/frr/logs
chmod 775 /etc/frr/logs

# enable MPLS
sysctl -w net.mpls.platform_labels=1048575

# enable MPLS on interfaces
sysctl -w net.mpls.conf.eth1.input=1

# create SRv6 interface
ip link add sr0 type dummy
ip link set sr0 up

# The Linux kernel resets net.vrf.strict_mode to 0 whenever a
# new VRF is created or the system restarts, which prevents FRR
# from installing End.DT4
sysctl -w net.vrf.strict_mode=1

# create VLAN interface for RED service
ip link add name eth3.10 link eth3 type vlan id 10
ip link set dev eth3.10 up

# create RED VRF and attach the VLAN interface to it
ip link add dev RED type vrf table 10
ip link set dev RED up
ip link set dev eth3.10 master RED
