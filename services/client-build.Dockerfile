FROM node-base:latest

VOLUME /client/public
VOLUME /client/src
VOLUME /client/build

# Webpack 3 in react-scripts 1 requires the legacy provider on Node 19.
# Build container only; the production frontend is served by nginx.
ENV NODE_OPTIONS=--openssl-legacy-provider

CMD npm run build
