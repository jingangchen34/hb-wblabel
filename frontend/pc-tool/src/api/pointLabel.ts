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

export function getPointLabels(dataId: string | number) {
    return get<Blob>('/api/point-label/frame', { dataId }, { responseType: 'blob' });
}

export function savePointLabels(dataId: string | number, labels: Uint8Array, frameId?: string) {
    return post('/api/point-label/save', {
        dataId,
        frameId,
        labelsBase64: labelsToBase64(labels),
    });
}

export function modifyPointLabels(dataId: string | number, labels: Uint8Array, frameId?: string) {
    return post('/api/point-label/modify', {
        dataId,
        frameId,
        labelsBase64: labelsToBase64(labels),
    });
}

export function exportPointLabelClip(sceneId: string | number) {
    return post<Blob>('/api/point-label/export/clip', { sceneId }, { responseType: 'blob' });
}
