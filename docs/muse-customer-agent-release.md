# Customer agent endpoint: code-only release procedure

This procedure is for a reviewed application-only release of the customer MCP
profile. It targets the existing EC2 instance `i-0cf5041ecb2a0045b` in
`us-east-1`, using its existing AWS Systems Manager (SSM) connection. It must
not run `deploy.sh`: that script changes IAM and instance-profile configuration,
CloudWatch retention, security-group ingress, and Elastic IP association.

This is a prepared procedure, not authorization to merge or deploy. It has not
been run against AWS. The local candidate must first be pushed, separately
reviewed, merged, and identified by the exact approved `main` commit SHA.

## Preconditions

1. The existing PR is merged and the deployment SHA is the reviewed `main`
   commit. Do not use a branch name or a moving `main` reference for the
   deployment checkout.
2. The operator confirms the existing SSM managed-node connection is online
   and already has permissions to run `AWS-RunShellScript` on the target.
   Do not attach roles, alter policies, or establish new access to make this
   procedure work.
3. The application runtime environment file already exists on the host at
   `/opt/ai-markdown-proxy/runtime.env`. Do not read, print, copy, or replace
   its contents.
4. Record the current production image ID and prior application commit before
   starting. Stop if either is unavailable; rollback requires a preserved
   image and known prior revision.

## Deploy

Set `RELEASE_SHA` to the full reviewed commit SHA and use the existing AWS CLI
SSM access for the target. Send one `AWS-RunShellScript` command to
`i-0cf5041ecb2a0045b` in `us-east-1` with these host commands, substituting the
verified SHA for `RELEASE_SHA`:

```bash
set -euo pipefail
RELEASE_SHA='<full-reviewed-main-sha>'
APP=/opt/ai-markdown-proxy
cd "$APP"
PREVIOUS_SHA="$(git rev-parse HEAD)"
PREVIOUS_IMAGE_ID="$(docker inspect --format '{{.Image}}' ai-markdown-proxy)"
test -n "$PREVIOUS_SHA" && test -n "$PREVIOUS_IMAGE_ID"
docker image tag "$PREVIOUS_IMAGE_ID" "ai-markdown-proxy:rollback-$PREVIOUS_SHA"
printf 'PREVIOUS_SHA=%s PREVIOUS_IMAGE_ID=%s\n' "$PREVIOUS_SHA" "$PREVIOUS_IMAGE_ID"
git fetch origin "$RELEASE_SHA"
test "$(git rev-parse FETCH_HEAD)" = "$RELEASE_SHA"
git checkout --detach "$RELEASE_SHA"
docker build -t "ai-markdown-proxy:$RELEASE_SHA" "$APP"
docker stop ai-markdown-proxy
docker rm ai-markdown-proxy
docker run -d --name ai-markdown-proxy --restart unless-stopped \
  --env-file "$APP/runtime.env" \
  -p 127.0.0.1:8080:8080 \
  --log-driver awslogs \
  --log-opt awslogs-region=us-east-1 \
  --log-opt awslogs-group=/motorinn/ai-markdown-proxy \
  --log-opt awslogs-create-group=false \
  "ai-markdown-proxy:$RELEASE_SHA"
for attempt in {1..20}; do
  curl -fsS http://127.0.0.1:8080/__health && break
  sleep 1
done
curl -fsS --retry 5 --retry-delay 1 --retry-connrefused \
  http://127.0.0.1:8080/__health/full
curl -fsS -H 'Host: ai.motorinnofcarroll.com' \
  http://127.0.0.1:8080/agent-connection.md >/dev/null
```

Wait for the SSM command to finish and inspect its status and output. Confirm
`__health/full` succeeds and `/agent-connection.md` returns successfully through
the local app listener. Do not display environment values or unrelated logs.
The procedure leaves Caddy, IAM, instance profiles, security groups, public
ports, Elastic IP, DNS, and CloudWatch configuration untouched.

## Rollback

If either health check fails, use the same SSM target and restore the tagged
pre-release image. Keep the existing runtime environment file and Caddy
container unchanged:

```bash
set -euo pipefail
ROLLBACK_TAG='ai-markdown-proxy:rollback-<previous-application-sha>'
docker image inspect "$ROLLBACK_TAG" >/dev/null
docker stop ai-markdown-proxy 2>/dev/null || true
docker rm ai-markdown-proxy 2>/dev/null || true
docker run -d --name ai-markdown-proxy --restart unless-stopped \
  --env-file /opt/ai-markdown-proxy/runtime.env \
  -p 127.0.0.1:8080:8080 \
  --log-driver awslogs \
  --log-opt awslogs-region=us-east-1 \
  --log-opt awslogs-group=/motorinn/ai-markdown-proxy \
  --log-opt awslogs-create-group=false \
  "$ROLLBACK_TAG"
curl -fsS --retry 5 --retry-delay 1 --retry-connrefused \
  http://127.0.0.1:8080/__health/full
```

Record the failed release SHA, SSM command ID, health-check result, restored
image ID, and rollback health result. Do not delete the rollback image until a
subsequent release has passed acceptance.

## Review status and limitations

The procedure is based on the existing host path, container name, loopback
binding, runtime-env path, log group, and health routes in `deploy.sh` and
`README.md`. The application-only flow has not been tested on the production
host; current SSM reachability and permissions, image availability, and host
Git/Docker behavior remain unverified. The runtime parameter is not accessed by
this procedure.
