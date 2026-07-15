import { get, post } from './base';
import { IClassType, AttrType, IResultSource, SourceType } from 'pc-editor';
import {
    IFrame,
    IFileConfig,
    IObject,
    IModel,
    IClassificationAttr,
    IClassification,
    IModelResult,
} from 'pc-editor';
import { utils } from 'pc-editor';
// import { empty, queryStr } from '../utils';
// import { traverseClassification2Arr } from '../utils/classification';
// import BSError from '../common/BSError';
import * as THREE from 'three';

let { empty, queryStr, traverseClassification2Arr, traverseClass2Arr } = utils;
export const EVALUATION_GT_SOURCE_ID = 'EVAL_GT';
export const EVALUATION_PRED_SOURCE_ID = 'EVAL_PRED';

export interface ISeriesFrameInfo {
    id: string;
    firstDataId?: string;
    name: string;
}

export async function getUrl(url: string) {
    return get(url, null, { headers: { 'x-request-type': 'resource' } });
}

export async function saveObject(config: any) {
    let url = '/api/annotate/data/save';
    let data = await post(url, config);
    data = data.data || [];
    let keyMap = {} as Record<string, Record<string, string>>;
    data.forEach((e: any) => {
        let dataId = e.dataId;
        keyMap[dataId] = keyMap[dataId] || {};
        keyMap[dataId][e.frontId] = e.id;
    });

    return keyMap;
}


export async function getModelEvaluationCompare(evaluationId: string | number, dataId: string | number) {
    const res: any = await get(`/api/modelEvaluation/${evaluationId}/data/${dataId}/compare`);
    return res?.data || res;
}

function normalizeEvaluationObject(item: any, dataId: string, source: 'GT' | 'PRED', index: number): any {
    const raw = item?.classAttributes || item || {};
    const sourceId = source === 'GT' ? EVALUATION_GT_SOURCE_ID : EVALUATION_PRED_SOURCE_ID;
    const sourceType = source === 'GT' ? SourceType.DATA_FLOW : SourceType.MODEL;
    if (raw.contour?.center3D && raw.contour?.size3D) {
        return {
            ...raw,
            dataId,
            source,
            sourceId,
            sourceType,
            color: source === 'GT' ? '#22c55e' : '#ef4444',
            classType: raw.classType || raw.modelClass || raw.label || raw.meta?.classType,
            modelClass: raw.modelClass || raw.label || raw.classType || raw.meta?.classType,
            modelConfidence: raw.modelConfidence ?? raw.confidence,
            trackId: raw.trackId || raw.trackID || `${source}-${index}`,
            trackID: raw.trackID || raw.trackId || `${source}-${index}`,
            trackName: raw.trackName || raw.displayText || (source === 'PRED' && (raw.modelConfidence ?? raw.confidence) !== undefined
                ? `${raw.modelClass || raw.label || raw.classType || raw.meta?.classType || 'unknown'} ${Number(raw.modelConfidence ?? raw.confidence).toFixed(2)}`
                : undefined),
        };
    }
    const box = raw.box || raw;
    const label = raw.modelClass || raw.label || raw.classType || raw.meta?.classType || 'unknown';
    const confidence = raw.modelConfidence ?? raw.confidence;
    const dz = Number(box.dz ?? box.zSize ?? 0);
    return {
        id: raw.id || `${source}-${dataId}-${index}`,
        frontId: raw.frontId || raw.id || `${source}-${dataId}-${index}`,
        type: '3D_BOX',
        source,
        sourceId,
        sourceType,
        color: source === 'GT' ? '#22c55e' : '#ef4444',
        modelClass: label,
        classType: label,
        modelConfidence: confidence,
        trackId: raw.trackId || raw.trackID || `${source}-${index}`,
        trackID: raw.trackID || raw.trackId || `${source}-${index}`,
        trackName: raw.trackName || raw.displayText || (source === 'PRED' && confidence !== undefined
            ? `${label} ${Number(confidence).toFixed(2)}`
            : label),
        classValues: [],
        contour: {
            pointN: raw.pointN || 0,
            points: [],
            center3D: {
                x: Number(box.x ?? 0),
                y: Number(box.y ?? 0),
                z: Number(box.z ?? 0),
            },
            size3D: {
                x: Number(box.dx ?? box.xSize ?? 0),
                y: Number(box.dy ?? box.ySize ?? 0),
                z: dz,
            },
            rotation3D: {
                x: 0,
                y: 0,
                z: Number(box.yaw ?? box.rotZ ?? 0),
            },
        },
        meta: { isProjection: false },
    };
}

