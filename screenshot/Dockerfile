FROM alpine:3.24@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6

RUN apk add --no-cache chromium nss freetype harfbuzz ca-certificates font-freefont font-noto-emoji nodejs npm \
    && adduser -D -u 1000 chrome
ENV HOME=/home/chrome
WORKDIR /src/screenshot
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY index.js browser-ready.js ./
EXPOSE 4000
USER chrome
CMD ["node", "index.js"]
