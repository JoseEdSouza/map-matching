FROM openjdk:21-jdk-slim

WORKDIR /app

# Instalar wget e unzip, limpar cache do apt
RUN apt-get update && \
    apt-get install -y --no-install-recommends wget unzip && \
    rm -rf /var/lib/apt/lists/*

RUN wget -q -O osm2po.zip "https://osm2po.de/releases/osm2po-5.5.16.zip" && \
    unzip -q osm2po.zip && \
    mkdir osm2po && \
    mv osm2po-core-5.5.16-signed.jar osm2po/ && \
    mv osm2po.config osm2po/ && \
    rm osm2po.zip

WORKDIR /app/osm2po

ENTRYPOINT ["java", "-jar", "osm2po-core-5.5.16-signed.jar"]
CMD ["help"]
