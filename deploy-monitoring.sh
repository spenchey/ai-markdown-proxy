#!/usr/bin/env bash
# Deploy the serverless public health monitor and two-failure Slack alert.

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
FUNCTION_NAME="${AI_PROXY_MONITOR_FUNCTION:-motorinn-ai-markdown-proxy-monitor}"
ROLE_NAME="${AI_PROXY_MONITOR_ROLE:-motorinn-ai-markdown-proxy-monitor-role}"
RULE_NAME="${AI_PROXY_MONITOR_RULE:-motorinn-ai-markdown-proxy-every-15-minutes}"
SECRET_ID="${AI_PROXY_SLACK_SECRET_ID:-motorinn/ai-markdown-proxy/slack-bot-token}"
STATE_PARAMETER="${AI_PROXY_STATE_PARAMETER:-/motorinn/ai-markdown-proxy/health-state}"
SLACK_CHANNEL_ID="${AI_PROXY_SLACK_CHANNEL_ID:-C0AC3BP5XPF}"
RULE_STATE="${AI_PROXY_MONITOR_RULE_STATE:-ENABLED}"
INVOKE_AFTER_DEPLOY="${AI_PROXY_MONITOR_INVOKE_AFTER_DEPLOY:-true}"

if [[ "$RULE_STATE" != "ENABLED" && "$RULE_STATE" != "DISABLED" ]]; then
  echo "AI_PROXY_MONITOR_RULE_STATE must be ENABLED or DISABLED" >&2
  exit 64
fi
if [[ "$INVOKE_AFTER_DEPLOY" != "true" && "$INVOKE_AFTER_DEPLOY" != "false" ]]; then
  echo "AI_PROXY_MONITOR_INVOKE_AFTER_DEPLOY must be true or false" >&2
  exit 64
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

cat >"$tmp_dir/trust.json" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
JSON

cat >"$tmp_dir/policy.json" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:${REGION}:${ACCOUNT_ID}:*"
    },
    {
      "Effect": "Allow",
      "Action": "cloudwatch:PutMetricData",
      "Resource": "*",
      "Condition": {"StringEquals": {"cloudwatch:namespace": "MotorInn/AIReadableMirror"}}
    },
    {
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:PutParameter"],
      "Resource": "arn:aws:ssm:${REGION}:${ACCOUNT_ID}:parameter${STATE_PARAMETER}"
    },
    {
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:${SECRET_ID}-*"
    }
  ]
}
JSON

if ! aws secretsmanager describe-secret --region "$REGION" --secret-id "$SECRET_ID" >/dev/null 2>&1; then
  echo "Missing Secrets Manager secret: $SECRET_ID" >&2
  echo "Stage the existing Jeeves Slack bot token there before deploying monitoring." >&2
  exit 2
fi

if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "file://$tmp_dir/trust.json" >/dev/null
fi
aws iam update-assume-role-policy --role-name "$ROLE_NAME" --policy-document "file://$tmp_dir/trust.json"
aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name MotorInnAiProxyMonitor --policy-document "file://$tmp_dir/policy.json"

cp infra/health_monitor.py "$tmp_dir/health_monitor.py"
(cd "$tmp_dir" && zip -q function.zip health_monitor.py)

role_arn="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
if aws lambda get-function --region "$REGION" --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  aws lambda update-function-code --region "$REGION" --function-name "$FUNCTION_NAME" --zip-file "fileb://$tmp_dir/function.zip" >/dev/null
  aws lambda wait function-updated --region "$REGION" --function-name "$FUNCTION_NAME"
  aws lambda update-function-configuration \
    --region "$REGION" --function-name "$FUNCTION_NAME" --runtime python3.12 \
    --handler health_monitor.lambda_handler --timeout 45 --memory-size 256 \
    --environment "Variables={SLACK_SECRET_ID=$SECRET_ID,SLACK_CHANNEL_ID=$SLACK_CHANNEL_ID,STATE_PARAMETER=$STATE_PARAMETER}" >/dev/null
else
  sleep 10
  aws lambda create-function \
    --region "$REGION" --function-name "$FUNCTION_NAME" --runtime python3.12 \
    --role "$role_arn" --handler health_monitor.lambda_handler --timeout 45 --memory-size 256 \
    --zip-file "fileb://$tmp_dir/function.zip" \
    --environment "Variables={SLACK_SECRET_ID=$SECRET_ID,SLACK_CHANNEL_ID=$SLACK_CHANNEL_ID,STATE_PARAMETER=$STATE_PARAMETER}" >/dev/null
fi
aws lambda wait function-active-v2 --region "$REGION" --function-name "$FUNCTION_NAME"

aws events put-rule --region "$REGION" --name "$RULE_NAME" --schedule-expression 'rate(15 minutes)' --state "$RULE_STATE" >/dev/null
function_arn="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"
aws events put-targets --region "$REGION" --rule "$RULE_NAME" --targets "Id=monitor,Arn=$function_arn" >/dev/null
aws lambda add-permission --region "$REGION" --function-name "$FUNCTION_NAME" \
  --statement-id AllowEventBridgeSchedule --action lambda:InvokeFunction --principal events.amazonaws.com \
  --source-arn "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/${RULE_NAME}" >/dev/null 2>&1 || true

aws cloudwatch put-metric-alarm --region "$REGION" \
  --alarm-name motorinn-ai-markdown-proxy-monitor-errors \
  --namespace AWS/Lambda --metric-name Errors --dimensions "Name=FunctionName,Value=$FUNCTION_NAME" \
  --statistic Sum --period 900 --evaluation-periods 2 --datapoints-to-alarm 2 \
  --threshold 0 --comparison-operator GreaterThanThreshold --treat-missing-data notBreaching

aws logs create-log-group --region "$REGION" --log-group-name "/aws/lambda/$FUNCTION_NAME" 2>/dev/null || true
aws logs put-retention-policy --region "$REGION" --log-group-name "/aws/lambda/$FUNCTION_NAME" --retention-in-days 30

if [[ "$INVOKE_AFTER_DEPLOY" == "true" ]]; then
  aws lambda invoke --region "$REGION" --function-name "$FUNCTION_NAME" "$tmp_dir/invoke.json" >/dev/null
  cat "$tmp_dir/invoke.json"
else
  printf '{"status":"staged","function":"%s","ruleState":"%s","invoked":false}\n' "$FUNCTION_NAME" "$RULE_STATE"
fi
