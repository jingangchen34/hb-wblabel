import { get, post } from './base';
import { OccGridData } from '../packages/pc-render/occ';

export interface OccPatchPayload {
    frameId?: string;
    meta?: OccGridData['meta'];
    edits: Array<{
        x: number;
        y: number;
        z: number;
        from: number;
        to: number;
    }>;
}

export function getOccGrid(dataId: string | number) {
    return get<OccGridData>('/api/occ/frame', { dataId });
}

export function saveOccPatch(dataId: string | number, patch: OccPatchPayload) {
    return post('/api/occ/patch', { dataId, ...patch });
}

export function exportOccClip(sceneId: string | number) {
    return post<Blob>('/api/occ/export/clip', { sceneId }, { responseType: 'blob' });
}
