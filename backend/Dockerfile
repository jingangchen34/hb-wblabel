FROM docker.m.daocloud.io/library/maven:3.8-openjdk-11
WORKDIR /build
ADD . .
RUN mvn package

RUN apt update && \
    apt install -y iputils-ping curl wget netcat python3 python3-pip git
RUN pip3 install --upgrade --force-reinstall git+https://github.com/xtreme1-io/xtreme1-sdk.git@6b53a73
WORKDIR /app
RUN cp /build/target/xtreme1-backend-0.9.1-SNAPSHOT.jar ./app.jar
RUN mkdir -p config
EXPOSE 8080
CMD java -jar app.jar
