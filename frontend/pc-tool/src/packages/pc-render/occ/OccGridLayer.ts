import * as THREE from 'three';
import { OccBrushOptions, OccEdit, OccGridData, OccGridMeta, OccVoxel } from './types';

const DEFAULT_COLOR_MAP: Record<number, string> = {
    0: '#222831',
    1: '#ff4d4f',
    2: '#faad14',
    3: '#52c41a',
    4: '#1677ff',
    5: '#13c2c2',
    6: '#722ed1',
    7: '#eb2f96',
    8: '#a0d911',
    9: '#f759ab',
    10: '#d46b08',
    11: '#08979c',
    12: '#531dab',
    13: '#389e0d',
    14: '#096dd9',
    15: '#c41d7f',
};

function voxelKey(x: number, y: number, z: number) {
    return `${x},${y},${z}`;
}

export default class OccGridLayer extends THREE.Group {
    meta?: OccGridMeta;
    edits: OccEdit[] = [];
    opacity = 0.72;

    private voxels: OccVoxel[] = [];
    private indexMap = new Map<string, number>();
    private colorMap: Record<number, string> = DEFAULT_COLOR_MAP;
    private mesh?: THREE.InstancedMesh;
    private visibleLabels = new Set<number>();
    private zRange?: [number, number];

    constructor() {
        super();
        this.name = 'occ-grid-layer';
    }

    setData(data: OccGridData) {
        this.clearLayer();
        this.meta = data.meta;
        this.voxels = data.voxels.map((voxel) => ({ ...voxel }));
        this.colorMap = { ...DEFAULT_COLOR_MAP, ...(data.colorMap || {}) };
        this.edits = [];
        this.indexMap.clear();
        this.visibleLabels = new Set(this.voxels.map((voxel) => voxel.label));
        this.voxels.forEach((voxel, index) => this.indexMap.set(voxelKey(voxel.x, voxel.y, voxel.z), index));
        this.rebuildMesh();
    }

    setOpacity(opacity: number) {
        this.opacity = THREE.MathUtils.clamp(opacity, 0.05, 1);
        if (this.mesh) {
            const material = this.mesh.material as THREE.MeshBasicMaterial;
            material.opacity = this.opacity;
            material.transparent = this.opacity < 1;
            material.needsUpdate = true;
        }
    }

    setZRange(range?: [number, number]) {
        this.zRange = range;
        this.rebuildMesh();
    }

    setVisibleLabels(labels: number[]) {
        this.visibleLabels = new Set(labels);
        this.rebuildMesh();
    }

    setVoxelLabel(x: number, y: number, z: number, label: number) {
        const key = voxelKey(x, y, z);
        const index = this.indexMap.get(key);
        if (index === undefined) {
            this.voxels.push({ x, y, z, label });
            this.indexMap.set(key, this.voxels.length - 1);
            this.edits.push({ x, y, z, from: -1, to: label });
        } else {
            const voxel = this.voxels[index];
            if (voxel.label === label) return;
            this.edits.push({ x, y, z, from: voxel.label, to: label });
            voxel.label = label;
        }
        this.visibleLabels.add(label);
        this.rebuildMesh();
    }

    fillBox(options: OccBrushOptions) {
        if (!this.meta) return;

        const min = this.worldToGrid(options.min);
        const max = this.worldToGrid(options.max);
        const start = {
            x: Math.min(min.x, max.x),
            y: Math.min(min.y, max.y),
            z: Math.min(min.z, max.z),
        };
        const end = {
            x: Math.max(min.x, max.x),
            y: Math.max(min.y, max.y),
            z: Math.max(min.z, max.z),
        };

        for (let x = start.x; x <= end.x; x++) {
            for (let y = start.y; y <= end.y; y++) {
                for (let z = start.z; z <= end.z; z++) {
                    if (this.inGrid(x, y, z)) this.setVoxelLabel(x, y, z, options.label);
                }
            }
        }
    }

    pickVoxel(raycaster: THREE.Raycaster) {
        if (!this.mesh) return undefined;
        const hits = raycaster.intersectObject(this.mesh, false);
        const hit = hits[0];
        if (!hit || hit.instanceId === undefined) return undefined;
        return this.mesh.userData.instanceToVoxel[hit.instanceId] as OccVoxel | undefined;
    }

    exportPatch() {
        return {
            frameId: this.meta?.frameId,
            meta: this.meta,
            edits: [...this.edits],
        };
    }

    clearLayer() {
        if (this.mesh) {
            this.remove(this.mesh);
            this.mesh.geometry.dispose();
            (this.mesh.material as THREE.Material).dispose();
            this.mesh = undefined;
        }
    }

    private rebuildMesh() {
        if (!this.meta) return;
        this.clearLayer();

        const visibleVoxels = this.voxels.filter((voxel) => {
            const labelVisible = this.visibleLabels.size === 0 || this.visibleLabels.has(voxel.label);
            const zVisible = !this.zRange || (voxel.z >= this.zRange[0] && voxel.z <= this.zRange[1]);
            return labelVisible && zVisible;
        });
        if (visibleVoxels.length === 0) return;

        const [sx, sy, sz] = this.meta.voxelSize;
        const geometry = new THREE.BoxGeometry(sx, sy, sz);
        const material = new THREE.MeshBasicMaterial({
            opacity: this.opacity,
            transparent: this.opacity < 1,
            vertexColors: true,
        });
        const mesh = new THREE.InstancedMesh(geometry, material, visibleVoxels.length);
        mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);

        const matrix = new THREE.Matrix4();
        const color = new THREE.Color();
        visibleVoxels.forEach((voxel, index) => {
            const center = this.gridToWorld(voxel.x, voxel.y, voxel.z);
            matrix.makeTranslation(center.x, center.y, center.z);
            mesh.setMatrixAt(index, matrix);
            color.set(this.colorMap[voxel.label] || DEFAULT_COLOR_MAP[voxel.label % 16]);
            mesh.setColorAt(index, color);
        });
        mesh.userData.instanceToVoxel = visibleVoxels;
        this.mesh = mesh;
        this.add(mesh);
    }

    private gridToWorld(x: number, y: number, z: number) {
        if (!this.meta) return new THREE.Vector3();
        const [ox, oy, oz] = this.meta.origin;
        const [sx, sy, sz] = this.meta.voxelSize;
        return new THREE.Vector3(ox + (x + 0.5) * sx, oy + (y + 0.5) * sy, oz + (z + 0.5) * sz);
    }

    private worldToGrid(position: THREE.Vector3) {
        if (!this.meta) return { x: 0, y: 0, z: 0 };
        const [ox, oy, oz] = this.meta.origin;
        const [sx, sy, sz] = this.meta.voxelSize;
        return {
            x: Math.floor((position.x - ox) / sx),
            y: Math.floor((position.y - oy) / sy),
            z: Math.floor((position.z - oz) / sz),
        };
    }

    private inGrid(x: number, y: number, z: number) {
        if (!this.meta) return false;
        const [gx, gy, gz] = this.meta.gridSize;
        return x >= 0 && y >= 0 && z >= 0 && x < gx && y < gy && z < gz;
    }
}

