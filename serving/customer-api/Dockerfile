# Build context: repository root (needs the parent pom.xml).
FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY pom.xml .
COPY serving/customer-api/pom.xml serving/customer-api/
COPY serving/customer-api/src serving/customer-api/src
RUN mvn -q -B -pl serving/customer-api -am package -DskipTests

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /src/serving/customer-api/target/customer-api-*.jar app.jar
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "/app/app.jar"]
