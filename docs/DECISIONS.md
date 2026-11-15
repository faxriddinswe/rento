# Decision records

## D001 — MinIO image source
- **Context:** `minio/minio` on Docker Hub no longer exists and `quay.io/minio/minio` returns 401 (MinIO stopped publishing community images).
- **Options:** build MinIO from source; use another S3 server (Garage/SeaweedFS); use the Chainguard build of MinIO (`chainguard/minio`, public on Docker Hub).
- **Decision:** `chainguard/minio:latest` (MinIO built from the official source by Chainguard, distroless, runs as uid 65532). Pin by digest before production deploy.
- **Consequences:** image has no shell/curl, so no in-container healthcheck; the API's `/ready` checks storage instead and creates the bucket on startup. Storage is behind a `Storage` interface so another S3 server can be swapped in via env.

## D002 — Dev ports
Host ports 5441/6391/9110/9111/8010/3010 because 5455/6380/6390 etc. are used by other projects on this machine.
