FROM docker.m.daocloud.io/library/maven:3.8-openjdk-11
WORKDIR /build
COPY pom.xml .
RUN mvn -q -DskipTests dependency:go-offline
COPY src ./src
RUN mvn -q -DskipTests package
WORKDIR /app
RUN cp /build/target/xtreme1-backend-0.9.1-SNAPSHOT.jar ./app.jar
RUN mkdir -p config
EXPOSE 8080
CMD ["java", "-jar", "app.jar"]
