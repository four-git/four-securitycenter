ARG DEBIAN_IMAGE
FROM ${DEBIAN_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends python3 clamav clamav-freshclam yara util-linux ca-certificates suricata suricata-update \
    && dpkg-query -W > /usr/local/share/package-versions.txt \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 983 scanner && useradd -u 997 -g 983 -M scanner
WORKDIR /opt/four-securitycenter
COPY src/ ./src/
COPY config/freshclam.conf /etc/clamav/freshclam.conf
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 997:983
ENTRYPOINT ["python3", "/opt/four-securitycenter/src/container_service.py"]
CMD ["scheduler"]
