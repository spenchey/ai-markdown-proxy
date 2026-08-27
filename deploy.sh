#!/usr/bin/env bash
# Create or update the production AI-readable mirror on AWS.

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
INSTANCE_ID="${AI_PROXY_INSTANCE_ID:-i-0cf5041ecb2a0045b}"
ROLE_NAME="${AI_PROXY_ROLE_NAME:-motorinn-ai-markdown-proxy-role}"
PROFILE_NAME="${AI_PROXY_PROFILE_NAME:-motorinn-ai-markdown-proxy-profile}"
LOG_GROUP="${AI_PROXY_LOG_GROUP:-/motorinn/ai-markdown-proxy}"
CADDY_LOG_GROUP="${AI_PROXY_CADDY_LOG_GROUP:-/motorinn/ai-markdown-proxy/caddy}"
REPOSITORY="${AI_PROXY_REPOSITORY:-https://github.com/spenchey/ai-markdown-proxy.git}"
RUNTIME_ENV_PARAMETER="/motorinn/ai-markdown-proxy/runtime-env"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

cat >"$tmp_dir/trust.json" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "ec2.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
JSON

cat >"$tmp_dir/inventory-read.json" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadPublishedDealerVaultInventory",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::motorinn-dealervault-raw/normalized/current_inventory_market/latest/current-inventory-market.json"
    },
    {
      "Sid": "ReadAgentAccessRuntimeConfiguration",
      "Effect": "Allow",
      "Action": ["ssm:GetParameter"],
      "Resource": "arn:aws:ssm:*:*:parameter/motorinn/ai-markdown-proxy/*"
    }
  ]
}
JSON

if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "file://$tmp_dir/trust.json" >/dev/null
fi
aws iam update-assume-role-policy --role-name "$ROLE_NAME" --policy-document "file://$tmp_dir/trust.json"
aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name ReadMotorInnPublishedInventory --policy-document "file://$tmp_dir/inventory-read.json"
aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy

if ! aws iam get-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null
fi
if ! aws iam get-instance-profile --instance-profile-name "$PROFILE_NAME" --query "InstanceProfile.Roles[?RoleName=='$ROLE_NAME']" --output text | grep -q "$ROLE_NAME"; then
  aws iam add-role-to-instance-profile --instance-profile-name "$PROFILE_NAME" --role-name "$ROLE_NAME"
fi

association_id="$(aws ec2 describe-iam-instance-profile-associations --region "$REGION" --filters Name=instance-id,Values="$INSTANCE_ID" --query 'IamInstanceProfileAssociations[?State!=`disassociated`].AssociationId|[0]' --output text)"
if [[ -z "$association_id" || "$association_id" == "None" ]]; then
  sleep 10
  aws ec2 associate-iam-instance-profile --region "$REGION" --instance-id "$INSTANCE_ID" --iam-instance-profile Name="$PROFILE_NAME" >/dev/null
fi

aws logs create-log-group --region "$REGION" --log-group-name "$LOG_GROUP" 2>/dev/null || true
aws logs put-retention-policy --region "$REGION" --log-group-name "$LOG_GROUP" --retention-in-days 30
aws logs create-log-group --region "$REGION" --log-group-name "$CADDY_LOG_GROUP" 2>/dev/null || true
aws logs put-retention-policy --region "$REGION" --log-group-name "$CADDY_LOG_GROUP" --retention-in-days 30

for attempt in {1..18}; do
  ping_status="$(aws ssm describe-instance-information --region "$REGION" --filters Key=InstanceIds,Values="$INSTANCE_ID" --query 'InstanceInformationList[0].PingStatus' --output text)"
  [[ "$ping_status" == "Online" ]] && break
  sleep 10
done
if [[ "${ping_status:-}" != "Online" ]]; then
  echo "SSM did not become online for $INSTANCE_ID" >&2
  exit 2
fi

