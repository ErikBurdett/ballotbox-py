# AWS Production Deployment Guide

This guide prepares **The Ballot Box** for a first AWS production deployment while keeping the existing local Docker setup unchanged.

Recommended production target:

- **Amazon ECR** for the production image
- **Amazon ECS on Fargate** for `web`, `worker`, and `beat`
- **Amazon RDS for PostgreSQL + PostGIS** for the database
- **Amazon ElastiCache for Redis/Valkey** for Celery/cache
- **Application Load Balancer + ACM** for HTTPS
- **CloudWatch Logs** for container logs
- **Secrets Manager or SSM Parameter Store** for secrets
- **Optional later:** S3 + CloudFront for static and large GeoJSON files

AWS docs:

- ECR: <https://docs.aws.amazon.com/AmazonECR/latest/userguide/what-is-ecr.html>
- ECS Fargate: <https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html>
- ECS task definitions: <https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definitions.html>
- RDS PostgreSQL: <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_PostgreSQL.html>
- PostGIS on RDS: <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.PostGIS.html>
- ElastiCache: <https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/WhatIs.html>
- ALB: <https://docs.aws.amazon.com/elasticloadbalancing/latest/application/introduction.html>
- ACM certificates: <https://docs.aws.amazon.com/acm/latest/userguide/acm-overview.html>
- Route 53: <https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/Welcome.html>
- Secrets Manager: <https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html>
- SSM Parameter Store: <https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html>
- CloudWatch Logs: <https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/WhatIsCloudWatchLogs.html>
- AWS Pricing Calculator: <https://calculator.aws/>

## 1. What Is Ready

Production-ready pieces now in this branch:

- `Dockerfile.prod` builds a clean production image.
- `scripts/start-web-prod.sh` starts Gunicorn.
- `scripts/start-worker-prod.sh` starts Celery worker.
- `scripts/start-beat-prod.sh` starts Celery beat.
- `.dockerignore` excludes local cache, virtualenvs, Docker data, tests, and editor files from the production build context.
- Static assets are built during the Docker image build:
  - Tailwind CSS via Node build stage
  - Django `collectstatic` into the image for WhiteNoise
- Runtime image includes GeoDjango/GDAL/GEOS/PROJ/Postgres client libraries.
- Existing local development files remain unchanged:
  - `Dockerfile`
  - `docker-compose.yml`

Current status as of local smoke testing:

- [x] Production image builds locally with `Dockerfile.prod`.
- [x] Production image runs locally on `http://localhost:8001/`.
- [x] Gunicorn starts successfully.
- [x] Home page responds locally.
- [x] Texas map responds locally.
- [x] Static CSS is served locally.
- [x] Production image passes `python manage.py check` against the local Compose Postgres/Redis network.
- [x] AWS CLI configured for non-root SSO admin profile `erik-pia-admin`.
- [x] ECR repository `ballotbox-prod` created in `us-east-2`.
- [x] Production image pushed to ECR as `426771918029.dkr.ecr.us-east-2.amazonaws.com/ballotbox-prod:latest`.
- [x] RDS PostgreSQL instance `ballotbox-prod-db` created and available.
- [ ] ElastiCache Redis/Valkey configured.
- [ ] Application secrets configured.
- [ ] ECS cluster/task definitions/services configured.
- [ ] ALB, ACM, Route 53 configured.

You are currently in the **AWS infrastructure setup phase**. Local production-readiness is complete, ECR is complete, and RDS has been created. The next infrastructure dependency is Redis/Valkey via ElastiCache.

Important account note: this AWS account already hosts 3 Amplify React apps. The steps below create new IAM users/roles, ECR/ECS/RDS/Redis/ALB resources, and should not modify Amplify apps. Do not delete, rename, or change Amplify resources, Route 53 records, ACM certificates, or IAM roles that are currently used by those apps.

## 2. Local Checklist Before AWS

From the repository root:

```bash
git status
```

Confirm you are on the deployment branch and do not have unrelated local changes.

