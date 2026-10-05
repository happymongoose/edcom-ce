FROM nginx:stable-alpine@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94

RUN apk upgrade --no-cache

COPY config/nginx.conf /etc/nginx/nginx.conf
COPY config/nginx.ssl.conf /etc/nginx/nginx.ssl.conf
COPY client/build/ /usr/share/nginx/html/

CMD sh -c 'if [[ -e /config/use_ssl ]] && grep -q "1" /config/use_ssl; then nginx -g "daemon off;" -c /etc/nginx/nginx.ssl.conf; else nginx -g "daemon off;" -c /etc/nginx/nginx.conf; fi'
