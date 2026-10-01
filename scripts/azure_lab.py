"""Provision, verify, and remove one temporary Azure lab within a fixed deadline.

Run only after checking current offer, spending limit, policy, SKU, quota and price.
Private logs, SSH keys and Azure identifiers go to the supplied evidence directory.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import ipaddress
import json
import os
import subprocess
import tarfile
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_source_archive(root: Path, selected: list[str], archive: Path) -> dict[str, str]:
    """Keep file contents and usable timestamps across the Linux build boundary."""
    manifest = {}
    with tarfile.open(archive, "w:gz") as output:
        for name in sorted(set(selected)):
            source = root / name
            if not source.is_file():
                continue
            data = source.read_bytes()
            manifest[name] = hashlib.sha256(data).hexdigest()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            # Epoch-zero timestamps can make Maven skip an absent,
            # unfiltered resource as unchanged. Preserve real source times
            # with a ZIP-compatible lower bound for jar packaging.
            info.mtime = max(315532800, int(source.stat().st_mtime))
            output.addfile(info, io.BytesIO(data))
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--az", default="az")
    parser.add_argument("--location", default="southeastasia")
    parser.add_argument("--vm-size", default="Standard_B2as_v2")
    parser.add_argument("--budget-inr", type=float, default=120)
    args = parser.parse_args()
    if not 0 < args.budget_inr <= 200:
        parser.error("this bounded lab requires an approved estimate of at most INR 200")
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    if os.name != "nt":
        evidence.chmod(0o700)
    run_id = uuid.uuid4().hex[:12]
    group = "appliance-smoke-" + run_id
    prefix = "appliance-smoke"
    deadline = time.monotonic() + 100 * 60
    sequence = 0
    ownership = False
    state = {"run_id": run_id, "resource_group": group, "location": args.location,
             "vm_size": args.vm_size, "approved_estimate_inr": args.budget_inr,
             "started_at_utc": datetime.now(timezone.utc).isoformat(), "phase": "preflight"}

    def save():
        (evidence / "state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def run(command, label, timeout=600, cleanup=False):
        nonlocal sequence
        sequence += 1
        print(f"[{sequence}] {label}", flush=True)
        maximum = timeout if cleanup else min(timeout, max(1, int(deadline - time.monotonic())))
        result = subprocess.run([str(x) for x in command], cwd=ROOT, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=maximum)
        (evidence / f"{sequence:02d}-{label}.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"{label} failed ({result.returncode}); inspect private log")
        return result.stdout

    def az(*values, label, timeout=600, cleanup=False):
        return run([args.az, *values], label, timeout, cleanup)

    try:
        account = json.loads(az("account", "show", "-o", "json", label="account"))
        state["subscription_id"] = account["id"]
        policy = json.loads(az("rest", "--method", "get", "--url",
                             f"https://management.azure.com/subscriptions/{account['id']}?api-version=2022-12-01",
                             "-o", "json", label="subscription-policy"))
        assert policy["state"] == "Enabled"
        assert policy["subscriptionPolicies"]["spendingLimit"] == "On", "spending limit must remain on"
        assert az("group", "exists", "--name", group, label="group-absent").strip() == "false"
        operator_ip = urllib.request.urlopen("https://api.ipify.org", timeout=20).read().decode().strip()
        assert isinstance(ipaddress.ip_address(operator_ip), ipaddress.IPv4Address)
        key = evidence / "lab-key"
        run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "temporary-appliance-lab", "-f", key], "ssh-key")
        parameters = {"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
                      "contentVersion": "1.0.0.0", "parameters": {
                          "adminSshPublicKey": {"value": key.with_suffix(".pub").read_text().strip()},
                          "operatorPublicCidr": {"value": operator_ip + "/32"},
                          "vmSize": {"value": args.vm_size},
                          "tags": {"value": {"purpose": "appliance-energy-cloud-smoke", "lifecycle": "temporary",
                                            "runId": run_id, "budgetInr": str(args.budget_inr)}}}}
        parameter_file = evidence / "parameters.json"
        parameter_file.write_text(json.dumps(parameters, indent=2), encoding="utf-8")
        paths = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
        selected = [p for p in paths if p.startswith(("backend/", "simulator/", "contracts/", "scripts/"))
                    or p in ("compose.yaml", ".dockerignore")]
        selected += ["scripts/azure_smoke.py", "infra/azure/prepare-host.sh"]
        archive = evidence / "source.tar.gz"
        manifest = build_source_archive(ROOT, selected, archive)
        state["source_archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        (evidence / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        save()
        az("group", "create", "--name", group, "--location", args.location, "--tags",
           "purpose=appliance-energy-cloud-smoke", "lifecycle=temporary", f"runId={run_id}", "-o", "json",
           label="create-dedicated-group")
        ownership = True
        deployment = ["--resource-group", group, "--template-file", str(ROOT / "infra/azure/lab.bicep"),
                      "--parameters", "@" + str(parameter_file), "-o", "json"]
        preview = json.loads(az("deployment", "group", "what-if", *deployment, "--no-pretty-print",
                                label="what-if", timeout=600))
        assert preview.get("status") == "Succeeded", "what-if did not succeed"
        state["phase"] = "provisioning"
        state["billing_started_at_utc"] = datetime.now(timezone.utc).isoformat()
        save()
        az("deployment", "group", "create", *deployment, label="deploy", timeout=1200)
        address = az("network", "public-ip", "show", "-g", group, "-n", prefix + "-ip",
                     "--query", "ipAddress", "-o", "tsv", label="public-address").strip()
        state["public_address"] = address
        save()
        host_key = json.loads(az("vm", "run-command", "invoke", "-g", group, "-n", prefix + "-vm",
                                "--command-id", "RunShellScript", "--scripts", "cat /etc/ssh/ssh_host_ed25519_key.pub",
                                "-o", "json", label="attest-host-key", timeout=300))
        public_host_key = next(line for item in host_key["value"] for line in item["message"].splitlines()
                               if line.startswith("ssh-ed25519 "))
        known = evidence / "known_hosts"
        known.write_text(address + " " + " ".join(public_host_key.split()[:2]) + "\n", encoding="utf-8")
        ssh_options = ["-i", str(key), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                       "-o", "UserKnownHostsFile=" + str(known), "-o", "ConnectTimeout=20"]
        destination = "appliance@" + address
        run(["scp", *ssh_options, archive, destination + ":source.tar.gz"], "upload-source", timeout=180)
        run(["ssh", *ssh_options, destination,
             "mkdir -p appliance-energy && tar -xzf source.tar.gz -C appliance-energy && "
             "cd appliance-energy && sudo bash infra/azure/prepare-host.sh"], "prepare-host", timeout=1200)
        state["phase"] = "runtime"
        save()
        try:
            run(["ssh", *ssh_options, destination,
                 "set -eu; cd appliance-energy; python3 -m venv .tools; "
                 ".tools/bin/pip -q install uv==0.8.22; "
                 ".tools/bin/uv sync --project simulator --locked; "
                 ".tools/bin/uv run --project simulator --locked python scripts/bootstrap.py --devices 100; "
                 "docker compose up -d --build --wait --wait-timeout 180; "
                 ".tools/bin/uv run --project simulator --locked python scripts/azure_smoke.py"],
                "runtime-and-acceptance", timeout=2400)
        finally:
            # Preserve bounded diagnostics even when acceptance fails, before
            # deleting the host. No environment, keys or certificate files.
            try:
                run(["ssh", *ssh_options, destination,
                     "set -e; cd appliance-energy; mkdir -p artifacts; "
                     "docker compose ps -a --format json > artifacts/azure-compose.json; "
                     "docker inspect --format '{{json .NetworkSettings.Ports}}' $(docker compose ps -aq) "
                     "> artifacts/azure-ports.json 2>/dev/null || true; "
                     "docker compose logs --tail 1000 backend > artifacts/azure-backend.log 2>&1 || true; "
                     "docker compose logs --tail 200 postgres > artifacts/azure-postgres.log 2>&1 || true; "
                     "docker version --format '{{.Server.Version}}' > artifacts/azure-docker-version.txt; "
                     "if [ -d data ]; then tar -czf /home/appliance/evidence.tar.gz artifacts data; "
                     "else tar -czf /home/appliance/evidence.tar.gz artifacts; fi"],
                    "capture-evidence", timeout=180)
                run(["scp", *ssh_options, destination + ":evidence.tar.gz", evidence / "evidence.tar.gz"],
                    "download-evidence", timeout=180)
            except Exception as diagnostic_error:
                state["diagnostic_error"] = str(diagnostic_error)
                save()
        if not (evidence / "evidence.tar.gz").is_file():
            raise RuntimeError("acceptance finished but its evidence archive was not downloaded")
        state["phase"] = "verified"
        save()
    except BaseException as exc:
        state["phase"] = "failed"
        state["error"] = str(exc)
        save()
        raise
    finally:
        if ownership:
            ownership_record = json.loads(az("group", "show", "--name", group, "-o", "json",
                                              label="verify-cleanup-ownership", cleanup=True))
            if ownership_record.get("tags", {}).get("runId") != run_id:
                raise RuntimeError("resource-group ownership mismatch; refusing deletion")
            az("group", "delete", "--name", group, "--yes", label="delete-owned-group", timeout=900, cleanup=True)
            absent = az("group", "exists", "--name", group, label="verify-group-deleted", cleanup=True).strip() == "false"
            state["resource_group_deleted"] = absent
            state["cleanup_finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            save()
            if not absent:
                raise RuntimeError("resource group still exists after teardown")
        print(json.dumps({k: state.get(k) for k in ("phase", "resource_group_deleted", "started_at_utc", "cleanup_finished_at_utc")}), flush=True)


if __name__ == "__main__":
    main()
