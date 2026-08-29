FROM eclipse-temurin:21-jdk

RUN useradd --create-home --uid 10001 grader

COPY --chown=grader:grader . /opt/template

USER grader
WORKDIR /opt/template

RUN ./gradlew test --no-daemon

ENTRYPOINT ["/opt/template/.judge-entrypoint.sh"]
