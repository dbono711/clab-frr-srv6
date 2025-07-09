#!/bin/bash

# create SRv6 interface
ip link add sr0 type dummy
ip link set sr0 up
