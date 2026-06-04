import * as THREE from 'three';

export interface OccGridMeta {
    gridSize: [number, number, number];
    voxelSize: [number, number, number];
    origin: [number, number, number];
    frameId?: string;
}

export interface OccVoxel {
    x: number;
    y: number;
    z: number;
    label: number;
}

export interface OccGridData {
    meta: OccGridMeta;
    voxels: OccVoxel[];
    colorMap?: Record<number, string>;
}

export interface OccEdit {
    x: number;
    y: number;
    z: number;
    from: number;
    to: number;
}

export interface OccBrushOptions {
    label: number;
    min: THREE.Vector3;
    max: THREE.Vector3;
}

