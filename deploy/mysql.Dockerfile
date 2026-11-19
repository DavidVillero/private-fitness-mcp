# Keep the official entrypoint/privilege model; rebuild its helper with patched Go.
FROM golang:1.27.3@sha256:e519d3b0a5b285e5aa53ab9eef02bc6bbb9cb04608389b743a136a9ce75f0d1e AS helper
RUN CGO_ENABLED=0 GOBIN=/out go install github.com/tianon/gosu@6456aaa0f3c854d199d0f037f068eb97515b7513

FROM mysql:8.4@sha256:a81d043930e51745522bd5c430961cf8286f0a23f0a9a2a6e0108f7ea71b0902
# mysqlsh and its embedded Python libraries are not used by the server or init SQL.
# The mysql and mysqldump clients remain available for operations and recovery.
RUN microdnf remove -y mysql-shell && microdnf clean all
COPY --from=helper /out/gosu /usr/local/bin/gosu
