FROM python:3.12-slim

ARG NODE_MAJOR=22

ENV DEBIAN_FRONTEND=noninteractive
ENV BULLPEN_PRODUCTION=1
ENV BULLPEN_PORT=8080
ENV APP_PORT=3000
ENV BULLPEN_WORKSPACE=/workspace
ENV BULLPEN_HOST=0.0.0.0

WORKDIR /opt/bullpen

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl git ripgrep gnupg && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | \
      gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
      > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && apt-get install -y --no-install-recommends nodejs && \
    npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x deploy/docker/entrypoint.sh && mkdir -p /workspace

EXPOSE 8080 3000

ENTRYPOINT ["./deploy/docker/entrypoint.sh"]
