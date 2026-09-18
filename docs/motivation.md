# Why subnet-clash exists

Two people described the same failure this year, from opposite ends of it: a VPN whose home range
turns out to be the range of the Wi-Fi you are sitting on, and a container handed a subnet another
interface on the same host already owns. Both are collisions between configuration files that are
each correct on their own. Both are quoted below, verbatim, with the thread they come from.

Each source has a scenario test that recreates it from fixture files and asserts the tool finds the
collision: `tests/test_scenarios.py`.

## Home LAN vs the Wi-Fi at the other end of the tunnel

- **Link:** https://www.reddit.com/r/WireGuard/comments/1rqpcp3/subnet_conflict_lan_access_fails_on_remote_wifi/
- **Date:** 2026-03-11
- **Subreddit:** r/WireGuard
- **Author:** fabb24
- **Quote:** "I suspect there's a subnet conflict when the remote Wi-Fi network also uses the
  192.168.1.0/24 range (the same as my home network...)"

What the tool does with it: reads the `AllowedIPs`/`Address` out of the WireGuard config and the
addresses out of the config describing the remote network, and reports the two lines that claim the
same block, each with its file and line number.

## A container's veth on a subnet the host already uses

- **Link:** https://www.reddit.com/r/homelab/comments/1tgjjyq/ran_adguard_on_the_router_itself_instead_of_a_pi/
- **Date:** 2026-05-18
- **Subreddit:** r/homelab
- **Author:** mattjh_
- **Quote:** "giving a container a veth on an overlapping subnet creates deeply cursed ECMP
  behaviour. DNS queries would intermittently land on nothing."

What the tool does with it: compares every `IPAM.Config[].Subnet` in a saved `docker network
inspect` against the LAN ranges in netplan/NetworkManager/dnsmasq, and names the docker network and
the interface that overlap before the container is started.

## The rule for this page

Every quote is copied verbatim from the thread it links to and is shown with the date, the
subreddit and the author who wrote it. Nothing here is paraphrased, reconstructed or composed from
several posts: if a line cannot be traced to a thread, it does not belong on this page — the same
rule the [well-known default ranges table](../README.md#well-known-default-ranges) follows for its
sources.
