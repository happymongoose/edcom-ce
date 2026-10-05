# Rebuild the inherited gosu helper: upstream 1.19 binaries embed Go 1.24.6.
FROM --platform=$BUILDPLATFORM golang:1.26-alpine3.24@sha256:8ac98ca534ac3f51e1f420a1dd2c15e74c75cfa0f23f3ad27eb5d7236c349a0c AS gosu-build
RUN apk add --no-cache git
ARG TARGETOS
ARG TARGETARCH
WORKDIR /src/gosu-build
RUN go mod init edcom-gosu-build \
    && go get github.com/tianon/gosu@v0.0.0-20250923190938-6456aaa0f3c8 golang.org/x/sys@v0.44.0 \
    && CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /go/bin/gosu github.com/tianon/gosu

FROM postgres:15-alpine3.24@sha256:f7d23353e1b15400d22ebe31189f4d314b87a4c129cc400c8c2d8d4ca127bf81

RUN apk upgrade --no-cache && apk --no-cache add pgbouncer
COPY --from=gosu-build /go/bin/gosu /usr/local/bin/gosu
RUN gosu --version && gosu nobody id

COPY ./config/pgbouncer.ini /etc/pgbouncer/pgbouncer.ini

ENV POSTGRES_USER edcom
ENV POSTGRES_PASSWORD edcom
ENV POSTGRES_DB edcom
VOLUME /docker-entrypoint-initdb.d

CMD su postgres -c 'pgbouncer -d /etc/pgbouncer/pgbouncer.ini' ; docker-entrypoint.sh postgres -c max_connections=1024 -c logging_collector=on -c log_destination=stderr -c log_directory=/logs/postgres -c log_rotation_age=7d