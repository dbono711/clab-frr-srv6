#!/bin/bash
echo "8021q" >> /etc/modules

ip link add name eth3.10 link eth3 type vlan id 10
ip link set dev eth3.10 up