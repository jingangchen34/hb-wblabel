import { Points } from '../points';
import { Event } from '../config';
import {
    buildPointLabelColors,
    DEFAULT_POINT_LABEL_COLORS,
    getPointLabelRgb,
} from './pointLabelPalette';

export { buildPointLabelColors, DEFAULT_POINT_LABEL_COLORS, getDisplayPointLabel } from './pointLabelPalette';

export function setPointLabelByIndices(
    points: Points,
    indices: number[],
    label: number,
    colorMap: Record<number, string> = {},
) {
    const labels = points.pointLabels;
    if (!labels) return undefined;

    const rgb = getPointLabelRgb(label, colorMap);
    let colorAttr = points.geometry.getAttribute('color') as any;
    if (!colorAttr || colorAttr.array.length !== labels.length * 3) {
        points.updatePointLabels(labels, buildPointLabelColors(labels, colorMap));
        colorAttr = points.geometry.getAttribute('color') as any;
    }
    const color = colorAttr.array as Uint8Array;

    indices.forEach((index) => {
        if (index >= 0 && index < labels.length) {
            labels[index] = label;
            color[index * 3] = rgb[0];
            color[index * 3 + 1] = rgb[1];
            color[index * 3 + 2] = rgb[2];
        }
    });
    colorAttr.needsUpdate = true;
    points.dispatchEvent({ type: Event.POINTS_CHANGE });
    return labels;
}
