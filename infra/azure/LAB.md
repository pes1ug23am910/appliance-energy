# Temporary Azure runtime laboratory

`lab.bicep` provisions one Ubuntu 24.04 VM with Docker Compose, using a separate
single-use resource group. The existing `main.bicep` remains a private-network
foundation requiring VPN/peering and planned egress.

The lab uses a Standard public IPv4 address for explicit outbound connectivity
and SSH access from **one operator IPv4 /32**. All application endpoints stay on
host loopback and the private Compose network. PostgreSQL, MQTT, Kafka and the
API are not public services. For an interactive API demonstration use an SSH
local tunnel, for example `ssh -L 18080:127.0.0.1:18080 ...`; use the attested
host key and temporary lab key created by the controller. The cloud VM does not
change the application's single-operator trust model into a multi-tenant service.

## Before running

Use an authenticated Azure CLI and verify the intended subscription, actual
remaining credit and expiry, enabled spending limit, permitted locations,
resource-provider registration, regional/family vCPU quota, SKU restrictions and
current Linux VM, managed disk, IP and egress prices. A budget alert is not a
hard spending stop. The controller's `--budget-inr` records an approved estimate;
it is **not** an Azure billing cap and cannot replace those checks.

The selected default is `Standard_B2as_v2` (2 vCPU, 8 GiB), with a 64 GiB Premium
SSD. Premium disk capacity is time-metered without the Standard SSD per-operation
charge. Verify these choices against current subscription access and pricing.
Do not substitute a large or unrestricted VM solely to overcome an allocation
failure. The template uses an ordinary on-demand Linux image, without a paid
Marketplace software plan.

From the repository root:

```text
python scripts/azure_lab.py --evidence <new-private-directory> --budget-inr <approved-estimate>
```

On Windows, `--az` can point to `az.cmd`. The evidence directory must not already
exist and should be outside the Git checkout. It contains the private SSH key,
operator IP, subscription identifiers, deployment logs and source manifest.
Never commit that directory or a rendered parameter file.

## Runtime and acceptance

The controller packages selected tracked application files plus its acceptance
script, records file/archive hashes, creates a tagged dedicated group, runs ARM
what-if, and provisions the VM. It obtains the SSH host public key through Azure
Run Command before accepting the SSH connection. It installs Ubuntu's Docker
packages and pinned `uv`, resolves the locked simulator environment, creates
fresh local-only identities/certificates, and builds the pinned container stack.
Source timestamps are preserved with a 1980 lower bound: epoch-zero archive
entries can cause Maven to skip unfiltered SQL resources. Before testing writes,
the harness confirms the deployed jar includes the migration. Run the archive
regression locally with `python scripts/azure_test.py`.

`scripts/azure_smoke.py` then runs:

- The seven real HTTP/TLS MQTT command, retry, expiry and receipt checks.
- A 100-device, 10-second-interval, 300-second generation window, with up to a
  60-second final receipt drain. Generated events must equal accepted counter
  deltas; dropped events and final pending events must be zero.
- Two independent Kafka consumer groups reading retained events into atomic
  file batches. Every batch hash and row count is checked; logical event maps
  must be identical between exports and match PostgreSQL-backed API identities.
- Docker CPU/memory samples about every ten seconds, retained with the raw run.

The harness verifies an authenticated registration before transport checks.
On failure it records the HTTP status/body and a bounded backend log tail,
then downloads partial artifacts before teardown. Logs stay private: only a
sanitized result summary belongs in the repository.

The device data remains simulated. This is a single-host cloud runtime check,
not a fleet capacity SLA, managed Kafka/PostgreSQL deployment, AKS deployment,
IoT Hub validation, or physical appliance test.

## Deadline and teardown

The controller gives normal work a maximum 100-minute deadline and keeps cleanup
separate. A guest shutdown timer at 90 minutes is a secondary safeguard only:
guest shutdown does not deallocate Azure compute. A `finally` handler verifies
the exact group's unique `runId` before deleting that group, then verifies its
absence. Never point cleanup at an existing/shared resource group.

Keep the operator process alive until cleanup completes. If the operator crashes
or loses access, inspect the private `state.json`, verify the exact resource
group and `runId`, then deallocate its VM and remove its resources using the
Azure portal or CLI. VM deallocation alone retains billable disk/IP resources.

Cost reconciliation is separate from a successful smoke result. Retain the
creation/deletion timestamps and price assumptions, then inspect billing after
Azure's reporting delay. Include failed attempts and disk/IP metering increments
in the estimate. Do not label an estimate as a settled charge.

References: [what-if](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/deploy-what-if),
[SKU availability](https://learn.microsoft.com/en-us/azure/azure-resource-manager/troubleshooting/error-sku-not-available),
[retail prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices),
[spending limits](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/spending-limit).
