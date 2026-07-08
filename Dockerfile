FROM python:3.11-slim

# System deps: git (semgrep/gitleaks scan file trees), curl (fetch gitleaks binary)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Gitleaks ships as a standalone binary, not a pip package.
RUN curl -sSL https://github.com/gitleaks/gitleaks/releases/download/v8.18.4/gitleaks_8.18.4_linux_x64.tar.gz \
    | tar -xz -C /usr/local/bin gitleaks

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user for defense-in-depth (the container runs semgrep/bandit over
# untrusted PR content, so least-privilege matters here more than usual).
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "app.core.webhook:app", "--host", "0.0.0.0", "--port", "8000"]
