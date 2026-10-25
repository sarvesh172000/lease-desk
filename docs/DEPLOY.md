# Deploying Lease Desk: Azure (backend) and Vercel (frontend)

```
browser ──▶ Vercel (Next.js) ──/api/* proxy──▶ Azure Container Apps: leasedesk-api ──▶ Azure Database for PostgreSQL 16
                                                Azure Container Apps: leasedesk-worker ─┘
ASI:One ──▶ Agentverse mailboxes ◀── Azure Container Apps: leasedesk-agents ──▶ leasedesk-api
                                     both publish to SpacetimeDB Maincloud (optional)
```

Three things shape this:

- **One origin for the browser.** The API's session cookie is `SameSite=Lax`,
  which a browser never sends on a cross-site request, so a Vercel page calling
  an `azurecontainerapps.io` API directly would sign in and then get 401 on
  everything. Next.js proxies `/api/*` to the API (`frontend/next.config.mjs`,
  `LEASEDESK_API_ORIGIN`), so the browser only talks to the Vercel origin.
- **No volume for documents.** The image is built with `BAKE_DEMO_DATA=1`,
  which runs the (deterministic) generator into `/app/data`; the setup job
  seeds the database from the same generator, so the files match byte for byte.
- **The demo needs no model key.** The model answers it uses are committed
  (`data/reference/llm_cache`, copied to `/app/reference`).

## On an Azure for Students subscription (what the live deployment needed)

The live deployment (web app at https://lease-desk-ten.vercel.app; resource
group `leasedesk-rg`; API at
`https://leasedesk-api.thankfulhill-bf35cf6d.northcentralus.azurecontainerapps.io`)
ran on *Azure for Students*, which differs from the steps below in four places:

1. **Allowed regions** are set by policy (`az policy assignment list`): here
   westus2, canadacentral, norwayeast, northcentralus, francecentral. And
   **Postgres flexible server is not offered in westus2** to this subscription
   (`az postgres flexible-server list-skus -l <region>` is empty), so the
   database, the environment and the apps are in **northcentralus**. The
   registry can stay anywhere.
2. **ACR Tasks are not allowed** (`az acr build` → `TasksOperationsNotAllowed`).
   Build locally for the platform Container Apps runs, and push:

   ```bash
   az acr login -n $ACR
   docker buildx build --platform linux/amd64 --build-arg BAKE_DEMO_DATA=1 -f backend/Dockerfile \
     -t $ACR.azurecr.io/leasedesk-backend:1 --push .
   docker buildx build --platform linux/amd64 -f deploy/Dockerfile.agents \
     -t $ACR.azurecr.io/leasedesk-agents:1 --push .
   ```
3. **The environment is an "express" environment, which has no Jobs.** Run
   `deploy/setup-demo.sh` from a laptop instead, in the same image, through a
   firewall rule for the laptop's address that is removed afterwards:

   ```bash
   IP=$(curl -s https://api.ipify.org)
   az postgres flexible-server firewall-rule create -g $RG --server-name $PG --name setup-from-laptop \
     --start-ip-address $IP --end-ip-address $IP
   docker run --rm -e LEASEDESK_DB_HOST=$PG.postgres.database.azure.com -e LEASEDESK_DB_PORT=5432 \
     -e LEASEDESK_DB_NAME=leasedesk -e LEASEDESK_DB_OWNER=leasedesk -e LEASEDESK_DB_OWNER_PASSWORD="$PGPASS" \
     -e LEASEDESK_LEASE_AGENT_PASSWORD="$PW_AGENT" -e LEASEDESK_LEASE_GATEWAY_PASSWORD="$PW_GATEWAY" \
     -e LEASEDESK_LEASE_API_PASSWORD="$PW_API" -e LEASEDESK_LEASE_READER_PASSWORD="$PW_READER" \
     -e PGSSLMODE=require -e LEASEDESK_DATA_DIR=/app/data <the backend image> sh /app/deploy/setup-demo.sh
   az postgres flexible-server firewall-rule delete -g $RG --server-name $PG --name setup-from-laptop --yes
   ```
   (In this CLI version the firewall-rule commands take `--server-name` for
   the server and `--name` for the rule.)
4. **`az containerapp create --args` cannot take an argument that starts with
   `-`** (`python -m app.jobs.worker` → "unrecognized arguments"). The worker
   and the agents were created from a spec instead
   (`az containerapp create -g $RG -n leasedesk-worker --yaml spec.yaml`), with
   `command: ["python"]`, `args: ["-m", "app.jobs.worker"]`, the secrets and the
   registry in it. Keep that file out of git (it holds the secrets) and delete
   it after use. `az containerapp logs show` does not work on express
   environments either; `az containerapp replica list` shows each replica's
   state and restart count.

