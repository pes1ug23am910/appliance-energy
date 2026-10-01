# Infrastructure preparation validation

Validated locally on 2026-10-01. No Azure resources or Kubernetes workloads were created.

| Check | Result | Scope |
|---|---|---|
| Bicep CLI 0.47.16, `bicep build azure/main.bicep` | Passed, no compiler warnings | Syntax, resource types and template compilation; no subscription/region/SKU validation |
| Official Bicep executable SHA-256 | Matched GitHub release digest | Compiler download integrity |
| Kubernetes YAML parse | Four documents parsed | YAML structure and required kind/name/version fields |
| Public Kubernetes Service types | None | Backend Service is ClusterIP; no LoadBalancer/NodePort |

Kubernetes schema admission, image pulling, network policy, secret mounting, workload startup and AKS behaviour remain untested. The manifests depend on separately supplied database, broker, Kafka, credentials and CA configuration. Bicep does not install the application or demonstrate a cloud deployment. See [README.md](README.md) for prerequisites and trust boundaries.