async function getEvaluationObjectsMap(evaluationId: string | number, dataIds: string[]) {
    const entries = await Promise.all(
        dataIds.map(async (dataId) => {
            const compare = await getModelEvaluationCompare(evaluationId, dataId);
            const gt = (compare?.groundTruths || []).map((item: any, index: number) =>
                utils.translateToObject(normalizeEvaluationObject(item, dataId, 'GT', index)),
            );
            const pred = (compare?.predictions || []).map((item: any, index: number) =>
                utils.translateToObject(normalizeEvaluationObject(item, dataId, 'PRED', index)),
            );
            return [dataId, [...gt, ...pred]] as const;
        }),
    );
    return entries.reduce((map, [dataId, objects]) => {
        map[dataId] = objects;
        return map;
    }, {} as Record<string, any[]>);
}
export async function getDataObjectBatch(dataIds: string[] | string, evaluationId?: string | number) {
    if (!Array.isArray(dataIds)) dataIds = [dataIds];
    const batchSize = 200;
    const requests: ReturnType<typeof getDataObject>[] = [];
    while (dataIds.length > 0) {
        const batchIds = dataIds.splice(0, batchSize);
        requests.push(getDataObject(batchIds, evaluationId));
    }
    return Promise.all(requests).then((res) => {
        return res.reduce(
            (map, item) => {
                Object.assign(map.objectsMap, item.objectsMap || {});
                Object.assign(map.classificationMap, item.classificationMap || {});
                return map;
            },
            { objectsMap: {}, classificationMap: {}, queryTime: Date.now() },
        );
    });
}

export async function getDataObject(dataIds: string[] | string, evaluationId?: string | number) {
    if (!Array.isArray(dataIds)) dataIds = [dataIds];

    let url = '/api/annotate/data/listByDataIds';
    let argsStr = queryStr({ dataIds });
    let data = await get(`${url}?${argsStr}`);
    data = data.data || [];
    let objectsMap = {} as Record<string, IObject[]>;
    let classificationMap = {};
    // let objects = [] as IObject[];
    data.forEach((e: any) => {
        const { dataId, objects, classificationValues } = e;
        objectsMap[dataId] = objects.map((o: any) => {
            let { id, sourceId, sourceType, classId } = o;
            return utils.translateToObject(
                Object.assign({ backId: id, sourceId, sourceType, classId }, o.classAttributes),
            );
        });
        classificationMap[dataId] = classificationValues.reduce((map: any, c: any) => {
            return Object.assign(
                map,
                utils.saveToClassificationValue(c.classificationAttributes.values),
            );
        }, {});
    });
    if (evaluationId) {
        objectsMap = await getEvaluationObjectsMap(evaluationId, dataIds);
    }
    return {
        objectsMap,
        classificationMap,
        queryTime: data.queryDate,
    };
}

export async function getDataClassification(dataIds: string[] | string) {
    if (!Array.isArray(dataIds)) dataIds = [dataIds];

    let url = `/api/annotate/data/listByDataIds`;
    let argsStr = queryStr({ dataIds });
    let data = await get(`${url}?${argsStr}`);
    // data = data.data || {};
    let dataAnnotations = data.data || [];

    let attrsMap = {} as Record<string, Record<string, string>>;
    dataAnnotations.forEach((e: any) => {
        let dataId = e.dataId;
        attrsMap[dataId] = attrsMap[dataId] || {};
        Object.assign(attrsMap[dataId], e.classificationAttributes || {});
    });
    return attrsMap;
}
export async function getDataClassificationBatch(dataIds: string[] | string) {
    if (!Array.isArray(dataIds)) dataIds = [dataIds];
    const batchSize = 200;
    const requests: Promise<any>[] = [];
    while (dataIds.length > 0) {
      const batchIds = dataIds.splice(0, batchSize);
      requests.push(getDataClassification(batchIds));
    }
    return Promise.all(requests).then((res) => {
      return res.reduce((map, item) => {
        return Object.assign(map, item);
      }, {});
    });
  }
export async function unlockRecord(recordId: string) {
    let url = `/api/data/unLock/${recordId}`;
    return await post(url);
}

export async function getDataStatus(dataIds: string[]) {
    const batchSize = 200;
    const requests: Promise<any>[] = [];
    let url = '/api/data/getDataStatusByIds';
    while (dataIds.length > 0) {
        const batchIds = dataIds.splice(0, batchSize);
        let argsStr = queryStr({ dataIds: batchIds });
        requests.push(get(`${url}?${argsStr}`));
    }
    return Promise.all(requests).then((res) => {
        const statusMap = {};
        res.forEach((re) => {
            re.data.forEach((item: any) => {
                statusMap[item.id] = item;
            });
        });
        return statusMap;
    });
}

