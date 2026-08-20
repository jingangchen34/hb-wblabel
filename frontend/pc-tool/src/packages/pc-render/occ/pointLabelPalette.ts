export const DEFAULT_POINT_LABEL_COLORS: Record<number, string> = {
    0: '#ffffff',
    1: '#808080',
    2: '#00ff00',
    3: '#0000ff',
    4: '#ffff00',
    5: '#00ffff',
    6: '#ff0000',
};

/** Map the source's detailed semantic labels to the coarser OCC labels shown by the tool. */
export function getDisplayPointLabel(label: number) {
    if (label >= 20 && label <= 23) return 2;
    if (label >= 30 && label <= 33) return 3;
    if (label >= 40 && label <= 41) return 4;
    if (label >= 50 && label <= 53) return 5;
    return label;
}

function hexToRgb(hex: string): [number, number, number] {
    const normalized = hex.replace('#', '');
    const value = Number.parseInt(normalized.length === 3
        ? normalized.split('').map((item) => item + item).join('')
        : normalized, 16);
    return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

export function getPointLabelRgb(label: number, colorMap: Record<number, string> = {}) {
    const displayLabel = getDisplayPointLabel(label);
    // An explicit source-label color has priority; otherwise use its coarse OCC color.
    const color = colorMap[label]
        || colorMap[displayLabel]
        || DEFAULT_POINT_LABEL_COLORS[displayLabel]
        || '#ffffff';
    return hexToRgb(color);
}

export function buildPointLabelColors(labels: Uint8Array, colorMap: Record<number, string> = {}) {
    const colors = new Uint8Array(labels.length * 3);
    const rgbMap: Record<number, [number, number, number]> = {};
    for (let index = 0; index < labels.length; index++) {
        const label = labels[index];
        const rgb = rgbMap[label] || (rgbMap[label] = getPointLabelRgb(label, colorMap));
        colors[index * 3] = rgb[0];
        colors[index * 3 + 1] = rgb[1];
        colors[index * 3 + 2] = rgb[2];
    }
    return colors;
}
