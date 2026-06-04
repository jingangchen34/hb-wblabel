import { Points } from '../points';

export const DEFAULT_POINT_LABEL_COLORS: Record<number, string> = {
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

export function buildPointLabelColors(labels: Uint8Array, colorMap: Record<number, string> = {}) {
    const mergedMap = { ...DEFAULT_POINT_LABEL_COLORS, ...colorMap };
    const colors = new Uint8Array(labels.length * 3);
    for (let index = 0; index < labels.length; index++) {
        const rgb = hexToRgb(mergedMap[labels[index]] || '#ffffff');
        colors[index * 3] = rgb[0];
        colors[index * 3 + 1] = rgb[1];
        colors[index * 3 + 2] = rgb[2];
    }
    return colors;
}

export function setPointLabelByIndices(
    points: Points,
    indices: number[],
    label: number,
    colorMap: Record<number, string> = {},
) {
    const labels = points.exportPointLabels();
    if (!labels) return undefined;
    indices.forEach((index) => {
        if (index >= 0 && index < labels.length) labels[index] = label;
    });
    points.updatePointLabels(labels, buildPointLabelColors(labels, colorMap));
    return labels;
}