Run the normal app test suite:

```bash
docker compose exec web bash -lc 'cd /app/src && python manage.py check'
docker compose exec web bash -lc 'cd /app/src && python -m pytest /app/tests -q'
```

Check migrations:

```bash
python manage.py makemigrations --check --dry-run
python manage.py migrate
```

Refresh local map data if needed:

```bash
python manage.py fetch_tceq_groundwater_geojson
python manage.py sync_tceq_gcd_jurisdictions
python manage.py sync_tceq_water_district_jurisdictions --types MUD,WCID,SUD,RA
```

Optional full map refresh:

```bash
python manage.py fetch_texas_legislative_geojson -v 2
```

## 3. Build And Smoke-Test The Production Image Locally

Build:

```bash
docker build -f Dockerfile.prod -t ballotbox-prod:local .
```

Run Django system check in the production image, attached to your local Compose network:

```bash
docker run --rm \
  --network ballotbox-py_default \
  -e DJANGO_DEBUG=0 \
  -e DJANGO_SECRET_KEY=local-prod-test-secret \
  -e DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1 \
  -e DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8001 \
  -e DATABASE_URL=postgis://avd:avd@db:5432/avd \
  -e REDIS_URL=redis://redis:6379/0 \
  -e CELERY_BROKER_URL=redis://redis:6379/1 \
  -e CELERY_RESULT_BACKEND=redis://redis:6379/2 \
  ballotbox-prod:local \
  python manage.py check
```

Run the production web container locally:

```bash
docker run --rm \
  --network ballotbox-py_default \
  -p 8001:8000 \
  -e DJANGO_DEBUG=0 \
  -e DJANGO_SECRET_KEY=local-prod-test-secret \
  -e DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1 \
  -e DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8001 \
  -e DATABASE_URL=postgis://avd:avd@db:5432/avd \
  -e REDIS_URL=redis://redis:6379/0 \
  -e CELERY_BROKER_URL=redis://redis:6379/1 \
  -e CELERY_RESULT_BACKEND=redis://redis:6379/2 \
  ballotbox-prod:local
```

Open:

```text
http://localhost:8001/
http://localhost:8001/texas/ballot-map/
```

Confirm:

- Pages render.
- Static CSS loads.
- Texas map loads.
- Water layers still work.
- Admin login page loads.

## 4. Required Production Environment Variables

Store these in AWS Secrets Manager or SSM Parameter Store.

Required:

```env
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=<strong-random-secret>
DJANGO_ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com,<alb-dns-name-if-needed>
DJANGO_CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
DATABASE_URL=postgis://<user>:<password>@<rds-endpoint>:5432/<db-name>
REDIS_URL=redis://<elasticache-primary-endpoint>:6379/0
CELERY_BROKER_URL=redis://<elasticache-primary-endpoint>:6379/1
CELERY_RESULT_BACKEND=redis://<elasticache-primary-endpoint>:6379/2
```

Recommended:

```env
BALLOTPEDIA_API_KEY=<if available>
BALLOTPEDIA_SYNC_STATE_CODE=TX
BALLOTPEDIA_GEO_BEAT_ENABLED=1
DEFAULT_FROM_EMAIL=noreply@yourdomain.com
SUBMISSIONS_NOTIFY_EMAIL=<staff-email>
SUBMISSIONS_STAFF_PIN=<non-default-pin>
```

For first deploy without Ballotpedia production access:

```env
BALLOTPEDIA_GEO_BEAT_ENABLED=0
```

## 5. AWS Account Safety, IAM, And AWS CLI Setup

You said you are currently using the AWS **root user** and have not configured IAM yet. Do not use the root user for day-to-day deployment work.

Root user should only be used for account-level tasks such as:

- Enabling MFA on the root account.
- Creating the first admin IAM Identity Center / IAM admin user.
- Updating account contact/billing/security settings.

AWS docs:

