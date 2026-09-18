# subnet-clash

CLI that detects overlapping IP ranges across WireGuard/docker/netplan/dnsmasq configs you already
have, before they collide.

You add a WireGuard peer, docker picks a bridge subnet, netplan owns the LAN and dnsmasq hands out
leases — each of them correct on its own, and one of them silently eats another's addresses.
`subnet-clash` reads those files, puts every range on the same table, and tells you which two lines
fight, quoting the file and line number of both.

- **Reads files only.** No sockets, no `docker` or `ip` invocation, no look at the live system.
  Everything it knows comes from paths you name (or stdin), so the same inputs always give the same
  report, on your laptop and in CI.
- **Standard library only.** `ipaddress`, `json`, `argparse` — no runtime dependencies.

## Install

```sh
pip install subnet-clash
# or, from a checkout
pip install .
```

Python 3.11+. Installing provides the `subnet-clash` command; `python -m subnet_clash` works too.

## Usage

```sh
subnet-clash check \
  --wg /etc/wireguard/wg0.conf \
  --docker docker-net.json \
  --netplan /etc/netplan/01-netcfg.yaml \
  --nm /etc/NetworkManager/system-connections/lab-eth.nmconnection \
  --dnsmasq /etc/dnsmasq.conf
```

| flag | source | what is read |
| --- | --- | --- |
| `--wg` | WireGuard config | `[Interface] Address`, `[Peer] AllowedIPs` |
| `--docker` | saved `docker network inspect` JSON | every `IPAM.Config[].Subnet` and `.IPRange` |
| `--netplan` | netplan YAML | per-device `addresses` (plain and address-options form), static `routes[].to` |
| `--nm` | NetworkManager keyfile | `[ipv4]`/`[ipv6]` `addressN`, `routeN` |
| `--dnsmasq` | dnsmasq config | `dhcp-range=` pools |

Every flag is repeatable, and `-` reads that source from stdin (once per run):

```sh
docker network inspect $(docker network ls -q) | subnet-clash check --docker - --wg /etc/wireguard/wg0.conf
```

Other options: `--format markdown|json` (default `markdown`), `-o FILE`, `--no-default-check`,
`--include-default-routes`. `subnet-clash defaults` prints the table of well-known default ranges.

## Example output

Running against the fixtures in `tests/fixtures/`:

```sh
subnet-clash check --wg wg0.conf --docker docker-net.json \
                   --netplan 01-netcfg.yaml --dnsmasq dnsmasq.conf
```

```markdown
**11 clash(es)** across 12 range(s): 2 overlap, 2 identical, 7 contains.

### 1. overlap: `01-netcfg.yaml:8` vs `dnsmasq.conf:6`

- **A** `192.168.50.1/24` - netplan enp3s0 address - `01-netcfg.yaml:8` (`network.ethernets.enp3s0.addresses[0]`)
- **B** `192.168.50.200-192.168.51.50` - dnsmasq dhcp-range - `dnsmasq.conf:6` (`dhcp-range`)
- shared: `192.168.50.200/29`, `192.168.50.208/28`, `192.168.50.224/27`
- partial overlap - each side also owns addresses the other does not; almost always a bug

### 4. identical: `docker-net.json:36` vs `wg0.conf:3`

- **A** `10.8.0.0/24` - docker network "lab" Subnet - `docker-net.json:36` (`$[1].IPAM.Config[0].Subnet`)
- **B** `10.8.0.1/24` - wg0 [Interface] Address - `wg0.conf:3` (`[Interface].Address`)
- shared: `10.8.0.0/24`
- the two ranges are exactly the same block

### 7. contains: `dnsmasq.conf:9` vs `wg0.conf:3`

- **A** `10.8.0.100-10.8.0.150` - dnsmasq dhcp-range - `dnsmasq.conf:9` (`dhcp-range`)
- **B** `10.8.0.1/24` - wg0 [Interface] Address - `wg0.conf:3` (`[Interface].Address`)
- shared: `10.8.0.100/30`, `10.8.0.104/29`, ...
- A is fully inside B
- one range sits entirely inside the other - frequently deliberate (...)
```

Both sides of every finding carry a file and a line. For JSON sources the line is accompanied by
the key path that produced it (`$[1].IPAM.Config[0].Subnet`), and for YAML by the document path
(`network.ethernets.enp3s0.addresses[0]`).

## overlap vs contains vs identical

