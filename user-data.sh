#!/bin/bash
# user-data.sh — runs on EC2 first boot
# Installs Docker, clones the GitHub repo, builds and runs the container
yum update -y
yum install -y docker git
service docker start
usermod -a -G docker ec2-user

# Clone the repo
cd /opt
git clone https://github.com/spenchey/ai-markdown-proxy.git
cd ai-markdown-proxy

# Build and run the Docker container
docker build -t ai-markdown-proxy .
docker run -d \
    --name ai-markdown-proxy \
    --restart unless-stopped \
    -p 80:8080 \
    ai-markdown-proxy

# Enable Docker on boot
systemctl enable docker
