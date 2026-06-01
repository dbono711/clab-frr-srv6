#!/bin/bash

# create logs directory
mkdir -p /etc/frr/logs
chown -R frr:frr /etc/frr/logs
chmod 775 /etc/frr/logs

# Required for SRv6 dataplane (encap/decap in the IPv6 forward path); resets to 0 on every boot
sysctl -w net.ipv6.conf.all.forwarding=1
# seg6_enabled gates seg6/seg6local processing. Off by default on every boot
sysctl -w net.ipv6.conf.all.seg6_enabled=1

# create SRv6 interface
ip link add sr0 type dummy
ip link set sr0 up

# create internet loopback interface
ip link add internet0 type dummy
ip link set internet0 up