Not every intersection is a bug, so they are reported as three different kinds:

| kind | meaning | how worried to be |
| --- | --- | --- |
| **overlap** | the two ranges share addresses, *and each one also owns addresses the other does not* | high — nobody configures this on purpose; a DHCP pool running past the end of its LAN, or two networks half-covering each other |
| **identical** | both sides describe exactly the same block | high — two tools believe they own the same addresses |
| **contains** | one range sits entirely inside the other (`10.1.2.0/24` inside `10.0.0.0/8`) | often intentional: a DHCP pool inside its LAN, a WireGuard peer's `/32` inside the tunnel subnet, a route into a larger aggregate. Read these, do not panic at them |

Two plain CIDRs can only ever be nested — CIDR blocks never half-overlap. A true `overlap` therefore
only shows up once a range is not a single prefix, which is exactly what a dnsmasq pool
(`192.168.50.200,192.168.51.50`) is: an arbitrary start–end span that gets summarised into several
networks. That is also the case most likely to be a genuine mistake.

## What counts as two different sources

Ranges are only compared across *different logical configuration units*, so the tool does not
report a config for being internally consistent:

| source | unit | not compared with itself |
| --- | --- | --- |
| WireGuard | the interface, and each peer separately | `[Interface] Address` vs its own peers' `AllowedIPs` — peers are supposed to live in the tunnel subnet. Two **peers** of the same tunnel overlapping *is* reported: that breaks routing |
| docker | one network per `Name` | `Subnet` vs its own `IPRange` — the pool is carved out of the subnet by design |
| netplan | one device | a device's `addresses` vs its own `routes` |
| NetworkManager | one connection file, per address family | — |
| dnsmasq | each `dhcp-range=` line | — |

`0.0.0.0/0` and `::/0` are put aside instead of compared: a full-tunnel `AllowedIPs = 0.0.0.0/0`
contains every other range on the table and would bury the report. They are listed in a separate
section; pass `--include-default-routes` to compare them anyway.

## Well-known default ranges

Beyond clashes between your own files, `subnet-clash` warns when a range *is* one of the defaults
that tools hand out unprompted — the ones most likely to collide with a machine you have not looked
at yet. The rule for this table: **a row exists only if it links to a document that describes the
range.** No link, no row.

| range | kind | what uses it | source |
| --- | --- | --- | --- |
| `172.17.0.0/16` | assignment | Docker: first default address pool; the default `bridge` network lands here | https://docs.docker.com/engine/network/ |
| `172.18.0.0/16` | pool | Docker: second default address pool (user-defined bridges) | https://docs.docker.com/engine/network/ |
| `172.19.0.0/16` | pool | Docker: third default address pool | https://docs.docker.com/engine/network/ |
| `172.20.0.0/14` | pool | Docker: fourth default address pool | https://docs.docker.com/engine/network/ |
| `172.24.0.0/14` | pool | Docker: fifth default address pool | https://docs.docker.com/engine/network/ |
| `172.28.0.0/14` | pool | Docker: sixth default address pool | https://docs.docker.com/engine/network/ |
| `192.168.0.0/16` | pool | Docker: last default address pool, carved into /20s | https://docs.docker.com/engine/network/ |
| `10.96.0.0/12` | assignment | Kubernetes: kubeadm default service CIDR (`--service-cidr`) | https://kubernetes.io/docs/reference/setup-tools/kubeadm/kubeadm-init/ |
| `10.244.0.0/16` | assignment | Flannel: default pod network for the documented kube-flannel manifest | https://github.com/flannel-io/flannel/blob/master/Documentation/kubernetes.md |
| `192.168.122.0/24` | assignment | libvirt: the `default` NAT network created on install (virbr0, 192.168.122.1/255.255.255.0) | https://wiki.libvirt.org/VirtualNetworking.html |
| `192.168.56.0/24` | assignment | VirtualBox: default host-only network | https://www.virtualbox.org/manual/topics/networkingdetails.html |
| `100.64.0.0/10` | pool | Shared address space (CGNAT); Tailscale assigns node addresses from it | https://tailscale.com/kb/1015/100.x-addresses |
| `10.192.122.0/24` | assignment | WireGuard: the example tunnel subnet in the wg-quick(8) man page | https://man7.org/linux/man-pages/man8/wg-quick.8.html |
| `192.168.0.0/24` | assignment | dnsmasq: the example `dhcp-range=192.168.0.50,192.168.0.150,12h` from dnsmasq(8) | https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html |
| `169.254.0.0/16` | assignment | IPv4 link-local autoconfiguration, the 169.254/16 prefix; never assign it by hand | https://www.rfc-editor.org/rfc/rfc3927 |
| `fe80::/10` | assignment | IPv6 link-local addressing (RFC 4291 §2.5.6) | https://www.rfc-editor.org/rfc/rfc4291 |

