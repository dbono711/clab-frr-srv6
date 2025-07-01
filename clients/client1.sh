#!/bin/bash
echo "8021q" >> /etc/modules

# create VLAN interface for RED service
ip link add name eth1.10 link eth1 type vlan id 10
ip link set dev eth1.10 up
ip addr add 10.10.1.2/30 dev eth1.10
ip route add 10.10.2.0/30 via 10.10.1.1
