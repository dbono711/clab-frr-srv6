#!/bin/bash
echo "8021q" >> /etc/modules

# enable SRv6
sysctl net.ipv6.seg6_flowlabel=1
sysctl net.ipv6.conf.all.seg6_enabled=1

# enable VRF strict mode
sysctl net.vrf.strict_mode=1

# create SRv6 interface
ip link add sr0 type dummy
ip link set sr0 up

# create VLAN interface for RED service
ip link add name eth3.10 link eth3 type vlan id 10
ip link set dev eth3.10 up

# create RED VRF and attach the VLAN interface to it
ip link add dev RED type vrf table 10
ip link set dev eth3.10 master RED
ip link set dev RED up