- Root user best practices: <https://docs.aws.amazon.com/accounts/latest/reference/root-user-best-practices.html>
- IAM best practices: <https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html>
- IAM Identity Center: <https://docs.aws.amazon.com/singlesignon/latest/userguide/what-is.html>
- AWS CLI install/update: <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>
- AWS CLI configure: <https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html>

### 5.1 Protect Existing Amplify Apps First

Before creating anything for this Django app:

1. Open the Amplify console: <https://console.aws.amazon.com/amplify/>
2. Confirm your 3 Amplify apps are healthy.
3. Record their:
   - App names
   - App IDs
   - Branches
   - Custom domains
   - Connected repositories
4. Do not change Amplify hosting, domains, build settings, environment variables, or service roles while deploying this app.

Useful read-only inventory commands after AWS CLI is configured:

```bash
aws amplify list-apps
aws route53 list-hosted-zones
aws acm list-certificates --region us-east-1
```

These commands only list resources.

### 5.2 Enable Root MFA

Sign in as root one final time and enable MFA:

1. AWS console: <https://console.aws.amazon.com/>
2. Account menu → Security credentials
3. Enable MFA for root user

Do this before creating deploy credentials.

### 5.3 Preferred: Use IAM Identity Center

Recommended setup:

1. Open IAM Identity Center: <https://console.aws.amazon.com/singlesignon/>
2. Enable IAM Identity Center if it is not enabled.
3. Create a user for yourself.
4. Create an admin permission set for initial setup.
5. Assign yourself access to the AWS account.
6. Use the AWS access portal to configure CLI credentials.

CLI setup with Identity Center:

```bash
aws configure sso
```

Then verify:

```bash
aws sts get-caller-identity
```

You should see an assumed role/user that is **not** the root user.

### 5.4 Simpler Alternative: Create A Dedicated IAM Deploy User

If you do not want to use IAM Identity Center yet, create a dedicated IAM user.

1. Open IAM: <https://console.aws.amazon.com/iam/>
2. Users → Create user
3. User name: `ballotbox-deploy`
4. Select programmatic access / access key for CLI use.
5. Attach permissions.

For first setup, you can temporarily attach:

- `AdministratorAccess`

After deployment is working, replace this with least-privilege policies for ECR/ECS/RDS/ElastiCache/ELB/ACM/Route53/Secrets/CloudWatch.

Create access key:

1. IAM → Users → `ballotbox-deploy`
2. Security credentials
3. Create access key
4. Use case: CLI
5. Save the access key ID and secret access key securely.

Configure locally:

```bash
aws configure --profile ballotbox-deploy
```

Enter:

```text
AWS Access Key ID: <from IAM>
AWS Secret Access Key: <from IAM>
Default region name: us-east-1
Default output format: json
```

Use the profile:

```bash
export AWS_PROFILE=ballotbox-deploy
aws sts get-caller-identity
```

Confirm the returned ARN is the IAM deploy user, not root.

### 5.5 Local AWS CLI Checklist

Before creating app resources:

```bash
aws --version
aws sts get-caller-identity
aws configure list
```

Confirm:

- [ ] AWS CLI v2 is installed.
- [ ] You are using a non-root identity.
- [ ] Default region is selected, recommended `us-east-1`.
- [ ] You can list existing Amplify apps without changing them:

```bash
aws amplify list-apps
```

### 5.6 Naming To Avoid Collisions With Amplify

Use a unique prefix for all new resources:

```bash
export AWS_REGION=us-east-1
export APP_NAME=ballotbox
export ENV_NAME=prod
export NAME_PREFIX=ballotbox-prod
```

Create new resources with names like:

- `ballotbox-prod` ECR repository
- `ballotbox-prod` ECS cluster
- `ballotbox-prod-web` ECS service
- `ballotbox-prod-worker` ECS service
- `ballotbox-prod-beat` ECS service
- `ballotbox-prod-db` RDS instance
- `ballotbox-prod-redis` ElastiCache replication group / cluster
- `/ballotbox/prod/env` secret
- `/ecs/ballotbox/web` CloudWatch log group

