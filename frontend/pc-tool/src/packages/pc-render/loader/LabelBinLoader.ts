import { FileLoader, Loader } from 'three';

type Callback = (args?: any) => void;

export interface LabelBinData {
    position: Float32Array;
    intensity: Float32Array;
    color: Uint8Array;
    pointLabels: Uint8Array;
    pointFields?: Float32Array;
}

export interface LabelBinOptions {
    pointDim?: number | number[];
    labelUrl?: string;
    pointCache?: boolean;
    colorMap?: Record<number, string>;
}

const DEFAULT_LABEL_COLORS: Record<number, string> = {
    0: '#ffffff',
    1: '#808080',
    2: '#00ff00',
    3: '#0000ff',
    4: '#ffff00',
    5: '#00ffff',
    6: '#ff0000',
};

function hexToRgb(hex: string): [number, number, number] {
    const normalized = hex.replace('#', '');
    const value = Number.parseInt(normalized.length === 3
        ? normalized.split('').map((item) => item + item).join('')
        : normalized, 16);
    return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

function buildRgbMap(colorMap: Record<number, string>) {
    const rgbMap: Record<number, [number, number, number]> = {};
    Object.keys(colorMap).forEach((label) => {
        rgbMap[+label] = hexToRgb(colorMap[+label]);
    });
    return rgbMap;
}

function fillColor(
    color: Uint8Array,
    pointIndex: number,
    label: number,
    rgbMap: Record<number, [number, number, number]>,
    fallback: [number, number, number],
) {
    const rgb = rgbMap[label] || fallback;
    const offset = pointIndex * 3;
    color[offset] = rgb[0];
    color[offset + 1] = rgb[1];
    color[offset + 2] = rgb[2];
}

function resolvePointDim(binData: ArrayBuffer, labels: Uint8Array, optionDim?: number | number[]) {
    const floatCount = binData.byteLength / 4;
    const candidates = (Array.isArray(optionDim) ? optionDim : [optionDim, 6, 7, 4])
        .filter((dim): dim is number => Number.isFinite(dim) && !!dim && dim >= 3);

    if (labels.length > 0) {
        const dim = floatCount / labels.length;
        if (Number.isInteger(dim) && dim >= 3) return dim;
    }

    const pointDim = candidates.find((dim) => binData.byteLength % (dim * 4) === 0);
    if (pointDim) return pointDim;

    throw new Error(
        `Invalid .bin length ${binData.byteLength}; expected one of pointDim=${candidates.join('/')}`,
    );
}

export default class LabelBinLoader extends Loader {
    load(
        url: string,
        onLoad: Callback,
        onProgress?: Callback,
        onError?: Callback,
        options: LabelBinOptions = {},
    ) {
        const labelPromise = options.labelUrl
            ? this.loadLabel(options.labelUrl)
            : Promise.resolve(new ArrayBuffer(0));
        const loader = new FileLoader(this.manager);
        loader.setPath(this.path);
        loader.setResponseType('arraybuffer');
        loader.setRequestHeader(this.requestHeader);
        loader.setWithCredentials(this.withCredentials);
        loader.load(
            url,
            async (binData) => {
                try {
                    const labelData = await labelPromise;
                    onLoad(options.pointCache
                        ? this.parsePointCache(binData as ArrayBuffer, options)
                        : this.parse(binData as ArrayBuffer, labelData, options));
                } catch (error) {
                    if (onError) onError(error);
                    this.manager.itemError(url);
                }
            },
            onProgress,
            onError,
        );
    }

    parse(binData: ArrayBuffer, labelData: ArrayBuffer, options: LabelBinOptions = {}): LabelBinData {
        const labels = new Uint8Array(labelData);
        const pointDim = resolvePointDim(binData, labels, options.pointDim);
        const bytesPerPoint = pointDim * 4;

        const pointCount = binData.byteLength / bytesPerPoint;
        if (labels.length > 0 && labels.length !== pointCount) {
            throw new Error(`.label point count ${labels.length} does not match .bin point count ${pointCount}`);
        }

        const source = new Float32Array(binData);
        const position = new Float32Array(pointCount * 3);
        const intensity = new Float32Array(pointCount);
        const color = new Uint8Array(pointCount * 3);
        const pointLabels = labels.length > 0 ? labels : new Uint8Array(pointCount);
        const mergedColorMap = { ...DEFAULT_LABEL_COLORS, ...(options.colorMap || {}) };
        const rgbMap = buildRgbMap(mergedColorMap);
        const fallback = hexToRgb('#ffffff');
        for (let index = 0; index < pointCount; index++) {
            const sourceOffset = index * pointDim;
            position[index * 3] = source[sourceOffset];
            position[index * 3 + 1] = source[sourceOffset + 1];
            position[index * 3 + 2] = source[sourceOffset + 2];
            intensity[index] = pointDim > 3 ? source[sourceOffset + 3] : 0;
            fillColor(color, index, pointLabels[index], rgbMap, fallback);
        }

        return {
            position,
            intensity,
            color,
            pointLabels,
        };
    }

    parsePointCache(cacheData: ArrayBuffer, options: LabelBinOptions = {}): LabelBinData {
        const startedAt = performance.now();
        const headerBytes = 16;
        if (cacheData.byteLength < headerBytes) {
            throw new Error(`Invalid .xyzl length ${cacheData.byteLength}`);
        }
        const header = new DataView(cacheData, 0, headerBytes);
        const magic = header.getUint32(0, true);
        const version = header.getUint32(4, true);
        const pointCount = header.getUint32(8, true);
        const labelOffset = headerBytes + pointCount * 12;
        const colorOffset = labelOffset + pointCount;
        const version1Length = colorOffset;
        const version2Length = colorOffset + pointCount * 3;
        const expectedLength = version === 2 ? version2Length : version1Length;
        if (magic !== 0x4c5a5958 || ![1, 2].includes(version) || cacheData.byteLength !== expectedLength) {
            throw new Error(`Invalid .xyzl header or length, version=${version}, length=${cacheData.byteLength}`);
        }

        const position = new Float32Array(cacheData, headerBytes, pointCount * 3);
        const pointLabels = new Uint8Array(cacheData, labelOffset, pointCount);
        let color: Uint8Array;
        if (version === 2) {
            color = new Uint8Array(cacheData, colorOffset, pointCount * 3);
        } else {
            color = new Uint8Array(pointCount * 3);
            const mergedColorMap = { ...DEFAULT_LABEL_COLORS, ...(options.colorMap || {}) };
            const rgbMap = buildRgbMap(mergedColorMap);
            const fallback = hexToRgb('#ffffff');
            for (let index = 0; index < pointCount; index++) {
                fillColor(color, index, pointLabels[index], rgbMap, fallback);
            }
        }

        console.log(
            `[pc-perf] step=parsePointCache version=${version} points=${pointCount} ms=${Math.round(
                performance.now() - startedAt,
            )}`,
        );

        return {
            position,
            intensity: new Float32Array(0),
            color,
            pointLabels,
        };
    }

    private loadLabel(url: string) {
        return new Promise<ArrayBuffer>((resolve, reject) => {
            const loader = new FileLoader(this.manager);
            loader.setResponseType('arraybuffer');
            loader.setRequestHeader(this.requestHeader);
            loader.setWithCredentials(this.withCredentials);
            loader.load(url, (data) => resolve(data as ArrayBuffer), undefined, reject);
        });
    }
}
