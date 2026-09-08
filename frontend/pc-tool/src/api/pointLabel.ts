import { get, post } from './base';

function labelsToBase64(labels: Uint8Array) {
    let binary = '';
    const chunkSize = 8192;
    for (let start = 0; start < labels.length; start += chunkSize) {
        const chunk = labels.subarray(start, start + chunkSize);
        binary += String.fromCharCode(...chunk);
    }
    return btoa(binary);
}

export function getPointLabels(dataId: string | number, preAnnotationId?: string | number) {
    return get<Blob>('/api/point-label/frame', { dataId, preAnnotationId }, { responseType: 'blob' });
}

export async function getSavedPointLabels(dataId: string | number, preAnnotationId?: string | number) {
    const labels = await getPointLabels(dataId, preAnnotationId);
    if (!labels.size) return undefined;
    return new Uint8Array(await labels.arrayBuffer());
}

export function savePointLabels(dataId: string | number, labels: Uint8Array, frameId?: string, preAnnotationId?: string | number) {
    return post('/api/point-label/save', {
        dataId,
        frameId,
        preAnnotationId,
        labelsBase64: labelsToBase64(labels),
    });
}

export function modifyPointLabels(dataId: string | number, labels: Uint8Array, frameId?: string, preAnnotationId?: string | number) {
    return post('/api/point-label/modify', {
        dataId,
        frameId,
        preAnnotationId,
        labelsBase64: labelsToBase64(labels),
    });
}

export function patchPointLabels(
    dataId: string | number,
    indices: number[],
    labels: Uint8Array,
    pointCount: number,
) {
    return post('/api/point-label/patch', {
        dataId,
        pointCount,
        indices,
        labelsBase64: labelsToBase64(labels),
    });
}

export function exportPointLabelClip(sceneId: string | number) {
    return post<Blob>('/api/point-label/export/clip', { sceneId }, { responseType: 'blob' });
}