## 0. Tools and names

```bash
brew install azure-cli && az login          # opens a browser; pick the subscription with the credits
az extension add --name containerapp --upgrade
az provider register -n Microsoft.App --wait
az provider register -n Microsoft.OperationalInsights --wait
az provider register -n Microsoft.DBforPostgreSQL --wait

RG=leasedesk-rg  LOC=westus2  SFX=$RANDOM
ACR=leasedeskacr$SFX  PG=leasedesk-pg-$SFX  ENV=leasedesk-env
```

Generate the secrets once and keep them out of git (a password manager, or a
local file that is gitignored):

```bash
PGPASS=$(openssl rand -base64 24 | tr -d '/+=')
for r in AGENT GATEWAY API READER; do eval "PW_$r=$(openssl rand -hex 16)"; done
SESSION_SECRET=$(openssl rand -hex 32)
```

## 1. Registry and images

```bash
az group create -n $RG -l $LOC
az acr create -g $RG -n $ACR --sku Basic --admin-enabled true
az acr build -r $ACR -t leasedesk-backend:1 --build-arg BAKE_DEMO_DATA=1 -f backend/Dockerfile .
az acr build -r $ACR -t leasedesk-agents:1 -f deploy/Dockerfile.agents .
ACR_PASS=$(az acr credential show -n $ACR --query 'passwords[0].value' -o tsv)
```

## 2. Postgres 16

```bash
az postgres flexible-server create -g $RG -n $PG -l $LOC --version 16 \
  --tier Burstable --sku-name Standard_B1ms --storage-size 32 \
  --admin-user leasedesk --admin-password "$PGPASS" --public-access 0.0.0.0 --yes
az postgres flexible-server parameter set -g $RG -s $PG -n azure.extensions -v PGCRYPTO
```

`--public-access 0.0.0.0` admits Azure services (the container apps) only.
`pgcrypto` must be allow-listed before the schema can create it. Azure
requires TLS, so every container sets `PGSSLMODE=require`. The admin user is
the database owner: it migrates and creates the four application roles.

## 3. Container Apps

```bash
az containerapp env create -g $RG -n $ENV -l $LOC

SECRETS="pg-owner=$PGPASS pw-agent=$PW_AGENT pw-gateway=$PW_GATEWAY pw-api=$PW_API pw-reader=$PW_READER session=$SESSION_SECRET"
DB_ENV="LEASEDESK_DB_HOST=$PG.postgres.database.azure.com LEASEDESK_DB_PORT=5432 LEASEDESK_DB_NAME=leasedesk \
  LEASEDESK_DB_OWNER=leasedesk LEASEDESK_DB_OWNER_PASSWORD=secretref:pg-owner \
  LEASEDESK_LEASE_AGENT_PASSWORD=secretref:pw-agent LEASEDESK_LEASE_GATEWAY_PASSWORD=secretref:pw-gateway \
  LEASEDESK_LEASE_API_PASSWORD=secretref:pw-api LEASEDESK_LEASE_READER_PASSWORD=secretref:pw-reader \
  PGSSLMODE=require LEASEDESK_DATA_DIR=/app/data"
REG="--registry-server $ACR.azurecr.io --registry-username $ACR --registry-password $ACR_PASS"
IMAGE=$ACR.azurecr.io/leasedesk-backend:1
```

**Setup job** (once; `deploy/setup-demo.sh` is idempotent, so re-running it is safe):

```bash
az containerapp job create -g $RG -n leasedesk-setup --environment $ENV --trigger-type Manual \
  --replica-timeout 1800 --image $IMAGE $REG --cpu 1 --memory 2Gi \
  --secrets $SECRETS --env-vars $DB_ENV --command sh --args /app/deploy/setup-demo.sh
az containerapp job start -g $RG -n leasedesk-setup
az containerapp job execution list -g $RG -n leasedesk-setup -o table      # wait for Succeeded
```

**API and worker** (demo mode on: the role switcher for judges; see the note below):

