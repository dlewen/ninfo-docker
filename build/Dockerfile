FROM python:3-alpine AS builder

ARG CUSTOM_GIT_REPOS
ENV CUSTOM_GIT_REPOS $CUSTOM_GIT_REPOS

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apk add --no-cache \
    git \
    gcc \
    python3-dev \
    musl-dev \
    libffi-dev

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt

COPY local_plugins /plugins
RUN git clone https://github.com/ninfo-py/ninfo.git ninfo && \
    git clone https://github.com/dlewen/django-ninfo.git django-ninfo

ARG CUSTOM_GIT_REPOS
ENV CUSTOM_GIT_REPOS $CUSTOM_GIT_REPOS
RUN if [ -n "$CUSTOM_GIT_REPOS" ]; then \
    echo "$CUSTOM_GIT_REPOS" | tr ',' '\n' | while read repo; do \
    if [ -n "$repo" ]; then \
    git clone "$repo" "$(basename $repo .git)"; \
    fi; \
    done; \
    fi

RUN for dir in ninfo django-ninfo $(find . -maxdepth 1 -type d -not -path "./ninfo" -not -path "./django-ninfo" -not -path "." -not -path ".." | grep -v "\.git$") ; do \
    if [ -f "$dir/setup.py" ]; then \
    cd "$dir" && pip wheel --no-cache-dir --wheel-dir /app/wheels . && cd ..; \
    fi; \
    done; \
    cd /plugins; \
    for dir in $(find /plugins -maxdepth 1 -type d -not -path "." -not -path ".." | grep -v "\.git$"); do \
    if [ -f "$dir/setup.py" ]; then \
    cd "$dir" && pip wheel --no-cache-dir --wheel-dir /app/wheels . && cd ..; \
    fi; \
    done;



# Stage 2

FROM python:3-alpine

RUN apk add --no-cache jq shadow tzdata && \
    rm -rf /var/cache/apk/*

# Create a non-root user to run the application
RUN addgroup -S -g 30002 ninfo && \
    adduser -S -G ninfo -u 30002 ninfo

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/ninfo/.local/bin:$PATH"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /app

COPY --chown=ninfo:ninfo app .
COPY --from=builder --chown=ninfo:ninfo /app/wheels /wheels
COPY --from=builder /app/requirements.txt ./
RUN chown -R ninfo:ninfo /app /wheels

USER ninfo
RUN pip install --no-cache-dir --user --upgrade pip && \
    for wheel in /wheels/*.whl; do \
    if pip install --no-cache-dir --user --no-deps --find-links=/wheels/ "$wheel" 2>/dev/null; then \
    echo "Successfully installed $wheel"; \
    else \
    echo "Skipping incompatible wheel: $wheel"; \
    fi; \
    done

USER root
RUN rm -rf /wheels

USER ninfo

RUN python manage.py collectstatic --noinput

ENTRYPOINT [ "/entrypoint.sh" ]

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "ninfo_www.wsgi:application"]
