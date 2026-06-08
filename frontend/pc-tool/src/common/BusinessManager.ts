import {
    BusinessManager as BaseBusinessManager,
    IDataResource,
    IFrame,
    IObject,
    utils,
    IFileConfig,
    SourceType,
} from 'pc-editor';
import Editor from './Editor';
import * as api from '../api';

export default class BusinessManager extends BaseBusinessManager {
    editor: Editor;
    constructor(editor: Editor) {
        super(editor);
        this.editor = editor;
    }

    async loadFrameConfig(data: IFrame): Promise<IDataResource> {
        const startedAt = performance.now();
        const logStep = (step: string, stepStartedAt: number) => {
            console.log(
                `[pc-perf] frame=${data.id} step=loadFrameConfig.${step} ms=${Math.round(
                    performance.now() - stepStartedAt,
                )} total=${Math.round(performance.now() - startedAt)}`,
            );
        };
        const regLidar = new RegExp(/point(_?)cloud/i);
        const regConfig = new RegExp(/camera(_?)config/i);
        const dataFileStartedAt = performance.now();
        let { configs: fileConfig, name } = await api.getDataFile(data.id + '');
        logStep('getDataFile', dataFileStartedAt);
        if (fileConfig.filter((e) => regLidar.test(e.dirName)).length === 0) {
            throw this.editor.lang('no-point-data');
        }
        let cameraConfig = fileConfig.find((e) => regConfig.test(e.dirName)) as IFileConfig;

        // no camera config
        let cameraInfo = [];
        if (cameraConfig) {
            const cameraStartedAt = performance.now();
            cameraInfo = await api.getUrl(cameraConfig.url);
            logStep('getCameraConfig', cameraStartedAt);
        }

        const viewConfigStartedAt = performance.now();
        let info = utils.createViewConfig(fileConfig, cameraInfo);
        logStep('createViewConfig', viewConfigStartedAt);
        let config: IDataResource = {
            pointsUrl: info.pointsUrl,
            labelUrl: info.labelUrl,
            pointCacheUrl: info.pointCacheUrl,
            binPointDim: 7,
            pointsData: {},
            viewConfig: info.config,
            time: 0,
            name: name,
        };
        return config;

        // return {} as IDataResource;
    }

    async getFrameClassification(
        frame: IFrame | IFrame[],
    ): Promise<Record<string, Record<string, string>>> {
        let valueMap = await api.getDataClassificationBatch(
            Array.isArray(frame) ? frame.map((e) => e.id) : frame.id,
        );
        return valueMap;
    }

    async getFrameObject(frame: IFrame | IFrame[]): Promise<{
        objectsMap: Record<string, IObject[]>;
        classificationMap: Record<string, IObject[]>;
        queryTime: string;
    }> {
        let data = await api.getDataObjectBatch(
            Array.isArray(frame) ? frame.map((e) => e.id) : frame.id,
        );
        return data;
    }
}
