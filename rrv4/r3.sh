#!/bin/bash

# create logs directory
mkdir -p /etc/frr/logs
chown -R frr:frr /etc/frr/logs
chmod 775 /etc/frr/logs

# create SRv6 interface
ip link add sr0 type dummy
ip link set sr0 up