Do not reuse names, domains, certificates, hosted zone records, or roles associated with Amplify apps.

## 6. AWS Setup Steps

### 6.1 Choose Region

Use one region consistently. The examples below assume `us-east-1`.

```bash
export AWS_REGION=us-east-1
export APP_NAME=ballotbox
```

If using the IAM deploy profile:

```bash
export AWS_PROFILE=ballotbox-deploy
```

### 6.2 Create ECR Repository

AWS console:

- ECR service: <https://console.aws.amazon.com/ecr/>

CLI:

```bash
aws ecr create-repository --repository-name ballotbox-prod --region "$AWS_REGION"
```

Authenticate Docker:

```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
```

Build and push:

```bash
docker build -f Dockerfile.prod -t ballotbox-prod:latest .
docker tag ballotbox-prod:latest "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/ballotbox-prod:latest"
docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/ballotbox-prod:latest"
```

### 6.3 Create VPC / Networking

For a first deployment, use the default VPC or create a small dedicated VPC.

Recommended:

- Public subnets for ALB
- Private subnets for ECS tasks, RDS, and Redis
- NAT Gateway only if ECS tasks in private subnets need outbound internet

Cost note: NAT Gateway can cost more than small app compute. For first low-budget deploy, public subnet ECS tasks with locked-down security groups can be acceptable, but private subnets are cleaner.

VPC docs: <https://docs.aws.amazon.com/vpc/latest/userguide/what-is-amazon-vpc.html>

### 6.4 Create RDS PostgreSQL With PostGIS

AWS console:

- RDS: <https://console.aws.amazon.com/rds/>

Recommended first deploy:

- Engine: PostgreSQL 16
- Instance: `db.t4g.micro` or `db.t4g.small`
- Storage: 20-50 GB gp3
- Multi-AZ: off for first low-cost deploy, on when production-critical
- Public access: no, if ECS is in same VPC/private subnets

After database exists, enable PostGIS:

```bash
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

You can run that from an ECS one-off task, a bastion, or your machine if networking allows.

Current RDS status:

- DB identifier: `ballotbox-prod-db`
- Status: `available`
- Region/AZ: `us-east-2` / `us-east-2c`
- Engine: PostgreSQL `18.3`
- Instance class: `db.t4g.small`
- Endpoint: `ballotbox-prod-db.cd6euswqcfjr.us-east-2.rds.amazonaws.com`
- Port: `5432`
- Master username: `ballotbox`
- VPC security group: `sg-06045755c5cd09b05`
- RDS-managed credentials secret:
  `arn:aws:secretsmanager:us-east-2:426771918029:secret:rds!db-4da2a1e5-fa3b-49aa-bc2d-41c0caee5ee3-lQ7jE1`

Notes:

- This database was created with PostgreSQL 18.3 instead of the originally recommended PostgreSQL 16.x. Continue if PostGIS is available for this engine version; otherwise recreate now before connecting ECS.
- `DBName` is currently blank/null, meaning no initial application database named `ballotbox` was created. For the first deploy, either:
  - use the default `postgres` database in `DATABASE_URL`, or
  - create a `ballotbox` database from inside the VPC before running migrations.
- Do not expose the DB publicly unless needed for a temporary, controlled admin task.

### 6.5 Create ElastiCache Redis/Valkey

AWS console:

- ElastiCache: <https://console.aws.amazon.com/elasticache/>

Recommended first deploy:

- Engine: Redis OSS or Valkey
- Node: `cache.t4g.micro`
- Cluster mode: disabled
- TLS/auth: enable if feasible
- Same VPC as ECS

### 6.6 Create Secrets

Use AWS Secrets Manager or SSM Parameter Store.

For Secrets Manager:

```bash
aws secretsmanager create-secret \
  --name /ballotbox/prod/env \
  --secret-string '{
    "DJANGO_DEBUG":"0",
    "DJANGO_SECRET_KEY":"replace-me",
    "DJANGO_ALLOWED_HOSTS":"yourdomain.com,www.yourdomain.com",
    "DJANGO_CSRF_TRUSTED_ORIGINS":"https://yourdomain.com,https://www.yourdomain.com",
    "DATABASE_URL":"postgis://user:password@host:5432/db",
    "REDIS_URL":"redis://redis-host:6379/0",
    "CELERY_BROKER_URL":"redis://redis-host:6379/1",
    "CELERY_RESULT_BACKEND":"redis://redis-host:6379/2",
    "BALLOTPEDIA_GEO_BEAT_ENABLED":"0"
  }'
