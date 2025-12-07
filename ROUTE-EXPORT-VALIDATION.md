# BGP VPN Route Export Validation - Complete Flow

This document outlines the step-by-step validation process from VRF route installation to BGP advertisement for MPLS L3VPN and SRv6-based VPN services. This will be the from the perspective of the PE1 router, specifically for the 10.10.1.0/30 route in the RED VRF, connected to the CE1 router.

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

## Step 3: Verify VPN label/SID allocation
```bash
show bgp ipv4 vpn rd 1.1.1.1:10 10.10.1.0/30
```
**Look for:**
- `Remote label: 80` (MPLS label if `label vpn export auto`)
- `Remote SID: 2001:db8:1::, sid structure=[32 16 16 0 16 48]` (SRv6 SID if `sid vpn export auto`)
- Extended Community: RT:65000:10

---

## Step 4: Verify route is in global VPNv4 table
```bash
show bgp ipv4 vpn rd 1.1.1.1:10 10.10.1.0/30
```
**Look for:**
- `Remote label: 80` (MPLS label if `label vpn export auto`)
- `Remote SID: 2001:db8:1::, sid structure=[32 16 16 0 16 48]` (SRv6 SID if `sid vpn export auto`)
- Extended Community: RT:65000:10
- One of these will be selected best

---

## Step 5: Verify BGP session state
```bash
show bgp ipv4 vpn summary
```
**Look for:**
- Neighbor 8.8.8.8: State = Established, PfxSnt > 0
- Neighbor 2001:db8:9::1: State = Established, PfxSnt > 0

---

## Step 6: Check detailed advertisement to RRV4
```bash
show bgp ipv4 vpn neighbors 8.8.8.8 advertised-routes 10.10.1.0/30
```
**Look for:**
- Extended Community: RT:65000:10
- Originator: 1.1.1.1
- Remote label value
- Next-hop: 1.1.1.1 (due to `next-hop-self`)

---

## Step 7: Check detailed advertisement to RRV6
```bash
show bgp ipv4 vpn neighbors 2001:db8:9::1 advertised-routes 10.10.1.0/30
```
**Look for:**
- Extended Community: RT:65000:10
- Originator: 1.1.1.1
- Remote SID: 2001:db8:1::
- Next-hop: 2001:db8:1::1 (IPv6 due to SRv6)

---

## Step 8: Verify SRv6 locator and SID allocation
```bash
show segment-routing srv6 locator
```
**Look for:**
- Status: Up
- Block length, node length, function bits
- Prefix: 2001:db8:1::/48

```bash
show segment-routing srv6 sid
```
**Look for:** VPN SIDs allocated for VRF RED

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

---

## Key Configuration Points

### For MPLS VPN:
- `label vpn export auto` in BGP VRF address-family
- LDP session to remote PE
- MPLS label forwarding path established

### For SRv6 VPN:
- `sid vpn export auto` in BGP VRF address-family
- `segment-routing srv6 locator Loc0` in BGP VRF
- `neighbor <rrv6> encapsulation srv6` in global BGP
- SRv6 locator configured and operational

### For Dual Transport (MPLS + SRv6):
- Both `label vpn export auto` and `sid vpn export auto`
- `no srv6-only` in VRF SRv6 configuration
- Separate route reflectors for each transport type recommended
