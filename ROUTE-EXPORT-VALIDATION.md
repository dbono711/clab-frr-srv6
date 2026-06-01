# BGP VPN Route Export Validation - Complete Flow

This document outlines the step-by-step validation process from VRF route installation to BGP advertisement for MPLS L3VPN and SRv6-based VPN services. This will be the from the perspective of the pe1 router, specifically for the 10.10.1.0/30 route in the RED VRF, connected to client1.

## Step 1: Verify route is in VRF routing table
```bash
show ip route vrf RED 10.10.1.0/30
```
**Look for:** Connected route 10.10.1.0/30 via eth3.10

---

## Step 2: Verify route is imported into VRF BGP table
```bash
show bgp vrf RED ipv4 unicast 10.10.1.0/30
```
**Look for:** Route 10.10.1.0/30 with origin `?` (incomplete), this is a locally sourced route due to `redistribute connected`
- Origin: incomplete
- Weight: 32768 (locally sourced)
- Status: valid, sourced, local, best

---

## Step 3: Verify VPN SID allocation in global VPNv4 table
```bash
show bgp ipv4 vpn rd 172.16.0.1:10 10.10.1.0/30
```
**Look for:**
- Origin incomplete, metric 0, weight 32768, valid, sourced, local, best (First path received)
- Remote SID: fcdd:dd00:101::, sid structure=[32 16 16 0 16 48]
- Extended Community: RT:65000:10

---

## Step 4: Verify BGP session state
```bash
show bgp ipv4 vpn summary
```
**Look for:**
- Neighbor 172.16.0.7: State = Established, PfxSnt > 0
- Neighbor fcdd:dd00:108::1 State = Established, PfxSnt > 0

---

## Step 5: Check detailed advertisement to RRV6
```bash
show bgp ipv4 vpn neighbors fcdd:dd00:108::1 advertised-routes 10.10.1.0/30
```
**Look for:**
- Extended Community: RT:65000:10
- Originator: 172.16.0.1
- Remote SID: fcdd:dd00:101::, sid structure=[32 16 16 0 16 48]

---

## Step 6: Verify SRv6 locator and SID allocation
```bash
show segment-routing srv6 locator
```
**Look for:**
- Status: Up
- Block length, node length, function bits
- Prefix: fcdd:dd00:101::/48

```bash
show segment-routing srv6 sid
```
**Look for:** VPN SIDs allocated for VRF RED
- fcdd:dd00:101:e000::  uDT4        VRF 'RED'           bgp(0)             Loc0       dynamic

---

## Complete Flow Summary

The route export process follows this path:

1. **Kernel** → Route installed in VRF routing table
2. **BGP VRF** → Route redistributed into BGP VRF table
3. **Label/SID allocation** → MPLS label and/or SRv6 SID assigned to route
4. **VPNv4 export** → Route exported to global VPNv4 table with RD/RT
5. **BGP advertisement** → Route sent to route reflectors with appropriate encapsulation
6. **Route Reflector** → Route reflected to other PE routers
7. **Remote PE** → Route imported into local VRF based on RT match

---

## Troubleshooting Commands

If routes aren't being exported as expected:

```bash
# Check BGP VRF configuration
show running-config bgp vrf RED

# Check export policies
show bgp vrf RED ipv4 unicast summary

# Verify next-hop reachability
show bgp nexthop

# Check for filtering or route-maps
show route-map
show ip prefix-list

# Enable debugging
debug bgp updates out
debug bgp vpn label
debug bgp srv6
```