```

### 6.7 Create ECS Cluster

AWS console:

- ECS: <https://console.aws.amazon.com/ecs/>

Create:

- Cluster: `ballotbox-prod`
- Launch type: Fargate

### 6.8 Create CloudWatch Log Groups

Create log groups:

```bash
/ecs/ballotbox/web
/ecs/ballotbox/worker
/ecs/ballotbox/beat
```

CloudWatch docs: <https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/Working-with-log-groups-and-streams.html>

### 6.9 Create ECS Task Definitions

Use the same image for all three tasks, changing only the command.

Web command:

```bash
bash /app/scripts/start-web-prod.sh
```

Worker command:

```bash
bash /app/scripts/start-worker-prod.sh
```

Beat command:

```bash
bash /app/scripts/start-beat-prod.sh
```

Suggested first sizes:

- Web: `0.5 vCPU`, `1 GB`
- Worker: `0.5 vCPU`, `1 GB`
- Beat: `0.25 vCPU`, `0.5 GB`

If memory pressure appears, move web/worker to `1 vCPU`, `2 GB`.

### 6.10 Create Application Load Balancer

AWS console:

- EC2 > Load Balancers: <https://console.aws.amazon.com/ec2/home#LoadBalancers>

Create:

- Internet-facing ALB
- Listener 80 -> redirect to 443
- Listener 443 -> ECS web target group
- Health check path: `/`

Create ACM certificate:

- ACM: <https://console.aws.amazon.com/acm/>

Attach cert to ALB HTTPS listener.

### 6.11 Create ECS Services

Create services:

- `ballotbox-web`: desired count 1 or 2, attached to ALB
- `ballotbox-worker`: desired count 1, no ALB
- `ballotbox-beat`: desired count 1, no ALB

Security groups:

- ALB allows 80/443 from internet.
- Web ECS service allows 8000 from ALB security group.
- Worker/beat do not need inbound traffic.
- RDS allows 5432 from ECS task security group.
- Redis allows 6379 from ECS task security group.

### 6.12 Run One-Off Tasks

After ECS task definition exists, run a one-off task for migrations:

```bash
python manage.py migrate --noinput
```

You can run this through ECS “Run task” and override the command:

```bash
python manage.py migrate --noinput
```

Optional one-off data tasks:

```bash
python manage.py fetch_tceq_groundwater_geojson
python manage.py sync_tceq_gcd_jurisdictions
python manage.py sync_tceq_water_district_jurisdictions --types MUD,WCID,SUD,RA
```

Note: `fetch_*geojson` writes files inside the task container. In the current image-based static setup, production map GeoJSON should be generated before image build or moved to S3/CloudFront later. For now, keep generated `src/static/geo/*.geojson` present before building/pushing the image.

### 6.13 Route 53 DNS

Create records:

- `yourdomain.com` -> ALB alias
- `www.yourdomain.com` -> ALB alias

Route 53 docs: <https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/routing-to-elb-load-balancer.html>

## 7. Cost Estimate

Always verify with <https://calculator.aws/>. Approximate low-traffic `us-east-1` monthly estimates:

| Service | Suggested size | Rough monthly |
| --- | --- | ---: |
| ECS Fargate web | 0.5 vCPU / 1 GB, 1 task always on | ~$18 |
| ECS Fargate worker | 0.5 vCPU / 1 GB, 1 task always on | ~$18 |
| ECS Fargate beat | 0.25 vCPU / 0.5 GB, 1 task always on | ~$9 |
| RDS PostgreSQL | db.t4g.micro, Single-AZ | ~$12 plus storage/backups |
| RDS storage | 20 GB gp3 | ~$2-3 |
| ElastiCache Redis | cache.t4g.micro | ~$12 |
| ALB | 1 ALB + low LCU usage | ~$18-25 |
| CloudWatch Logs | low volume | ~$1-5 |
| ECR storage | a few images | <$1-3 |
| Route 53 hosted zone | 1 zone | ~$0.50 |

Expected low-traffic baseline: **about $90-$120/month** before data transfer, NAT Gateway, backups, and taxes.

Important cost warning:

- A NAT Gateway is roughly **$30+/month plus data processing**. Avoid it for first deploy if budget matters, or use public subnet tasks with restrictive security groups until you need stricter networking.
- Multi-AZ RDS roughly doubles database compute cost.
- Fargate task count and size are the largest controllable app costs.

Official pricing pages:

- Fargate pricing: <https://aws.amazon.com/fargate/pricing/>
- RDS PostgreSQL pricing: <https://aws.amazon.com/rds/postgresql/pricing/>
- ElastiCache pricing: <https://aws.amazon.com/elasticache/pricing/>
- ALB pricing: <https://aws.amazon.com/elasticloadbalancing/pricing/>
- CloudWatch pricing: <https://aws.amazon.com/cloudwatch/pricing/>
- ECR pricing: <https://aws.amazon.com/ecr/pricing/>
- Route 53 pricing: <https://aws.amazon.com/route53/pricing/>

## 8. Deployment Checklist

Before pushing an image:

- [ ] `git status` is clean except intended deployment changes.
- [ ] Root MFA is enabled.
- [ ] AWS CLI is configured with a non-root IAM Identity Center role or IAM deploy user.
- [ ] Existing Amplify app names/domains are recorded.
- [ ] `aws amplify list-apps` works and no Amplify resources have been modified.
- [ ] `.env` is not committed.
- [ ] `docker build -f Dockerfile.prod -t ballotbox-prod:local .` succeeds.
- [ ] Production image passes `python manage.py check`.
- [ ] Full local test suite passes.
- [ ] `python manage.py makemigrations --check --dry-run` passes.
- [ ] Local map GeoJSON files needed by production exist in `src/static/geo/`.
- [ ] `DJANGO_DEBUG=0` is tested locally.
- [ ] `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` are known for production domain.
- [ ] RDS has PostGIS and pg_trgm enabled.
- [ ] Secrets are in AWS Secrets Manager or SSM, not in Git.
- [ ] ECS web task has ALB health checks passing.
- [ ] Worker and beat have CloudWatch logs.
- [ ] Migrations have run once in production.
- [ ] Admin user creation path is known:

```bash
python manage.py createsuperuser
```

Run as an ECS one-off task command override.

## 9. Release Flow

For each release:

```bash
docker build -f Dockerfile.prod -t ballotbox-prod:<git-sha> .
docker tag ballotbox-prod:<git-sha> "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/ballotbox-prod:<git-sha>"
docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/ballotbox-prod:<git-sha>"
```

Then:

1. Update ECS task definitions to the new image tag.
2. Run migration one-off task.
3. Deploy web service.
4. Deploy worker service.
5. Deploy beat service.
6. Watch CloudWatch logs.
7. Smoke-test:
   - `/`
   - `/officials/`
   - `/candidates/`
   - `/texas/ballot-map/`
   - `/texas/water-districts/`
   - `/admin/`

## 10. Later Improvements

After first deploy:

- Move `static/geo/*.geojson` to S3 + CloudFront.
- Add S3 static storage with `django-storages`.
- Convert Celery beat to ECS scheduled tasks where possible.
- Add RDS automated snapshot retention policy.
- Add AWS WAF on the ALB.
- Add deploy automation with GitHub Actions.
- Use Fargate ARM64 images for lower compute pricing if all dependencies build cleanly.
