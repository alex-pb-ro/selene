# All dependencies are copied from previously provisioned local tools. Build offline.
FROM selene-isolated:local
USER root
COPY dependencies /opt/benchmark/dependencies
COPY typescript /opt/benchmark/typescript
COPY checks.py container_worker.py /opt/benchmark/
COPY tooling.json /opt/benchmark/tooling.json
LABEL io.selene.benchmark.profile="submission-v1"
WORKDIR /tmp
USER 65534:65534
ENTRYPOINT ["/opt/selene/.venv/bin/python", "-I", "-S", "/opt/benchmark/container_worker.py"]
