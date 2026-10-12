ARG GO_IMAGE=golang:1.25-alpine
# Keep SQLite compatible with older Docker seccomp profiles (pwritev2 fallback).
ARG PYTHON_IMAGE=python:3.13-alpine3.21
ARG NODE_IMAGE=node:22-alpine
FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS frontend
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM --platform=$BUILDPLATFORM ${GO_IMAGE} AS agents
WORKDIR /src
COPY agent/ ./
RUN go test ./... && go vet ./...
RUN mkdir /out && for target in linux/amd64 linux/arm64 darwin/amd64 darwin/arm64 windows/amd64 windows/arm64; do \
    os=${target%/*}; arch=${target#*/}; suffix=""; if [ "$os" = windows ]; then suffix=.exe; fi; \
    CGO_ENABLED=0 GOOS=$os GOARCH=$arch go build -trimpath -ldflags="-s -w" -o /out/proxylens-agent-$os-$arch$suffix . || exit 1; \
    done

FROM ${PYTHON_IMAGE} AS server
WORKDIR /app
RUN addgroup -S proxylens && adduser -S -G proxylens proxylens && mkdir /data && chown proxylens:proxylens /data
COPY --chown=proxylens:proxylens server/*.py /app/
COPY --from=frontend --chown=proxylens:proxylens /web/dist/ /app/web/
COPY --from=agents /out/ /app/downloads/
USER proxylens
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data PORT=8080
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"
CMD ["python", "app.py"]
