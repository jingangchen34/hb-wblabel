FROM docker.m.daocloud.io/library/maven:3.8-openjdk-11
WORKDIR /build
COPY settings.xml /root/.m2/settings.xml

RUN sed -i \
        -e 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' \
        -e 's|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' \
        -e 's|http://security.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' \
        /etc/apt/sources.list && \
    apt-get update -o Acquire::Retries=5 && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        iputils-ping \
        curl \
        wget \
        netcat-openbsd \
        python3 \
        python3-pip \
        git && \
    rm -rf /var/lib/apt/lists/*
RUN pip3 install --upgrade --force-reinstall git+https://github.com/xtreme1-io/xtreme1-sdk.git@6b53a73

COPY pom.xml .
RUN mvn -q -DskipTests dependency:go-offline
COPY src ./src
RUN mvn -q -DskipTests package

WORKDIR /app
RUN cp /build/target/xtreme1-backend-0.9.1-SNAPSHOT.jar ./app.jar
RUN mkdir -p config
EXPOSE 8080
CMD java -jar app.jar
