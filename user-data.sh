#!/bin/bash
# user-data.sh — runs on EC2 first boot via install docker, build image, and run it
# This script is embedded in the EC2 user-data and runs as root

# Install Docker
yum update -y
yum install -y docker
service docker start
usermod -a -G docker ec2-user

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Create app directory
mkdir -p /opt/ai-markdown-proxy
cd /opt/ai-markdown-proxy

# Copy app files from S3 (or create them inline)
cat > server.py << 'PYTHON_EOF'
__placeholder__  
PYTHON_EOF

# We'll copy the files from the local build context instead
# For now, copy from a git repo or S3

# Pull and run the Docker image
docker build -t ai-markdown-proxy https://github.com/spencerheywood/ai-markdown-proxy.git || {
    echo "FALLBACK: Building from local files"
    # If git repo not available, copy files manually
}

# Run the container on port 80
docker run -d \
    --name ai-markdown-proxy \
    --restart unless-stopped \
    -p 80:8080 \
    ai-markdown-proxy

# Enable on boot
chkconfig docker on
