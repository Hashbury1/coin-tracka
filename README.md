# Running Coin Tracka on Local Kubernetes (kind)

This runs the exact same topology you'd use in a real deployment — real
Deployments, Services, Ingress, and a real Prometheus Operator — just on a
kind cluster instead of a cloud provider. No AWS/GCP/Azure involved.

## Prerequisites

```bash
# Arch Linux
sudo pacman -S kind kubectl helm
```

## 1. Edit the frontend host path

`kind-config.yaml`'s `extraMounts` needs an absolute path to your repo:

```bash
sed -i "s|/home/hashbury/coin-tracka|$(pwd)|" infra/k8s/kind-config.yaml
grep hostPath infra/k8s/kind-config.yaml
```

## 2. Create the cluster

```bash
kind create cluster --config infra/k8s/kind-config.yaml --name coin-tracka
kubectl cluster-info --context kind-coin-tracka
```

## 3. Install ingress-nginx (kind-specific manifest — uses hostPort, not LoadBalancer)

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml

# Wait for it to actually be ready before continuing - Ingress resources
# applied before this is ready will sit stuck with no address.
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

## 4. Build your service images and load them into kind

kind runs its own containerd inside the cluster nodes — it can't see images
in your local Docker daemon unless you explicitly load them in. This is the
single most common "ImagePullBackOff on a perfectly good local image" gotcha.

```bash
docker compose build ingestion scoring api
kind load docker-image coin-tracka-ingestion:latest --name coin-tracka
kind load docker-image coin-tracka-scoring:latest --name coin-tracka
kind load docker-image coin-tracka-api:latest --name coin-tracka
```

(Adjust the image names above if your actual built tags differ — check
with `docker images | grep coin-tracka`.)

## 5. Create the namespace, config, and secrets

```bash
kubectl apply -f infra/k8s/00-namespace-config.yaml

# Real secret, generated FROM your existing .env - never commit this file,
# and note the command itself never writes .env's contents to disk anywhere new.
kubectl create secret generic app-secrets --namespace coin-tracka \
  $(grep -v '^#' .env | grep -v '^$' | sed 's/^/--from-literal=/' | tr '\n' ' ')
```

## 6. Deploy the stateful services first

```bash
kubectl apply -f infra/k8s/01-timescaledb-init-configmap.yaml
kubectl apply -f infra/k8s/02-timescaledb.yaml
kubectl apply -f infra/k8s/03-redis.yaml

# Wait for both before deploying anything that depends on them -
# the initContainers in the next step will wait too, but there's no
# reason to race it.
kubectl wait --namespace coin-tracka --for=condition=ready pod -l app=redis --timeout=60s
kubectl rollout status statefulset/timescaledb -n coin-tracka --timeout=120s
```

## 7. Deploy the app services

```bash
kubectl apply -f infra/k8s/04-ingestion.yaml
kubectl apply -f infra/k8s/05-scoring.yaml
kubectl apply -f infra/k8s/06-api.yaml
kubectl apply -f infra/k8s/07-frontend.yaml
kubectl apply -f infra/k8s/08-ingress.yaml
```

Check everything's actually running before moving on:

```bash
kubectl get pods -n coin-tracka
```

If anything shows `Init:0/2` for a long time, it's stuck in an
initContainer waiting on Redis/TimescaleDB — check with:
```bash
kubectl logs -n coin-tracka <pod-name> -c wait-for-timescaledb
```

## 8. Add hostnames to `/etc/hosts`

```bash
echo "127.0.0.1 api.coin-tracka.local app.coin-tracka.local grafana.coin-tracka.local" | sudo tee -a /etc/hosts
```

Test the API:
```bash
curl http://api.coin-tracka.local/health
```

Open the dashboard: `http://app.coin-tracka.local`

## 9. Install kube-prometheus-stack

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  -f infra/k8s/kube-prometheus-stack-values.yaml
```

This takes a few minutes — it's installing Prometheus, Alertmanager,
Grafana, and the Operator itself. Watch it:
```bash
kubectl get pods -n monitoring --watch
```

## 10. Wire up the dashboard and ServiceMonitors

```bash
kubectl apply -f infra/k8s/10-grafana-dashboard-configmap.yaml
kubectl apply -f infra/k8s/09-servicemonitors.yaml
```

Open Grafana: `http://grafana.coin-tracka.local` (login: `admin` / `admin`
— it's a local cluster, this is fine here, would never be fine anywhere
real). Your existing "Meme Tracker Overview" dashboard should already be
imported via the sidecar within about a minute.

## 11. Verify Prometheus is actually scraping your services

```bash
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090
```

Open `http://localhost:9090/targets` — you should see `ingestion`,
`scoring`, and `api` all listed with state `UP`. If they're missing
entirely (not even shown as `DOWN`), the ServiceMonitor's `release: prometheus`
label doesn't match your Helm release name — see the comment in
`09-servicemonitors.yaml`.

---

## Tearing it down

```bash
kind delete cluster --name coin-tracka
```

This deletes everything — cluster, PVC-backed data, all of it — cleanly,
since it never touched anything outside the kind container itself.

## What this setup deliberately does NOT do

- No TLS on the Ingress (no cert-manager) — fine locally, would be a real
  gap in production
- Grafana admin password is a hardcoded `admin`/`admin` — acceptable only
  because this never leaves your machine
- Single replica everywhere — no actual HA being tested, just topology
- Alertmanager has no real notification channel wired up (no Slack/email) —
  alerts still evaluate and appear as firing in the UI, they just don't
  page anyone, which is an honest reflection of "local-only," not a bug
  to fix here
