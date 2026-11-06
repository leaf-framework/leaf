#!/bin/bash

# Define variables
IMAGE_NAME="harbor.containers.wurnet.nl/leaf-framework/leaf:dev"
PLATFORMS="linux/amd64,linux/arm64"

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if buildx is available
if ! docker buildx version &> /dev/null; then
    echo "Docker buildx is not available. Ensure you have Docker version 19.03+ and buildx enabled."
    exit 1
fi

# Create and use a new buildx builder if not already set up
if ! docker buildx inspect multiarch-builder &> /dev/null; then
    echo "Creating a new buildx builder..."
    docker buildx create --name multiarch-builder --use
fi

# Inspect the builder to ensure it supports arm64
if ! docker buildx inspect --bootstrap | grep -q "linux/arm64"; then
    echo "Your system may not support linux/arm64 builds. Trying anyway..."
fi

# Log in to Docker registry
echo "Logging in to Docker registry..."
docker login harbor.containers.wurnet.nl

# Build and push for both amd64 and arm64
echo "Building and pushing image for platforms: $PLATFORMS"
docker buildx build --no-cache --platform $PLATFORMS -t $IMAGE_NAME --push .

echo "Build and push completed successfully!"
