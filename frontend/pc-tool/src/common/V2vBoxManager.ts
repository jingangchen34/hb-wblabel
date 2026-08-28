import * as THREE from 'three';
import { IDataResource } from 'pc-editor';
import * as api from '../api';
import type Editor from './Editor';

const MAX_TIMESTAMP_GAP_NS = 500_000_000n;
const BOX_EDGES = [
    0, 1, 1, 2, 2, 3, 3, 0,
    4, 5, 5, 6, 6, 7, 7, 4,
    0, 4, 1, 5, 2, 6, 3, 7,
];

interface V2vBox {
    frameIndex: number;
    timestampNs: bigint;
    vehicleId: string;
    truckType: string;
    corners: THREE.Vector3[];
}

interface V2vFrame {
    frameIndex: number;
    timestampNs: bigint;
    boxes: V2vBox[];
}

function parseCsvLine(line: string) {
    const values: string[] = [];
    let value = '';
    let quoted = false;
    for (let index = 0; index < line.length; index += 1) {
        const char = line[index];
        if (char === '"') {
            if (quoted && line[index + 1] === '"') {
                value += '"';
                index += 1;
            } else {
                quoted = !quoted;
            }
        } else if (char === ',' && !quoted) {
            values.push(value);
            value = '';
        } else {
            value += char;
        }
    }
    values.push(value);
    return values;
}

function parseTimestamp(value: string | undefined) {
    try {
        return BigInt(value || '0');
    } catch (_) {
        return 0n;
    }
}

export function parseV2vCsv(text: string): V2vFrame[] {
    const lines = text.split(/\r?\n/).filter((line) => line.trim());
    if (lines.length < 2) return [];
    const headers = parseCsvLine(lines[0]);
    const frames = new Map<string, V2vFrame>();

    lines.slice(1).forEach((line) => {
        const values = parseCsvLine(line);
        const row = Object.fromEntries(headers.map((header, index) => [header, values[index] || '']));
        const timestampNs = parseTimestamp(row.frame_timestamp_ns || row.box_timestamp_ns);
        if (timestampNs <= 0n) return;
        const corners = Array.from({ length: 8 }, (_, index) => {
            const point = index + 1;
            return new THREE.Vector3(
                Number(row[`point${point}_x_m`]),
                Number(row[`point${point}_y_m`]),
                Number(row[`point${point}_z_m`]),
            );
        });
        if (corners.some((point) => !Number.isFinite(point.x + point.y + point.z))) return;
        const frameIndex = Number.parseInt(row.frame_index || '-1', 10);
        const key = timestampNs.toString();
        const frame = frames.get(key) || { frameIndex, timestampNs, boxes: [] };
        frame.boxes.push({
            frameIndex,
            timestampNs,
            vehicleId: row.vehicle_id || 'unknown',
            truckType: row.truck_type || 'unknown',
            corners,
        });
        frames.set(key, frame);
    });

    return Array.from(frames.values()).sort((left, right) =>
        left.timestampNs < right.timestampNs ? -1 : left.timestampNs > right.timestampNs ? 1 : 0,
    );
}

function timestampFromPointName(name?: string) {
    const match = String(name || '').match(/(\d{16,})/);
    return match ? parseTimestamp(match[1]) : 0n;
}

function absBigInt(value: bigint) {
    return value < 0n ? -value : value;
}

function findNearestFrame(frames: V2vFrame[], timestampNs: bigint, frameIndex: number) {
    if (!frames.length) return undefined;
    if (timestampNs <= 0n) {
        const frame = frames.find((item) => item.frameIndex === frameIndex);
        return frame ? { frame, gap: 0n } : undefined;
    }
    let nearest = frames[0];
    let gap = absBigInt(nearest.timestampNs - timestampNs);
    for (let index = 1; index < frames.length; index += 1) {
        const candidate = frames[index];
        const candidateGap = absBigInt(candidate.timestampNs - timestampNs);
        if (candidateGap < gap) {
            nearest = candidate;
            gap = candidateGap;
        }
    }
    return gap <= MAX_TIMESTAMP_GAP_NS ? { frame: nearest, gap } : undefined;
}

