# OCC Xtreme1 Development Runbook

This repository is an OCC extension fork of `xtreme1-io/xtreme1`.

## Current State

The OCC changes are implemented in:

- `frontend/pc-tool/src/packages/pc-render/occ/`
- `frontend/pc-tool/src/packages/pc-render/PointCloud.ts`
- `frontend/pc-tool/src/api/occ.ts`
- `backend/src/main/java/ai/basic/x1/adapter/api/controller/OccAnnotationController.java`
- `backend/src/main/java/ai/basic/x1/usecase/OccAnnotationUseCase.java`

The local checkout was created as a sparse checkout. To run the full platform, first make the checkout complete.

## Complete the Checkout

Run from the repository root:

```powershell
git sparse-checkout disable
```

If the network is unstable, fetch only the missing runtime directories first:

```powershell
git sparse-checkout add deploy frontend/main frontend/image-tool frontend/text-tool
```

After this, these paths must exist:

```text
deploy/nginx/conf.d/default.conf
deploy/mysql/custom.cnf
deploy/mysql/migration
frontend/main
frontend/image-tool
frontend/text-tool
```

## Run the OCC Fork

Install Docker Desktop first. The current machine used to prepare this repo did not have a `docker` command available, so Docker startup was not verified locally.

From the repository root:

```powershell
docker compose up --build
```

Open:

```text
http://localhost:8190
```

The compose file is configured to build `backend` and `frontend` from local source. This is required because the official Docker images do not include the OCC extension.

## OCC Annotation Storage

Saved OCC patch JSON files are stored in the Docker volume:

```text
occ-annotations
```

The backend receives the path through:

```text
OCC_ANNOTATION_PATH=/app/data/occ-annotations
```

## Development Frontend Only

For quick work on the point-cloud/OCC viewer:

```powershell
cd frontend/pc-tool
npm install
npm run dev
```

Open:

```text
http://localhost:3200
```

This only runs the point-cloud tool. Saving/exporting OCC edits still requires the backend.

## Remaining Integration Work

The OCC rendering and patch API are in place. To use real model outputs, implement a converter that:

1. Reads each frame `.npz`.
2. Converts dense OCC labels to sparse `{x, y, z, label}` records.
3. Serves the payload through `GET /api/occ/frame?dataId=...`.
4. Applies saved patch edits back to the original tensor.
5. Exports the modified clip as `.npz` files.

