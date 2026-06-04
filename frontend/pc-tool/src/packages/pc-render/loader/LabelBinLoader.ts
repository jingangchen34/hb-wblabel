import { FileLoader, Loader } from 'three';

type Callback = (args?: any) => void;

export interface LabelBinData {
    position: Float32Array;
    intensity: Float32Array;
    color: Uint8Array;
    pointLabels: Uint8Array;
    pointFields: Float32Array;
}

export interface LabelBinOptions {
    pointDim?: number;
    labelUrl?: string;
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

function colorize(labels: Uint8Array, colorMap: Record<number, string>) {
    const color = new Uint8Array(labels.length * 3);
    for (let index = 0; index < labels.length; index++) {
        const rgb = hexToRgb(colorMap[labels[index]] || '#ffffff');
        color[index * 3] = rgb[0];
        color[index * 3 + 1] = rgb[1];
        color[index * 3 + 2] = rgb[2];
    }
    return color;
}

export default class LabelBinLoader extends Loader {
    load(
        url: string,
        onLoad: Callback,
        onProgress?: Callback,
        onError?: Callback,
        options: LabelBinOptions = {},
    ) {
        const loader = new FileLoader(this.manager);
        loader.setPath(this.path);
        loader.setResponseType('arraybuffer');
        loader.setRequestHeader(this.requestHeader);
        loader.setWithCredentials(this.withCredentials);
        loader.load(
            url,
            async (binData) => {
                try {
                    const labelData = options.labelUrl
                        ? await this.loadLabel(options.labelUrl)
                        : new ArrayBuffer(0);
                    onLoad(this.parse(binData as ArrayBuffer, labelData, options));
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
        const pointDim = options.pointDim || 7;
        const bytesPerPoint = pointDim * 4;
        if (binData.byteLength % bytesPerPoint !== 0) {
            throw new Error(`Invalid .bin length ${binData.byteLength}; expected pointDim=${pointDim}`);
        }

        const pointCount = binData.byteLength / bytesPerPoint;
        const labels = new Uint8Array(labelData);
        if (labels.length > 0 && labels.length !== pointCount) {
            throw new Error(`.label point count ${labels.length} does not match .bin point count ${pointCount}`);
        }

        const source = new Float32Array(binData);
        const position = new Float32Array(pointCount * 3);
        const intensity = new Float32Array(pointCount);
        for (let index = 0; index < pointCount; index++) {
            const sourceOffset = index * pointDim;
            position[index * 3] = source[sourceOffset];
            position[index * 3 + 1] = source[sourceOffset + 1];
            position[index * 3 + 2] = source[sourceOffset + 2];
            intensity[index] = source[sourceOffset + 3] || 0;
        }

        const pointLabels = labels.length > 0 ? new Uint8Array(labels) : new Uint8Array(pointCount);
        return {
            position,
            intensity,
            color: colorize(pointLabels, { ...DEFAULT_LABEL_COLORS, ...(options.colorMap || {}) }),
            pointLabels,
            pointFields: source,
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
