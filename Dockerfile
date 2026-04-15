FROM python:3.12-slim

ARG NODE_MAJOR=22
ARG BULLPEN_UID=1000
ARG BULLPEN_GID=1000

ENV DEBIAN_FRONTEND=noninteractive
ENV BULLPEN_PRODUCTION=0
ENV BULLPEN_PORT=8080
ENV APP_PORT=3000
ENV BULLPEN_WORKSPACE=/workspace
ENV BULLPEN_HOST=0.0.0.0
ENV BULLPEN_CODEX_SANDBOX=none
ENV HOME=/home/bullpen

WORKDIR /opt/bullpen

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl gh git openssh-client ripgrep gnupg && \
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

RUN if getent group "${BULLPEN_GID}" >/dev/null; then \
      BULLPEN_GROUP="$(getent group "${BULLPEN_GID}" | cut -d: -f1)"; \
    else \
      groupadd --gid "${BULLPEN_GID}" bullpen; \
      BULLPEN_GROUP="bullpen"; \
    fi && \
    useradd --uid "${BULLPEN_UID}" --gid "${BULLPEN_GROUP}" --create-home --shell /bin/bash bullpen && \
    chmod +x deploy/docker/entrypoint.sh && \
    mkdir -p /workspace && \
    chown -R bullpen:"${BULLPEN_GROUP}" /opt/bullpen /workspace /home/bullpen

EXPOSE 8080 3000

USER bullpen

ENTRYPOINT ["./deploy/docker/entrypoint.sh"]
