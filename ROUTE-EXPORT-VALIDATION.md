# BGP VPN Route Export Validation

This document validates SRv6-based L3VPN route export and import from the perspective of `pe1` only.

The goal is to confirm two things from `pe1`:

1. `pe1` correctly exports its locally connected RED VRF routes toward the route reflector.
2. `pe1` correctly receives and installs remote RED VRF routes originated by `pe2`, including the SRv6 information needed to forward traffic to the remote PE.

The examples below focus on these prefixes:

- Local IPv4 on `pe1`: `10.10.1.0/30`
- Remote IPv4 learned on `pe1` from `pe2`: `10.10.2.0/30`
- Local IPv6 on `pe1`: `2001:c0de:10:1::/64`
- Remote IPv6 learned on `pe1` from `pe2`: `2001:c0de:10:2::/64`

JSON output is used only where the normal FRR CLI output does not expose the SRv6 details we need to validate.

## IPv4

### Local IPv4 client prefix on PE1: `10.10.1.0/30`

This section validates that the client-facing IPv4 prefix connected to `pe1` is present in the RED VRF, imported into BGP, exported into the VPN table, and advertised by `pe1` toward the route reflector.

#### Step 1: Verify the route exists in the RED VRF routing table
```bash
show ip route vrf RED 10.10.1.0/30
```

**Look for:**
- A connected route for `10.10.1.0/30`
- The expected client-facing interface, such as `eth3.10`

This confirms the local client subnet is present in the VRF RIB before BGP export is considered.

#### Step 2: Verify the route is present in the RED VRF BGP table
```bash
show bgp vrf RED ipv4 unicast 10.10.1.0/30
```

**Look for:**
- Prefix `10.10.1.0/30`
- `Origin ?` / incomplete origin
- `Weight 32768`
- Best-path indicators showing the route is valid, local, and selected

This confirms `pe1` has redistributed the connected route into the VRF BGP address family.

#### Step 3: Verify the route is exported into the global VPNv4 table
```bash
show bgp ipv4 vpn rd 172.16.0.1:10 10.10.1.0/30
```

**Look for:**
- Route distinguisher `172.16.0.1:10`
- Route target `RT:65000:10`
- The route marked valid, local, and best
- SRv6 service information associated with the exported route

This confirms the VRF route has been exported into VPNv4 with the correct RD/RT context.

#### Step 4: Verify the SRv6 SID allocated on PE1 for the RED VRF service
```bash
show segment-routing srv6 sid
```

**Look for:**
- A dynamic SID for VRF `RED`
- An entry similar to:
  - `fcdd:dd00:101:e000::  uDT4  VRF 'RED'  ...`

This confirms `pe1` has allocated the local SRv6 service SID used for VPN route export for IPv4 reachability.

#### Step 5: Verify PE1 is advertising the route toward the route reflector
```bash
show bgp ipv4 vpn neighbors 2001:face::8 advertised-routes 10.10.1.0/30
```

**Look for:**
- Prefix `10.10.1.0/30`
- `RT:65000:10`
- Originator or local origin attributes tied to `pe1`
- SRv6 service information attached to the advertisement

This is the final export proof from the `pe1` point of view: the local RED VRF IPv4 route is not just present locally, but is actually being advertised upstream.

### Remote IPv4 client prefix seen on PE1: `10.10.2.0/30`

This section validates that `pe1` receives the remote RED VRF IPv4 route from `pe2`, sees the SRv6 information carried with the VPN route, and installs the route into the RED VRF with the expected `seg6` forwarding information.

#### Step 1: Verify the remote route is present in the VPNv4 table on PE1
```bash
show bgp ipv4 vpn 10.10.2.0/30 json
```

**Look for:**
- Prefix `10.10.2.0/30`
- A valid and selected path
- The remote route distinguisher and RED route target
- The SRv6 field showing the remote service information from `pe2`
- Specifically, `pe1` should see:
  - `"remoteTransposedSid":"fcdd:dd00:106:e000::"`

JSON is required here because the standard FRR CLI output does not expose the `remoteTransposedSid` clearly enough for this validation.

This confirms that `pe1` learned the remote VPN route and that the BGP path includes the SRv6 service SID information advertised by `pe2`.

#### Step 2: Verify the remote route is installed in the RED VRF RIB/FIB on PE1
```bash
show ip route vrf RED 10.10.2.0/30 json
```

