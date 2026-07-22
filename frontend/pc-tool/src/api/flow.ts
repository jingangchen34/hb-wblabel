import { get, post } from './base';

export async function invalidData(dataId: string) {
    let url = `/api/data/flow/markAsInvalid/${dataId}`;
    let data = await post(url);
}

export async function validData(dataId: string) {
    let url = `/api/data/flow/markAsValid/${dataId}`;
    let data = await post(url);
}

export async function submitData(dataId: string) {
    let url = `/api/data/flow/submit/${dataId}`;
    let data = await post(url);
}
export async function submitSelectedData(dataIds: string[]) {
    await post('/api/data/flow/submitSelected', dataIds);
}