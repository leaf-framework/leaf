FROM python:3.12

WORKDIR /app

# Copy the start script to the container
ADD start.sh /app/start.sh

RUN pip install --upgrade pip && \
    pip install git+https://gitlab.com/LabEquipmentAdapterFramework/leaf.git

# Start the application
ENTRYPOINT ["bash", "/app/start.sh"]