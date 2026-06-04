# Point Label OCC Extension

This extension adds point-wise OCC/semantic label visualization to Xtreme1's point-cloud tool.

## Scope

- Load raw `.bin` point clouds where each point has 7 `float32` fields.
- Load raw `.label` files where each point has 1 `uint8` label.
- Color point clouds by semantic label.
- Edit point labels in memory.
- Save modified labels as raw `.label` buffers.
- Export clip-level `.label` files as a zip.

The current sample format is point-wise, not dense voxel-grid OCC:

```python
points = np.fromfile("frame.bin", dtype=np.float32).reshape(-1, 7)
labels = np.fromfile("frame.label", dtype=np.uint8)
assert len(points) == len(labels)
```

## Frontend Entry Points

- `frontend/pc-tool/src/packages/pc-render/loader/LabelBinLoader.ts`
- `frontend/pc-tool/src/packages/pc-render/occ/pointLabel.ts`
- `frontend/pc-tool/src/packages/pc-render/PointCloud.ts`
- `frontend/pc-tool/src/api/pointLabel.ts`

The editor can load point-wise labels through `IDataResource`:

```ts
{
  pointsUrl: '/path/to/frame.bin',
  labelUrl: '/path/to/frame.label',
  binPointDim: 7,
  labelColorMap: {
    0: '#475569',
    1: '#ff4d4f',
    3: '#faad14',
    6: '#ec4899',
  },
}
```

The loaded point cloud contains:

```ts
{
  position: Float32Array,   // x/y/z
  intensity: Float32Array,  // field 3
  color: Uint8Array,        // derived from label
  pointLabels: Uint8Array,  // raw label buffer
  pointFields: Float32Array // original 7-float point fields
}
```

## Backend Endpoints

- `GET /api/point-label/frame?dataId={id}` returns raw `.label` bytes.
- `POST /api/point-label/save` saves raw labels from base64.
- `POST /api/point-label/export/clip` exports saved `.label` files as a zip.

Configure sidecar storage:

```properties
occ.annotation.path=/data/xtreme1/point-labels
```

## Dense OCC Note

The old `OccGridLayer` remains in the codebase for future dense voxel-grid support. The current imported sample data is point-wise, so the direct production path is `.bin + .label` rather than `.npz` dense OCC.
