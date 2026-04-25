#!/bin/bash

# Usage: ./deploy.sh [instance_number]
# Example: ./deploy.sh 2

INSTANCE=${1:-2}

echo "🚀 Starting deployment to instance ${INSTANCE}..."

# Build and restart specific instance
docker compose -p smdg-scale -f docker-compose.scale.yml up -d --no-deps --build smdg

echo "⏳ Waiting for instance to be healthy..."
sleep 10

# Check health
if docker inspect smdg-scale-smdg-${INSTANCE} --format='{{.State.Health.Status}}' | grep -q healthy; then
    echo "✅ Instance ${INSTANCE} is healthy"
    
    # Switch traffic to this instance
    ./scripts/cutover.sh green ${INSTANCE}
    
    echo "✅ Deployment complete! Traffic now on instance ${INSTANCE}"
else
    echo "❌ Instance ${INSTANCE} is not healthy. Aborting."
    exit 1
fi
