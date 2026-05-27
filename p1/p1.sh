#!/bin/bash

# create logs directory
mkdir -p /etc/frr/logs
chown -R frr:frr /etc/frr/logs
chmod 775 /etc/frr/logs

# enable MPLS
sysctl -w net.mpls.platform_labels=1048575

# enable MPLS on interfaces
sysctl -w net.mpls.conf.eth1.input=1
sysctl -w net.mpls.conf.eth2.input=1
sysctl -w net.mpls.conf.eth3.input=1
