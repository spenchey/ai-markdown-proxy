#!/bin/bash
# Deploy AI Markdown Proxy to AWS EC2
# Prerequisites: AWS CLI configured, SSH key pair available
# Usage: ./deploy.sh [key-pair-name] [instance-type] [region]

set -e

KEY_NAME="${1:-ai-proxy-key}"
INSTANCE_TYPE="${2:-t3.nano}"
REGION="${3:-us-east-1}"
AMI_ID="ami-0c55b159cbfafe1d0"  # Amazon Linux 2 AMI

echo "=== AI Markdown Proxy - AWS Deployment ==="
echo "Key pair: $KEY_NAME"
echo "Instance type: $INSTANCE_TYPE"
echo "Region: $REGION"
echo ""

# Create security group
echo "Creating security group..."
SG_ID=$(aws ec2 create-security-group \
    --group-name ai-markdown-proxy-sg \
    --description "Security group for AI Markdown Proxy" \
    --region "$REGION" \
    --query 'GroupId' --output text 2>/dev/null || true)

if [ -z "$SG_ID" ]; then
    # Group already exists, get its ID
    SG_ID=$(aws ec2 describe-security-groups \
        --group-names ai-markdown-proxy-sg \
        --region "$REGION" \
        --query 'SecurityGroups[0].GroupId' --output text)
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
echo "DNS: ai-markdown-proxy.$REGION.compute.amazonaws.com (if using elastic IP)"
echo ""
echo "To check status:"
echo "  curl http://$PUBLIC_IP/__health"
echo ""
echo "To view logs:"
echo "  ssh -i $KEY_FILE ec2-user@$PUBLIC_IP 'docker logs ai-markdown-proxy'"
