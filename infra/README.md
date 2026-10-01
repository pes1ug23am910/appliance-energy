# Deployment preparation

The private foundation and Kubernetes adapter below are separate from the bounded Azure runtime demonstration in [azure/LAB.md](azure/LAB.md). Consult [VALIDATION.md](VALIDATION.md) for dated execution evidence and remaining limitations. Compiling a template alone never establishes a deployment.

## Private Azure VM foundation

`azure/main.bicep` describes one Ubuntu VM, private NIC, VNet, subnet and NSG. There is no public IP, application installation, container registry, database service, IoT Hub, paid bastion or AKS cluster. Inbound traffic is restricted to SSH from an explicitly chosen private operator network. A route through existing VPN/peering is required. Default outbound Internet access is disabled; installation later requires an explicitly designed egress route or prebuilt image. Managed identity is created without any role assignments.

The VM size is an editable capacity placeholder, not a price recommendation. Before any future deployment, validate region/SKU availability, address-space overlap, operator routing, managed-disk charges and the user's then-current spending limit. This template alone cannot enforce a spending cap or delete resources on a timer. Deallocated VMs can still incur storage charges.

Local syntax/type validation:

```text
bicep build infra/azure/main.bicep --outfile infra/build/main.json
```

This does not contact an Azure subscription. A later Azure what-if and deployment are separate operations. Neither is part of the local software validation. An SSH public key is a required input; private keys and credentials never belong in a parameters file.

The local service uses plain HTTP inside its trusted local boundary and environment bearer credentials. Before exposing it outside that boundary, add a TLS ingress, review authentication and credential rotation, configure backups, protect Kafka and database traffic, and validate the relevant network policies. Do not simply expose Compose ports publicly.

## Kubernetes / AKS application adapter

`kubernetes/backend.yaml` describes one backend replica and a ClusterIP Service with non-root execution, read-only root filesystem, resource limits, a temporary volume and health probes. It creates no load balancer or ingress. The database-aware HTTP health probe controls readiness; TCP liveness avoids restarting the backend merely because a downstream database is unavailable.

This is an application adapter, not a complete cluster or an AKS deployment. Before applying it anywhere, supply:

- An accessible immutable backend image reference, replacing the local development image tag.
- PostgreSQL, Kafka and a TLS MQTT broker with durable storage and an appropriate trust/network boundary.
- A `backend-config` ConfigMap adapted from the example; its hostnames are placeholders for services that are not supplied by these manifests.
- A `backend-secrets` Secret containing `API_TOKEN`, `SPRING_DATASOURCE_PASSWORD` and `MQTT_PASSWORD`.
- A `broker-ca` ConfigMap containing the public `ca.crt`. Its server certificate must cover the configured broker DNS name.

Do not commit a rendered Secret. The backend pod intentionally cannot start until its dependencies/configuration exist. Keep one replica until outbox scheduling, MQTT client identity and session ownership have been explicitly tested with multiple service instances. Scaling the Deployment alone is not a demonstrated high-availability design.

A future cluster must enforce egress/ingress policy appropriate to its CNI and actual managed-service destinations. No universal NetworkPolicy is provided that would silently block required managed endpoints or claim enforcement on a cluster without a policy engine.

References: [Azure VM resource schema](https://learn.microsoft.com/en-us/azure/templates/microsoft.compute/virtualmachines), [Bicep build command](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/bicep-cli#build), [Kubernetes security contexts](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/), [Kubernetes probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/).