export async function getInfoByRecordId(recordId: string) {
    let url = `/api/data/findDataAnnotationRecord/${recordId}`;
    let data = await get(url);
    data = data.data;
    // no data
    if (!data || !data.datas || data.datas.length === 0)
        return getInfoByDataId(recordId);

    let isSeriesFrame = ['FRAME_SERIES', 'SCENE'].includes(data.itemType);
    let modelRecordId = data.serialNo || '';
    const seriesFrameId = data.datas[0]?.sceneId ? data.datas[0].sceneId + '' : '';
    const seriesFrameName = seriesFrameId ? await getDataName(seriesFrameId + '') : '';
    let model = undefined as IModelResult | undefined;
    if (modelRecordId) {
        model = {
            recordId: modelRecordId,
            id: '',
            version: '',
            state: '',
        };
    }

    let dataInfos: IFrame[] = [];
    (data.datas || []).forEach((config: any) => {
        dataInfos.push({
            // id: config.id,
            id: config.dataId + '',
            datasetId: config.datasetId + '',
            teamId: config.teamId + '',
            // config: [],
            // viewConfig: [],
            pointsUrl: '',
            queryTime: '',
            loadState: '',
            model: model,
            needSave: false,
            classifications: [],
            dataStatus: 'VALID',
            annotationStatus: 'NOT_ANNOTATED',
            skipped: false,
        });
    });

    let ids = dataInfos.map((e) => e.id);
    let stateMap = await getDataStatus(ids);
    dataInfos.forEach((data) => {
        let status = stateMap[data.id];
        if (!status) return;
        data.dataStatus = status.status || 'VALID';
        data.annotationStatus = status.annotationStatus || 'NOT_ANNOTATED';
    });

    return { dataInfos, isSeriesFrame, seriesFrameId, seriesFrameName };
}

async function getInfoByDataId(dataId: string) {
    const dataResp = await get(`/api/data/listByIds`, { dataIds: dataId });
    const data = (dataResp.data || [])[0];
    if (!data) return { dataInfos: [], isSeriesFrame: false, seriesFrameId: '', seriesFrameName: '' };

    const datasetId = data.datasetId + '';
    const sceneId = data.parentId && data.parentId !== 0 ? data.parentId + '' : '';
    let seriesFrameName = '';
    let dataInfos = [] as IFrame[];
    let isSeriesFrame = false;

    if (sceneId) {
        isSeriesFrame = true;
        seriesFrameName = await getDataName(sceneId);
        dataInfos = await getFrameSeriesData(datasetId, sceneId);
        const currentIndex = dataInfos.findIndex((frame) => frame.id === dataId);
        if (currentIndex > 0) {
            dataInfos = dataInfos.slice(currentIndex).concat(dataInfos.slice(0, currentIndex));
        }
    } else {
        dataInfos = [buildFrameInfo(dataId, datasetId)];
        seriesFrameName = data.name || '';
    }

    return { dataInfos, isSeriesFrame, seriesFrameId: sceneId, seriesFrameName };
}

export async function getDataInfo(dataId: string) {
    if (!dataId) return undefined;
    const dataResp = await get(`/api/data/listByIds`, { dataIds: dataId });
    return (dataResp.data || [])[0];
}

export async function getDataName(dataId: string) {
    const data = await getDataInfo(dataId);
    return data?.name || '';
}

export interface ISceneAttribute {
    datasetId: string;
    dataId: string;
    category?: string;
    subType?: string;
}

export async function getSceneAttribute(dataId: string) {
    const res = await get(`/api/data/sceneAttribute`, { dataId });
    return (res.data || {}) as ISceneAttribute;
}

export async function saveSceneAttribute(attribute: ISceneAttribute) {
    await post(`/api/data/sceneAttribute`, attribute);
}

function buildFrameInfo(dataConfig: string | number | Record<string, any>, datasetId: string): IFrame {
    const isObject = typeof dataConfig === 'object' && dataConfig !== null;
    const dataId = isObject ? dataConfig.id || dataConfig.dataId : dataConfig;
    const name = isObject ? dataConfig.name || '' : '';
    const orderName = isObject ? dataConfig.orderName || dataConfig.order_name || '' : '';
    return {
        id: dataId + '',
        datasetId,
        name,
        orderName,
        pointsUrl: '',
        queryTime: '',
        loadState: '',
        needSave: false,
        classifications: [],
        dataStatus: 'VALID',
        annotationStatus: 'NOT_ANNOTATED',
        skipped: false,
    };
}