command_id="$(aws ssm send-command \
  --region "$REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --comment "Deploy Motor Inn AI-readable mirror" \
  --parameters commands="[
    \"set -euo pipefail\",
    \"if [ ! -d /opt/ai-markdown-proxy/.git ]; then git clone $REPOSITORY /opt/ai-markdown-proxy; fi\",
    \"git -C /opt/ai-markdown-proxy fetch origin main\",
    \"git -C /opt/ai-markdown-proxy reset --hard origin/main\",
    \"docker build --pull -t ai-markdown-proxy:production /opt/ai-markdown-proxy\",
    \"install -m 600 /dev/null /opt/ai-markdown-proxy/runtime.env\",
    \"aws ssm get-parameter --region $REGION --name $RUNTIME_ENV_PARAMETER --with-decryption --query Parameter.Value --output text > /opt/ai-markdown-proxy/runtime.env\",
    \"chmod 600 /opt/ai-markdown-proxy/runtime.env\",
    \"docker stop ai-markdown-proxy caddy 2>/dev/null || true\",
    \"docker rm ai-markdown-proxy caddy 2>/dev/null || true\",
    \"docker pull caddy:2.10-alpine\",
    \"mkdir -p /opt/caddy-data /opt/caddy-config\",
    \"docker run -d --name ai-markdown-proxy --restart unless-stopped --env-file /opt/ai-markdown-proxy/runtime.env -p 127.0.0.1:8080:8080 --log-driver awslogs --log-opt awslogs-region=$REGION --log-opt awslogs-group=$LOG_GROUP --log-opt awslogs-create-group=false ai-markdown-proxy:production\",
    \"docker run -d --name caddy --restart unless-stopped --network host -v /opt/ai-markdown-proxy/Caddyfile:/etc/caddy/Caddyfile:ro -v /opt/caddy-data:/data -v /opt/caddy-config:/config --log-driver awslogs --log-opt awslogs-region=$REGION --log-opt awslogs-group=$CADDY_LOG_GROUP --log-opt awslogs-create-group=false caddy:2.10-alpine\",
    \"for attempt in {1..20}; do curl -fsS http://127.0.0.1:8080/__health && break; sleep 1; done\",
    \"curl -fsS --retry 5 --retry-delay 1 --retry-connrefused http://127.0.0.1:8080/__health/full\"
  ]" \
  --query 'Command.CommandId' --output text)"

aws ssm wait command-executed --region "$REGION" --command-id "$command_id" --instance-id "$INSTANCE_ID"
aws ssm get-command-invocation --region "$REGION" --command-id "$command_id" --instance-id "$INSTANCE_ID" --output json

sg_id="$(aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text)"
aws ec2 revoke-security-group-ingress --region "$REGION" --group-id "$sg_id" --protocol tcp --port 22 --cidr 0.0.0.0/0 2>/dev/null || true
aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$sg_id" --protocol tcp --port 80 --cidr 0.0.0.0/0 2>/dev/null || true
aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$sg_id" --protocol tcp --port 443 --cidr 0.0.0.0/0 2>/dev/null || true

allocation_id="$(aws ec2 describe-addresses --region "$REGION" --filters Name=tag:Name,Values=ai-markdown-proxy --query 'Addresses[0].AllocationId' --output text)"
if [[ -z "$allocation_id" || "$allocation_id" == "None" ]]; then
  read -r allocation_id public_ip < <(aws ec2 allocate-address --region "$REGION" --domain vpc --tag-specifications 'ResourceType=elastic-ip,Tags=[{Key=Name,Value=ai-markdown-proxy}]' --query '[AllocationId,PublicIp]' --output text)
else
  public_ip="$(aws ec2 describe-addresses --region "$REGION" --allocation-ids "$allocation_id" --query 'Addresses[0].PublicIp' --output text)"
fi
current_instance="$(aws ec2 describe-addresses --region "$REGION" --allocation-ids "$allocation_id" --query 'Addresses[0].InstanceId' --output text)"
if [[ "$current_instance" != "$INSTANCE_ID" ]]; then
  aws ec2 associate-address --region "$REGION" --instance-id "$INSTANCE_ID" --allocation-id "$allocation_id" --allow-reassociation >/dev/null
fi

printf '{"status":"ok","instanceId":"%s","elasticIp":"%s","logGroup":"%s","caddyLogGroup":"%s"}\n' "$INSTANCE_ID" "$public_ip" "$LOG_GROUP" "$CADDY_LOG_GROUP"
