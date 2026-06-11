#!/bin/bash

# create VLAN interface for RED service
ip link add name eth1.10 link eth1 type vlan id 10
ip link set dev eth1.10 up

## IPv4
ip addr add 10.10.2.2/30 dev eth1.10
ip route add 10.10.1.0/30 via 10.10.2.1

## IPv6
ip addr add 2001:c0de:10:2::2/64 dev eth1.10
ip route add 2001:c0de:10:1::/64 via 2001:c0de:10:2::1
