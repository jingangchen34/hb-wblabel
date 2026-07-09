import { Editor as BaseEditor, IFrame, SourceType } from 'pc-editor';
import { IBSState } from '../type';
import { getDefault } from '../state';
import { utils, AttrType, IClassificationAttr, IUserData } from 'pc-editor';
import * as api from '../api';
import { EVALUATION_GT_SOURCE_ID, EVALUATION_PRED_SOURCE_ID } from '../api/common';
import BusinessManager from './BusinessManager';
import DataManager from './DataManager';
import MultiFrameMergeManager from './MultiFrameMergeManager';

export default class Editor extends BaseEditor {
    businessManager: BusinessManager;
    dataManager: DataManager;
    multiFrameMergeManager: MultiFrameMergeManager;
    bsState: IBSState = getDefault();
    constructor() {
        super();

        this.businessManager = new BusinessManager(this);
        this.dataManager = new DataManager(this);
        this.multiFrameMergeManager = new MultiFrameMergeManager(this);
    }

    async loadFrame(index: number, showLoading: boolean = true, force: boolean = false) {
        this.multiFrameMergeManager.captureDisplayLabels();
        await super.loadFrame(index, showLoading, force);
        await this.multiFrameMergeManager.refreshDisplayForCurrentFrame();
    }

    needSave(frames?: IFrame[]) {
        frames = frames || this.state.frames;
        let needSaveData = frames.filter((e) => e.needSave);
        return needSaveData.length > 0;
    }

    async saveObject(frames?: IFrame[], force?: boolean) {
        let { bsState } = this;
        let { classTypes } = this.state;
        // let dataMeta = state.dataList[state.dataIndex];
        if (bsState.saving) return;

        frames = frames || this.state.frames;

        if (!force && !this.needSave(frames)) return;
        if (force) {
            await this.dataManager.loadMissingFrameObjects(frames.map((frame) => frame.id));
        }

        let dataInfos = [] as any[];
        let queryTime = frames[0].queryTime;
        frames.forEach((dataMeta) => {
            // if (dataMeta.skipped) return;
            if (!force && !dataMeta.needSave) return;
            let annotates = this.dataManager.getFrameObject(dataMeta.id) || [];
            if (new Date(dataMeta.queryTime).getTime() > new Date(queryTime).getTime())
                queryTime = dataMeta.queryTime;

            // result object
            let data = utils.convertAnnotate2Object(annotates, this);
            let infos = [] as any[];
            let dataAnnotations = [] as any[];
            data.forEach((e) => {
                let classConfig = this.getClassType(e.classId || e.classType || '');
                e.uuid = undefined;
                e.sourceId = this.state.config.withoutTaskId;
                e.sourceType = SourceType.DATA_FLOW;
                e.modelRun = '';
                e.modelRunLabel = '';
                let objectV2 = utils.translateToObjectV2(e, classConfig);
                infos.push({
                    id: undefined,
                    frontId: e.frontId,
                    classId: classConfig?.id,
                    source: 'ARTIFICIAL',
                    sourceId: this.state.config.withoutTaskId,
                    sourceType: SourceType.DATA_FLOW,
                    classAttributes: objectV2,
                });
            });

            dataMeta.classifications.forEach((classification) => {
                let values = utils.classificationToSave(classification);
                dataAnnotations.push({
                    classificationId: classification.id,
                    classificationAttributes: {
                        id: classification.id,
                        values: values,
                    },
                });
            });

            dataInfos.push({
                dataId: dataMeta.id,
                objects: infos,
                dataAnnotations: dataAnnotations,
            });
        });

        let objectInfo = {
            datasetId: bsState.datasetId,
            dataInfos: dataInfos,
        };
        bsState.saving = true;
        try {
            // debugger
            await api.saveObject(objectInfo).then((keyMap) => {
                this.updateBackId(keyMap);
                frames.forEach((frame) => {
                    const annotates = this.dataManager.getFrameObject(frame.id) || [];
                    annotates.forEach((annotate: any) => {
                        annotate.userData.sourceId = this.state.config.withoutTaskId;
                        annotate.userData.sourceType = SourceType.DATA_FLOW;
                        annotate.userData.modelRun = '';
                        annotate.userData.modelRunLabel = '';
                    });
                });
            });
            frames.forEach((e) => {
                e.needSave = false;
            });
            this.showMsg('success', this.lang('save-ok'));
        } catch (e: any) {
            console.error(e);
            this.showMsg('error', this.lang('save-error'));
        }
        bsState.saving = false;
    }

    updateBackId(keyMap: Record<string, Record<string, string>>) {
        Object.keys(keyMap).forEach((dataId) => {
            let dataKeyMap = keyMap[dataId];
            let annotates = this.dataManager.getFrameObject(dataId) || [];
            annotates.forEach((annotate: any) => {
                let frontId = annotate.uuid;
                let backId = dataKeyMap[frontId];
                if (!backId) return;
                annotate.userData.backId = backId;
                // annotate.uuid = backId;
            });
        });
    }
    async getResultSources(frame?: IFrame) {
        let { state } = this;
        frame = frame || this.getCurrentFrame();
        if (!frame.sources) {
            if (this.bsState.query.showEvaluation) {
                frame.sources = [
                    {
                        name: 'GT',
                        sourceId: EVALUATION_GT_SOURCE_ID,
                        sourceType: SourceType.DATA_FLOW,
                    },
                    {
                        name: 'Pred',
                        sourceId: EVALUATION_PRED_SOURCE_ID,
                        sourceType: SourceType.MODEL,
                    },
                ];
            } else {
                let sources = await api.getResultSources(frame.id);
                sources.unshift({
                    name: 'Without Task',
                    sourceId: state.config.withoutTaskId,
                    sourceType: SourceType.DATA_FLOW,
                });
                frame.sources = sources;
            }
        }
        this.setSources(frame.sources);

        // let sourceMap = {};
        // sources.forEach((e) => {
        //     sourceMap[e.sourceId] = true;
        // });
        // state.sourceFilters = [state.config.withoutTaskId];
        // state.sources = sources;
    }
}