```bash
az containerapp create -g $RG -n leasedesk-api --environment $ENV --image $IMAGE $REG \
  --target-port 8000 --ingress external --min-replicas 1 --cpu 1 --memory 2Gi \
  --secrets $SECRETS --env-vars $DB_ENV LEASEDESK_SESSION_SECRET=secretref:session \
    LEASEDESK_COOKIE_SECURE=1 LEASEDESK_DEMO_MODE=1 LEASEDESK_CORS_ORIGINS=https://placeholder.invalid
API=https://$(az containerapp show -g $RG -n leasedesk-api --query properties.configuration.ingress.fqdn -o tsv)
curl -s $API/ready          # {"status":"ready","database":"ok","chain":"verified"}

az containerapp create -g $RG -n leasedesk-worker --environment $ENV --image $IMAGE $REG \
  --min-replicas 1 --cpu 0.5 --memory 1Gi --secrets $SECRETS --env-vars $DB_ENV \
  --command python --args -m app.jobs.worker
```

Optional on both: `SPACETIME_DB`, `SPACETIME_TOKEN` (the live mirror) and
`ANTHROPIC_API_KEY` (anything not committed calls Claude).

**Agents** (stop any copy running elsewhere first: two copies at the same
addresses would read the same mailboxes):

```bash
az containerapp create -g $RG -n leasedesk-agents --environment $ENV \
  --image $ACR.azurecr.io/leasedesk-agents:1 $REG --min-replicas 1 --max-replicas 1 --cpu 0.5 --memory 1Gi \
  --secrets seed-coord=... seed-recon=... seed-inv=... seed-appr=... asi=... \
  --env-vars LEASEDESK_API_URL=$API AGENT_SEED_COORDINATOR=secretref:seed-coord \
    AGENT_SEED_RECONCILIATION=secretref:seed-recon AGENT_SEED_INVESTIGATION=secretref:seed-inv \
    AGENT_SEED_APPROVALS=secretref:seed-appr ASI_ONE_API_KEY=secretref:asi
```

The seeds are the ones the agents were registered with (the repo's `.env`);
the same seeds give the same addresses and the same Agentverse mailboxes.

## 4. Vercel

1. vercel.com → **Add New → Project** → import the GitHub repo.
2. **Root Directory: `frontend`** (Next.js is detected).
3. Environment variables (Production):

   | Name | Value |
   |---|---|
   | `LEASEDESK_API_ORIGIN` | `$API` (the proxy target; server side only) |
   | `NEXT_PUBLIC_API_URL` | `/` (relative: every call goes to this site's `/api`, which the proxy forwards) |
   | `NEXT_PUBLIC_SPACETIME_URI` | `wss://maincloud.spacetimedb.com` (optional) |
   | `NEXT_PUBLIC_SPACETIME_DB` | `leasedesk-live` (optional) |

   Leave `NEXT_PUBLIC_USE_FIXTURES` unset. `NEXT_PUBLIC_*` values are inlined at
   build time: change one, redeploy.
4. Deploy, then point the API's CORS at the real URL:

   ```bash
   az containerapp update -g $RG -n leasedesk-api --set-env-vars LEASEDESK_CORS_ORIGINS=https://<your-app>.vercel.app
   ```

   On an express environment the running replica keeps its old environment
   (no revision suffixes, and `revision restart` failed). Scale to two
   replicas, check the new one answers a preflight, then scale back to one;
   the older replica is the one removed:

   ```bash
   az containerapp update -g $RG -n leasedesk-api --min-replicas 2 --max-replicas 2
   az containerapp update -g $RG -n leasedesk-api --min-replicas 1 --max-replicas 1
   ```

   The browser goes through the `/api` proxy, so CORS only matters for
   anything that calls the API directly.

## 5. Check

- `$API/ready` → ready, chain verified.
- The Vercel URL: sign in as `priya.raghunathan@northbaypt.example` / `demo`;
  Today is as of July with $25,736.36 held; *Run investigation* on the July
  hold finds the amendment (+$443,255.70, four balanced entries).
- ASI:One: in a chat with **Northbay Lease Desk**, `help`, then
  `pair <code>` from the web app's *your name → Connect chat*.

## Demo mode on a public URL

`LEASEDESK_DEMO_MODE=1` gives judges the role switcher, and also lets anyone
with the link switch identity and reset the database. `0` makes people sign
in as themselves, but the seeded people's password (`demo`) is in the README,
so it would need real per-role passwords. For a judged demo, `1` with the URL
shared only on Devpost is the practical choice; re-run the setup job if the
data is broken.

## Cost and teardown

Roughly $15–30 a month on credits (a B1ms Postgres, three always-on
replicas). When the demo is over: `az group delete -n $RG`.
