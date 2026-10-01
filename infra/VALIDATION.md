# Infrastructure validation

Verified on 2026-10-01 using a temporary Ubuntu 24.04 VM in Azure `southeastasia`:
`Standard_B2as_v2` (2 vCPU, 8 GiB), a 64 GiB Premium SSD, and Docker 29.1.3.
The VM ran the repository's Java, PostgreSQL, Kafka and TLS MQTT stack with
software-simulated devices. All temporary compute, disks and networking were
removed after verification.

The [machine-readable receipt](evidence/azure-smoke.json) records exact values,
source/archive hashes, sampled resources and cleanup. The
[source manifest](evidence/azure-source-manifest.json) identifies the files
uploaded for this run. Reproduction instructions are in [azure/LAB.md](azure/LAB.md).
Raw logs, credentials, account identifiers and public IP addresses stay outside
the repository.

## Cloud acceptance

| Check | Observed result |
|---|---|
| ARM what-if and deployment | Succeeded for the temporary lab template |
| Fresh database initialization | Migration present in deployed jar; Flyway validated and applied V1 |
| HTTP/TLS MQTT transport smoke | All 7 checks passed in 2.729 s |
| Sustained generation | 100 devices, one tick every 10 s, 30 ticks; 301.190 s including final receipt drain |
| Offered versus durable receipts | 3,000 generated; 3,000 accepted; 0 dropped; 0 pending; 0 missed ticks |
| Receipt latency | 3,000 samples: p50 1.145 s, p95 2.533 s, maximum 4.105 s |
| Independent Kafka replays | 7 batches and 3,001 unique events in each export; logical event maps identical |
| PostgreSQL/API reconciliation | 3,001 identities, exactly matching Kafka; includes the one transport-smoke event |
| Host port exposure | API 18080, MQTT 18883, Kafka 19092 and PostgreSQL 15432 bound only to `127.0.0.1` |
| Final resource inventory | Zero resources at 18:17:09 UTC; four dedicated lab groups deleted |

The seven transport checks cover rejected unauthenticated access, ten retries
preserving one command/revision, conflicting payload and stale revision rejection,
TLS MQTT reported-state confirmation, duplicate telemetry with one durable row,
lost-report reconciliation, and expired-command rejection. Receipt latency runs
from the first publish attempt to the durable application receipt.

SSH was restricted to one operator IPv4 `/32`; the host key was obtained through
Azure Run Command before connecting. An unused regional Network Watcher was
automatically created by Azure during VNet provisioning. Its creation activity
matched the deployment window, and it had no flow logs, connection monitors or
packet captures. That exact resource was removed; the empty system resource group
was retained. [Azure documents this automatic enablement](https://learn.microsoft.com/en-us/azure/network-watcher/network-watcher-create).

## Resource observations

Twenty-nine samples were collected per container during acceptance, with no
sampling errors. These are sampled maxima, not continuous peaks or simultaneous
totals. Docker's CPU calculation scales by available CPUs and can exceed 100%;
memory is Docker-reported usage. [Docker metrics](https://docs.docker.com/reference/cli/docker/container/stats/),
[CPU calculation](https://github.com/docker/cli/blob/master/cli/command/container/stats_helpers.go).

| Container | Maximum sampled Docker CPU % | Maximum sampled memory MiB |
|---|---:|---:|
| Java backend | 181.38 | 241.00 |
| Kafka | 164.78 | 440.60 |
| PostgreSQL | 25.47 | 66.96 |
| Mosquitto | 4.41 | 6.96 |

This five-minute workload establishes bounded correctness and measured behaviour
on one shared host. It does not establish fleet capacity, sustained throughput
limits, availability, hardware behaviour or a production SLA.

## Packaging regression and cost boundary

The cloud archive builder now preserves usable source timestamps. A clean build
from epoch-zero file entries omitted the unfiltered SQL migration: Flyway found
zero migrations and a fresh registration returned HTTP 500. With preserved
timestamps, the same clean build packaged V1, applied one migration and returned
HTTP 200 on a new database. `python scripts/azure_test.py` also passed its automated
archive/extraction regression using an epoch-zero SQL fixture. Backend source
changes were unnecessary.

Cost accounting includes three setup attempts and the successful run, totalling
35.318 minutes from deployment request to resource-group deletion. Rounding each
VM, disk and IP allocation up to a whole hour gives a conservative USD 0.4535
base estimate. Adding USD 0.50 for unmetered egress/transfer overhead gives
USD 0.9535, approximately INR 91.53 at the recorded conversion rate, below the
INR 200 allowance. Downloaded evidence archives totalled 446,129 bytes.
This is an intentionally conservative envelope, **not a settled Azure charge**;
billing reconciliation remains subject to Azure's reporting delay.

Rates recorded from the [Azure retail prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices):
B2as v2 Linux USD 0.0944/hour, P6 LRS disk USD 10.207/month (730-hour estimate),
and Standard IPv4 USD 0.005/hour. [Managed disk billing](https://learn.microsoft.com/en-us/azure/virtual-machines/disks-understand-billing),
[public IP billing increments](https://azure.microsoft.com/en-us/pricing/details/ip-addresses/).

## Other infrastructure checks and limitations

| Check | Result | Scope |
|---|---|---|
| Bicep CLI 0.47.16, `bicep build azure/main.bicep` | Passed, no compiler warnings | Private foundation syntax/types; this separate template was not deployed |
| Official Bicep executable SHA-256 | Matched release digest | Compiler download integrity |
| Kubernetes YAML parse | Four documents parsed | YAML structure and required kind/name/version fields |
| Public Kubernetes Service types | None | Backend Service is ClusterIP; no LoadBalancer/NodePort |

AKS, IoT Hub, physical firmware, managed Kafka/PostgreSQL, backups and multi-host
failover were not validated by this run. Kubernetes schema admission, image pulls,
network policy, secret mounting and workload startup remain untested; the adapter
needs separately supplied dependencies. The deployed lab is a separate template
from the private-network foundation. See [README.md](README.md) for prerequisites.
