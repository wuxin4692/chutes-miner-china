# Base layer.
FROM python:3.12 as base
RUN apt update && apt -y install net-tools procps vim jq bc curl
RUN useradd chutes -s /bin/bash -d /home/chutes && mkdir -p /home/chutes && chown chutes:chutes /home/chutes
RUN mkdir -p /app && chown chutes:chutes /app
USER chutes
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH=$PATH:/home/chutes/.local/bin

# Miner/API
FROM base AS api
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && mv kubectl /usr/local/bin/ && chmod 755 /usr/local/bin/kubectl
RUN curl -fsSL -o /usr/local/bin/dbmate https://github.com/amacneil/dbmate/releases/latest/download/dbmate-linux-amd64 && chmod +x /usr/local/bin/dbmate
ADD --chown=chutes pyproject.toml poetry.lock /app/
ADD --chown=chutes api /app/api
WORKDIR /app
RUN poetry install
ENV PYTHONPATH=/app
ENTRYPOINT ["poetry", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# Porter.
FROM base AS porter
ADD --chown=chutes porter /app
WORKDIR /app
RUN poetry install
ENV PYTHONPATH=/app
ENTRYPOINT ["poetry", "run", "python", "porter.py", "--real-host", "$REAL_AXON_HOST", "--real-port", "$REAL_AXON_PORT", "--validator-whitelist", "$VALIDATOR_WHITELIST", "--hotkey", "$MINER_HOTKEY_SS58"]

# GraVal bootstrap.
FROM base AS bootstrap
ADD --chown=chutes porter /app
WORKDIR /app
RUN poetry install
ENV PYTHONPATH=/app
ENTRYPOINT ["poetry", "run", "python", "bootstrap.py", "--validator-whitelist", "$VALIDATOR_WHITELIST", "--hotkey", "$MINER_HOTKEY_SS58"]