export async function saveDataClassification(config: any) {
    let url = `/api/annotate/data/save`;
    await post(url, config);
}

export async function getDataSetClassification(datasetId: string) {
    let url = `/api/datasetClassification/findAll/${datasetId}`;
    let data = await get(url);
    data = data.data || [];

    let classifications = traverseClassification2Arr(data);

    return classifications;
}

export async function getDataSetClass(datasetId: string) {
    let url = `/api/datasetClass/findAll/${datasetId}`;
    let data = await get(url);
    data = data.data || [];

    let classTypes = traverseClass2Arr(data);

    return classTypes;
}

export async function getDataFile(dataId: string) {
    let url = `/api/data/listByIds`;
    let data = await get(url, { dataIds: dataId });

    data = data.data || [];

    let configs = [] as IFileConfig[];
    const walk = (config: any, dirName: string) => {
        if (!config) return;
        if (config.file) {
            let fileUrl = config.file;
            if (fileUrl.binary) fileUrl = fileUrl.binary;
            configs.push({
                dirName,
                name: config.name,
                url: fileUrl.url,
                pointDim: config.pointDim,
            });
            return;
        }
        (config.files || []).forEach((file: any) => walk(file, config.name || dirName));
    };
    data[0].content.forEach((config: any) => {
        walk(config, config.name);
    });

    return { configs, name: data[0]?.name || '' };
}

export async function getUserInfo() {
    let url = `/api/user/logged`;
    let { data } = await get(url);
    return data;
}
export async function getDataSetInfo(datasetId: string) {
    let url = `/api/dataset/info/${datasetId}`;
    let { data } = await get(url);
    return data;
}

export async function annotateData(config: any) {
    let url = `/api/data/annotate`;
    let data = await post(url, config);
    return data;
}

export async function getLockRecord(datasetId: string) {
    let url = `/api/data/findLockRecordIdByDatasetId`;
    let data = await get(url, { datasetId });
    return data;
}
export async function getResultSources(dataId: string) {
    let url = `/api/data/getDataModelRunResult/${dataId}`;
    // let url = `/api/dataset/dataset/getDatasetAnnotateResult/${datasetId}`;
    let data = await get(url);

    data = data.data || {};

    let sources = [] as IResultSource[];
    data.forEach((item: any) => {
        let { modelId, modelName, runRecords = [] } = item;
        runRecords.forEach((e: any) => {
            sources.push({
                name: e.runNo,
                sourceId: e.id,
                modelId: modelId,
                modelName: modelName,
                sourceType: SourceType.MODEL,
            });
        });
    });
    return sources.filter((e) => e.sourceType !== SourceType.DATA_FLOW);
}
export async function getFrameSeriesData(datasetId: string, frameSeriesId: string) {
    const url = `/api/data/getDataIdBySceneIds`;
    const data = await get(url, {
        datasetId,
        sceneIds: frameSeriesId,
        // sortFiled: 'ID',
        // ascOrDesc: 'ASC',
    });

    const list = (data.data || {})[frameSeriesId] || [];
    // (list as any[]).reverse();
    if (list.length === 0) throw '';

    const dataList = [] as IFrame[];
    list.forEach((e: any) => {
        dataList.push(buildFrameInfo(e, datasetId));
    });
    return dataList;
    // return configs;
}

export async function getFrameSeriesList(datasetId: string): Promise<ISeriesFrameInfo[]> {
    const pageSize = 1000;
    let pageNo = 1;
    let total = Number.POSITIVE_INFINITY;
    const list: ISeriesFrameInfo[] = [];

    while ((pageNo - 1) * pageSize < total) {
        const data = await get('/api/data/findByPage', {
            datasetId,
            pageNo,
            pageSize,
            sortField: 'NAME',
            ascOrDesc: 'ASC',
        });
        const page = data.data || {};
        const items = page.list || [];
        total = page.total ?? items.length;

        items.forEach((item: any) => {
            if (item.type === 'SCENE') {
                list.push({
                    id: item.id + '',
                    firstDataId: item.firstDataId ? item.firstDataId + '' : undefined,
                    name: item.name || '',
                });
            }
        });

        if (items.length < pageSize) break;
        pageNo += 1;
    }

    return list;
}
