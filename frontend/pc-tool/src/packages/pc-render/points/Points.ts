import * as THREE from 'three';
import { PCDLoader } from '../loader';
import PointsMaterial from '../material/PointsMaterial';
import { Event } from '../config';
import { IPoints } from './type';

interface IData {
    position?: number[] | Float32Array;
    intensity?: number[] | Float32Array;
    color?: number[] | Uint8Array;
    pointLabels?: Uint8Array;
    pointFields?: Float32Array;
}

enum Status {
    loading = 'loading',
    completed = 'completed',
    failed = 'failed',
}

function createGeometry(data: IData = { position: [], color: [], intensity: [] }) {
    let geometry = new THREE.BufferGeometry();

    let positionAttr = new THREE.Float32BufferAttribute(data.position || [], 3);
    // positionAttr.usage = THREE.DynamicDrawUsage;

    let intensityAttr = new THREE.Float32BufferAttribute(data.intensity || [], 1);
    // intensityAttr.usage = THREE.DynamicDrawUsage;

    let colorAttr = new THREE.Uint8BufferAttribute(data.color || [], 3);
    // colorAttr.usage = THREE.DynamicDrawUsage;

    geometry.setAttribute('position', positionAttr);
    geometry.setAttribute('intensity', intensityAttr);
    geometry.setAttribute('color', colorAttr);
    return geometry;
}

export default class Points extends THREE.Points implements IPoints {
    completed: boolean = false;
    loading: boolean = false;
    timeStamp: number = 0;
    loader: PCDLoader = new PCDLoader();
    pointLabels?: Uint8Array;
    pointFields?: Float32Array;
    constructor(material: PointsMaterial) {
        let geometry = createGeometry();
        super(geometry, material);
    }

    clear() {
        return this;
    }

    setBufferAttribute(attr: THREE.Float32BufferAttribute, data: number[] | Float32Array = []) {
        if (!(data instanceof Float32Array)) data = new Float32Array(data);
        attr.array = data;
        attr.count = data.length / attr.itemSize;
        attr.needsUpdate = true;
    }

    updateData(data: IData) {
        const startedAt = performance.now();
        let geometry = this.geometry as THREE.BufferGeometry;
        // let position = data.position as number[];
        // let oldPosition = geometry.getAttribute('position') as THREE.Float32BufferAttribute;

        geometry.dispose();
        const createGeometryStartedAt = performance.now();
        this.geometry = createGeometry(data);
        console.log(
            `[pc-perf] step=createGeometry points=${this.geometry.getAttribute('position').count} ms=${Math.round(
                performance.now() - createGeometryStartedAt,
            )}`,
        );

        // if (oldPosition.count < position.length / oldPosition.itemSize) {
        //     geometry.dispose();
        //     geometry = createGeometry(data);
        //     this.geometry = geometry;
        // } else {
        // let positionAttr = geometry.getAttribute('position') as THREE.Float32BufferAttribute;
        // this.setBufferAttribute(positionAttr, data.position || []);
        // positionAttr.setDrawRange(0,);

        // let intensityAttr = geometry.getAttribute('intensity') as THREE.Float32BufferAttribute;
        // this.setBufferAttribute(intensityAttr, data.intensity || []);

        // let colorAttr = geometry.getAttribute('color') as THREE.Float32BufferAttribute;
        // this.setBufferAttribute(colorAttr, data.color || []);
        // }

        const boundingSphereStartedAt = performance.now();
        this.geometry.computeBoundingSphere();
        console.log(
            `[pc-perf] step=computeBoundingSphere ms=${Math.round(
                performance.now() - boundingSphereStartedAt,
            )}`,
        );
        this.pointLabels = data.pointLabels;
        this.pointFields = data.pointFields;
        this.dispatchEvent({ type: Event.POINTS_CHANGE });
        console.log(`[pc-perf] step=Points.updateData ms=${Math.round(performance.now() - startedAt)}`);
    }

    updatePointLabels(labels: Uint8Array, color: Uint8Array) {
        if (labels.length !== this.geometry.getAttribute('position').count) {
            throw new Error('Label count does not match point count');
        }
        this.pointLabels = new Uint8Array(labels);
        this.geometry.setAttribute('color', new THREE.Uint8BufferAttribute(color, 3));
        this.geometry.getAttribute('color').needsUpdate = true;
        this.dispatchEvent({ type: Event.POINTS_CHANGE });
    }

    exportPointLabels() {
        return this.pointLabels ? new Uint8Array(this.pointLabels) : undefined;
    }

    loadUrl(url: string, onProgress?: (percent: number) => void): Promise<any> {
        this.loading = true;
        let timeStamp = new Date().getTime();
        this.timeStamp = timeStamp;

        return new Promise((resolve, reject) => {
            this.loader.load(
                url,
                (data: any) => {
                    if (timeStamp !== this.timeStamp) {
                        reject();
                        return;
                    }

                    // this.dispatchEvent({ type: Event.LOAD_POINT_BEFORE });

                    this.updateData(data);
                    this.loading = false;
                    resolve(this);
                    // this.dispatchEvent({ type: Event.LOAD_POINT_AFTER });
                },
                (e) => {
                    if (onProgress) onProgress(e.loaded / e.total);
                },
                () => {
                    reject();
                },
            );
        });
    }
}
