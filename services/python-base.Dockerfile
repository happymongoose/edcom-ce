FROM python:3.11-alpine3.24@sha256:cd04730b8511def3fbf14204d66a0c1536f290b8e896ed5a94cd64cb15ac1356

WORKDIR /

RUN apk add --no-cache postgresql-dev libffi-dev libxslt-dev logrotate gcc libc-dev

COPY config/pip.requirements /

RUN pip install --upgrade pip && pip install -r /pip.requirements && pip install gunicorn watchdog && pip check

# Keep packaging helpers patched independently of application dependency pins.
RUN pip install --upgrade setuptools==84.0.0 wheel==0.46.3 && pip check