**Look for:**
- Prefix `10.10.2.0/30` installed in VRF `RED`
- BGP as the source of the installed route
- The SRv6 forwarding information in the route entry
- Specifically, a `seg6` structure similar to:
  - `"seg6":{"segs":"fcdd:dd00:106:e000::"}`

JSON is required here because the standard route display does not show the `seg6` encapsulation details needed to prove how traffic will be forwarded.

This confirms that `pe1` did not merely learn the remote route in BGP; it also installed the route with the expected SRv6 forwarding behavior toward the service endpoint advertised by `pe2`.

## IPv6

### Local IPv6 client prefix on PE1: `2001:c0de:10:1::/64`

This section validates that the locally connected IPv6 subnet in VRF `RED` is present on `pe1`, imported into BGP, exported into the VPN table, and advertised toward the route reflector.

#### Step 1: Verify the route exists in the RED VRF IPv6 routing table
```bash
show ipv6 route vrf RED 2001:c0de:10:1::/64
```

**Look for:**
- A connected route for `2001:c0de:10:1::/64`
- The expected client-facing interface for the RED VRF attachment

This confirms the local IPv6 client subnet is present in the VRF before BGP export.

#### Step 2: Verify the route is present in the RED VRF IPv6 BGP table
```bash
show bgp vrf RED ipv6 unicast 2001:c0de:10:1::/64
```

**Look for:**
- Prefix `2001:c0de:10:1::/64`
- A locally originated path, typically with incomplete origin and local best-path selection

This confirms `pe1` has redistributed the local IPv6 route into the VRF BGP table.

#### Step 3: Verify the route is exported into the global VPNv6 table
```bash
show bgp ipv6 vpn rd 172.16.0.1:10 2001:c0de:10:1::/64
```

**Look for:**
- Route distinguisher `172.16.0.1:10`
- Route target `RT:65000:10`
- The route marked valid, local, and best
- SRv6 service information associated with the VPNv6 export

This confirms the local IPv6 VRF route has been exported into the VPNv6 table with the expected VPN attributes.

#### Step 4: Verify PE1 is advertising the route toward the route reflector
```bash
show bgp ipv6 vpn neighbors 2001:face::8 advertised-routes 2001:c0de:10:1::/64
```

**Look for:**
- Prefix `2001:c0de:10:1::/64`
- `RT:65000:10`
- Originator or local origin attributes tied to `pe1`
- SRv6 service information attached to the advertisement

This confirms the local IPv6 RED VRF route is being exported by `pe1` toward the control plane.

### Remote IPv6 client prefix seen on PE1: `2001:c0de:10:2::/64`

This section validates that `pe1` receives the remote IPv6 RED VRF route from `pe2` and installs it with the expected SRv6 forwarding information.

#### Step 1: Verify the remote route is present in the VPNv6 table on PE1
```bash
show bgp ipv6 vpn 2001:c0de:10:2::/64 json
```

**Look for:**
- Prefix `2001:c0de:10:2::/64`
- A valid and selected path
- The remote route distinguisher and RED route target
- SRv6 service information carried with the remote advertisement
- The remote transposed SID associated with the route

Use JSON here if the normal FRR output does not expose the SRv6 service fields clearly enough.

This confirms that `pe1` learned the remote IPv6 VPN route with the SRv6 information required to reach the remote service.

#### Step 2: Verify the remote route is installed in the RED VRF IPv6 routing table on PE1
```bash
show ipv6 route vrf RED 2001:c0de:10:2::/64 json
```

**Look for:**
- Prefix `2001:c0de:10:2::/64` installed in VRF `RED`
- BGP as the source of the route
- `seg6` forwarding information identifying the SRv6 segment list used for forwarding

This confirms that `pe1` has installed the remote IPv6 route into the VRF with SRv6 forwarding behavior, not just learned it in BGP.

# Validation Summary

From the `pe1` point of view, successful validation should show this flow:

1. A local client prefix exists in VRF `RED`.
2. The local route is redistributed into the VRF BGP table.
3. The route is exported into the global VPN table with the correct RD/RT and SRv6 service information.
4. `pe1` advertises the local VPN route toward the route reflector.
5. `pe1` receives remote VPN routes from `pe2` with the expected SRv6 attributes.
6. `pe1` installs those remote routes into VRF `RED` with `seg6` forwarding information pointing to the remote service SID.

For remote-route validation, the most important proof points on `pe1` are:

- The VPN route is present in BGP.
- The remote SRv6 service information is visible in the BGP entry.
- The route is installed in the RED VRF routing table.
- The installed route contains the expected `seg6` forwarding data.
