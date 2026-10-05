FROM --platform=$BUILDPLATFORM golang:1.26-alpine3.24@sha256:8ac98ca534ac3f51e1f420a1dd2c15e74c75cfa0f23f3ad27eb5d7236c349a0c AS build

ARG TARGETOS
ARG TARGETARCH
WORKDIR /src/smtprelay

RUN apk add --no-cache git

COPY go.mod go.sum /src/smtprelay/

RUN go mod download

COPY *.go /src/smtprelay/

COPY smtpd/*.go /src/smtprelay/smtpd/

RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build smtprelay

# Run explicitly with --target test; retain upstream assertions for the local fork.
FROM build AS test
RUN go test -v -timeout 3m ./...

FROM alpine:3.24@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6

RUN apk add --no-cache ca-certificates tzdata

COPY --from=build /src/smtprelay/smtprelay /usr/bin

ENV TZ=America/Los_Angeles

RUN cp /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

EXPOSE 587 2525 8025

VOLUME /cert

ENV edcomhost=api:8000

ENTRYPOINT ["/usr/bin/smtprelay"]