FROM debian:12 AS build

# Run in single layer to keep size down
RUN apt-get update && apt-get upgrade -y &&\
    DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates python3-full python3-pip tzdata && \
    python3 -m venv /venv && \
    /venv/bin/pip install --upgrade pip

# Build the virtualenv as a separate step: Only re-execute this step when requirements.txt changes
FROM build AS build-venv
COPY requirements.txt /requirements.txt
RUN /venv/bin/pip install --disable-pip-version-check -r /requirements.txt

FROM debian:12

# ARGS invalidates cache, if any
ARG TITLE
ARG VCS_URL
ARG VCS_REF
ARG BUILD_DATE
ARG VERSION

LABEL org.opencontainers.image.authors="emil@jacero.se"
LABEL org.opencontainers.image.title="${TITLE}"
LABEL org.opencontainers.image.source="${VCS_URL}"
LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.version="${VERSION}"

RUN apt-get update && apt-get upgrade -y &&\
    DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates python3-full python3-pip tzdata ffmpeg imagemagick
## Modify the ImageMagic policy.xml to allow usage.
RUN sed -i 's/<policy domain="path" rights="none" pattern="@\*"\/>/<!-- <policy domain="path" rights="none" pattern="@\*"\/> -->/g' /etc/ImageMagick-6/policy.xml

ENV TZ=Europe/Stockholm
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY --from=build-venv /venv /venv
RUN mkdir /app && groupadd -g 1000 derp && useradd -m -s /bin/bash -d /app -g 1000 -u 1000 derp
ADD main.py /app/main.py
RUN chown -R 1000:1000 /app

USER 1000:1000
WORKDIR /app

ENTRYPOINT ["/venv/bin/python3", "main.py"]