function createLabel(box: V2vBox, gapNs: bigint) {
    const canvas = document.createElement('canvas');
    canvas.width = 768;
    canvas.height = 96;
    const context = canvas.getContext('2d');
    if (!context) return undefined;
    context.fillStyle = 'rgba(8, 20, 32, 0.82)';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.strokeStyle = '#22d3ee';
    context.lineWidth = 5;
    context.strokeRect(2, 2, canvas.width - 4, canvas.height - 4);
    context.fillStyle = '#e6fbff';
    context.font = 'bold 34px sans-serif';
    context.fillText(
        `V2V  ${box.vehicleId}  type=${box.truckType}  dt=${Number(gapNs / 1_000_000n)}ms`,
        18,
        62,
    );
    const texture = new THREE.CanvasTexture(canvas);
    const material = new THREE.SpriteMaterial({ map: texture, depthTest: false, transparent: true });
    const sprite = new THREE.Sprite(material);
    const top = box.corners.reduce((result, point) => result.add(point), new THREE.Vector3()).multiplyScalar(1 / 8);
    top.z = Math.max(...box.corners.map((point) => point.z)) + 1.2;
    sprite.position.copy(top);
    sprite.scale.set(15, 1.875, 1);
    sprite.renderOrder = 1001;
    return sprite;
}

export default class V2vBoxManager {
    private editor: Editor;
    private group = new THREE.Group();
    private csvCache = new Map<string, Promise<V2vFrame[]>>();

    constructor(editor: Editor) {
        this.editor = editor;
        this.group.name = 'v2v-boxes';
        this.group.renderOrder = 1000;
        this.editor.pc.scene.add(this.group);
    }

    private clear() {
        this.group.traverse((object: any) => {
            object.geometry?.dispose?.();
            const materials = Array.isArray(object.material) ? object.material : [object.material];
            materials.filter(Boolean).forEach((material: any) => {
                material.map?.dispose?.();
                material.dispose?.();
            });
        });
        this.group.clear();
        this.editor.pc.render();
    }

    private load(url: string) {
        let pending = this.csvCache.get(url);
        if (!pending) {
            pending = api.getUrl(url).then((value) => parseV2vCsv(String(value || '')));
            this.csvCache.set(url, pending);
        }
        return pending;
    }

    async refreshCurrentFrame() {
        this.clear();
        const currentFrame = this.editor.getCurrentFrame();
        if (!currentFrame) return;
        const frameId = currentFrame.id;
        const resource = this.editor.dataResource.dataMap[frameId] as IDataResource | undefined;
        if (!resource?.v2vUrl) return;

        try {
            const frames = await this.load(resource.v2vUrl);
            if (this.editor.getCurrentFrame()?.id !== frameId) return;
            const match = findNearestFrame(
                frames,
                timestampFromPointName(resource.name),
                this.editor.state.frameIndex,
            );
            if (!match) return;

            match.frame.boxes.forEach((box) => {
                const positions: number[] = [];
                BOX_EDGES.forEach((cornerIndex) => {
                    const point = box.corners[cornerIndex];
                    positions.push(point.x, point.y, point.z);
                });
                const geometry = new THREE.BufferGeometry();
                geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
                const material = new THREE.LineBasicMaterial({
                    color: 0x22d3ee,
                    depthTest: false,
                    transparent: true,
                    opacity: 0.95,
                });
                const wireframe = new THREE.LineSegments(geometry, material);
                wireframe.renderOrder = 1000;
                wireframe.userData = { source: 'V2V', vehicleId: box.vehicleId, truckType: box.truckType };
                this.group.add(wireframe);

                const label = createLabel(box, match.gap);
                if (label) this.group.add(label);
            });
            this.editor.pc.render();
        } catch (error) {
            console.warn('load V2V boxes error', error);
        }
    }
}
