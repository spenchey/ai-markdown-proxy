#!/bin/bash
# Deploy AI Markdown Proxy to AWS EC2
# Prerequisites: AWS CLI configured, SSH key pair available
# Usage: ./deploy.sh [instance-type] [region]

set -e

INSTANCE_TYPE="${1:-t3.nano}"
REGION="${2:-us-east-1}"
KEY_NAME="ai-proxy-key"
SEC_GROUP="ai-markdown-proxy-sg"

echo "=== AI Markdown Proxy - AWS Deployment ==="
echo "Instance type: $INSTANCE_TYPE"
echo "Region: $REGION"
echo ""

# Create security group
echo "Creating security group..."
SG_ID=$(aws ec2 create-security-group \
    --group-name "$SEC_GROUP" \
    --description "Security group for AI Markdown Proxy" \
    --region "$REGION" \
    --query 'GroupId' --output text 2>/dev/null || true)

if [ -z "$SG_ID" ]; then
    SG_ID=$(aws ec2 describe-security-groups \
        --group-names "$SEC_GROUP" \
        --region "$REGION" \
        --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null)
fi

echo "Security group ID: $SG_ID"

# Authorize ports 22 (SSH) and 80 (HTTP)
aws ec2 authorize-security-group-ingress \
    --group-id "$SG_ID" \
    --protocol tcp --port 22 --cidr 0.0.0.0/0 \
    --region "$REGION" 2>/dev/null || true

aws ec2 authorize-security-group-ingress \
    --group-id "$SG_ID" \
    --protocol tcp --port 80 --cidr 0.0.0.0/0 \
    --region "$REGION" 2>/dev/null || true

# Create key pair if it doesn't exist
KEY_FILE="${KEY_NAME}.pem"
if ! aws ec2 describe-key-pairs --key-names "$KEY_NAME" --region "$REGION" 2>/dev/null; then
    echo "Creating key pair $KEY_NAME..."
    aws ec2 create-key-pair \
        --key-name "$KEY_NAME" \
        --query 'KeyMaterial' \
        --output text \
        --region "$REGION" > "$KEY_FILE"
    chmod 400 "$KEY_FILE"
    echo "Key saved to $KEY_FILE"
fi

# Get latest Amazon Linux 2023 AMI
AMI_ID=$(aws ssm get-parameters \
    --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
    --region "$REGION" \
    --query 'Parameters[0].Value' --output text)

echo "Using AMI: $AMI_ID"

# Launch EC2 instance
echo "Launching EC2 instance..."
INSTANCE_ID=$(aws ec2 run-instances \
    --image-id "$AMI_ID" \
    --count 1 \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SG_ID" \
    --user-data file://user-data.sh \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=ai-markdown-proxy}]" \
    --region "$REGION" \
    --query 'Instances[0].InstanceId' --output text)

echo "Instance ID: $INSTANCE_ID"
echo "Waiting for instance to be running..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGION"

# Get public IP
PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)

echo ""
echo "=== Deployment Complete ==="
echo "Instance ID: $INSTANCE_ID"
echo "Public IP: $PUBLIC_IP"
echo "URL: http://$PUBLIC_IP"
echo ""
echo "SSH: ssh -i $KEY_FILE ec2-user@$PUBLIC_IP"
echo ""
echo "To check status:"
echo "  curl http://$PUBLIC_IP/__health"
