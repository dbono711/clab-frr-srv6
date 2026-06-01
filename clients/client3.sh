#!/bin/bash

ip link set dev eth1 up

## IPv4
ip addr add 10.11.1.2/30 dev eth1
ip route add 99.99.99.99/32 via 10.11.1.1