`kind` is `assignment` for a network some tool actually creates, and `pool` for a block a tool
auto-allocates smaller networks out of.

### Why 192.168.1.0/24 is not in the table

It is the most common home-router LAN there is, and it is exactly the kind of range this table
wants. But the rule above is the rule: RFC 1918 reserves `192.168.0.0/16` without blessing any
particular `/24`, and no vendor document was found that states `192.168.1.0/24` as a published
default. Rather than cite something weaker than the other rows, the row is left out. If you have a
citable source, add the row to `src/subnet_clash/defaults.py` with the link — that is all it takes.

## Exit codes

| code | meaning |
| --- | --- |
| `0` | no clashes (warnings about default ranges do not change this) |
| `1` | at least one clash found |
| `2` | unusable input — missing file, malformed JSON/YAML, invalid CIDR, non-UTF-8 bytes (file or stdin), no sources given — with the file and line on stderr |

The split matters in a pipeline: `1` always means "something was found", never "the input could
not be read", so `docker network inspect ... | subnet-clash check --docker -` on garbage bytes
exits `2`, not `1`.

```console
$ subnet-clash check --netplan broken.yaml
subnet-clash: error: broken.yaml:2: tab used for indentation (YAML forbids it)
$ echo $?
2
```

A file that parses cleanly but contains no ranges at all is not an error — an empty config is
legal — but it is named on stderr, because that is also what a half-read file looks like:

```console
$ subnet-clash check --wg keys-only.conf
subnet-clash: warning: keys-only.conf: read as wireguard, no ranges found
```

## JSON report

`--format json` emits `sources`, `summary`, every parsed `ranges` entry, `clashes` and
`default_range_warnings`. Each clash carries both sides with `file`, `line`, `key` and `location`,
plus the `intersection` networks:

```json
{
  "kind": "contains",
  "container": "b",
  "intersection": ["172.17.5.0/24"],
  "a": { "source": "docker", "range": "172.17.0.0/16", "location": "docker-net.json:14",
         "file": "docker-net.json", "line": 14, "key": "$[0].IPAM.Config[0].Subnet" },
  "b": { "source": "wireguard", "range": "172.17.5.0/24", "location": "wg0.conf:15",
         "file": "wg0.conf", "line": 15, "key": "[Peer].AllowedIPs" }
}
```

## Not in v0.1

- It never fixes anything: no config is written or suggested.
- No live monitoring and no reading of system state — if you want the current docker networks,
  save `docker network inspect` to a file and pass it in.
- Windows networking and VPNs other than WireGuard are out of scope.
- dnsmasq `conf-file`/`conf-dir` includes are not followed; name those files yourself.
- The bundled YAML reader covers the netplan dialect (block mappings, block and flow sequences,
  plain scalars). Anchors and aliases (`&lan` / `*lan`, including `<<:` merge keys),
  multi-document files, duplicate keys and block scalars are rejected with exit code 2 rather
  than half-read — quote the value if you want a literal `*` or `&`. Concatenating two netplan
  files into one is therefore an error (duplicate `network:`), not a silent read of the last one
  — pass each file with its own `--netplan`.
- Both documented `addresses:` forms are read: the plain `- 10.100.1.38/24` and the
  address-options one MAAS writes, where the address is the key —

  ```yaml
  addresses:
    - 10.100.1.38/24:
        lifetime: 0
        label: "maas"
  ```

  Anything else under `addresses:` or `routes:` — a value that is not a list, a list item that is
  not an address, a `to:` that is not a single address — is exit code 2, never a skipped address.

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q          # tests, all on file fixtures under tests/fixtures/
ruff check . && ruff format --check .
python -m build    # wheel + sdist
```

CI runs lint, the test suite on Python 3.11/3.12/3.13, and a build on every push and pull request.
Pushing a `v*` tag builds a wheel and an sdist and attaches them to the GitHub release.

## License

MIT — see [LICENSE](LICENSE).
