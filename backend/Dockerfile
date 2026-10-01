FROM maven:3.9.9-eclipse-temurin-21@sha256:3a4ab3276a087bf276f79cae96b1af04f53731bec53fb2e651aca79e4b10211e AS build
WORKDIR /workspace
COPY pom.xml .
COPY src src
RUN --mount=type=cache,target=/root/.m2 mvn -B -ntp -DskipTests package
FROM eclipse-temurin:21-jre@sha256:d7051a45dd955e4d5d1db4d3f4269fe13d1c6dff8cc6b7ef89fc8577b96c1982
WORKDIR /app
RUN groupadd -r appliance && useradd -r -g appliance appliance
COPY --from=build /workspace/target/appliance-backend-0.1.0.jar /app/app.jar
USER appliance
EXPOSE 8080
ENTRYPOINT ["java","-jar","/app/app.jar"]
