import { Editor as BaseEditor, IFrame, SourceType, Event } from 'pc-editor';
import { IBSState } from '../type';
import { getDefault } from '../state';
import { utils, AttrType, IClassificationAttr, IClassType, IUserData } from 'pc-editor';
import * as api from '../api';
import { EVALUATION_GT_SOURCE_ID, EVALUATION_PRED_SOURCE_ID } from '../api/common';
import BusinessManager from './BusinessManager';
import DataManager from './DataManager';
import MultiFrameMergeManager from './MultiFrameMergeManager';
import V2vBoxManager from './V2vBoxManager';

function isEvaluationPrediction(object: any) {
    return (
        object?.source === 'PRED' ||
        object?.sourceId === EVALUATION_PRED_SOURCE_ID ||
        object?.sourceType === SourceType.MODEL
    );
}

function evaluationClassKey(object: any) {
    const key = String(
        object?.classType || object?.modelClass || object?.meta?.classType || object?.classId || '',
    ).toLowerCase();
    const aliases: Record<string, string> = {
        minetruck: 'mining_truck',
        vehicle2: 'excavator_body',
        excavator: 'excavator_body',
        vehicle2_head: 'excavator_head',
        vehicle: 'truck',
        vehicle1: 'truck',
        tram: 'truck',
    };
    return aliases[key] || key;
}

function prepareEvaluationGroundTruth(objects: any[], humanReview: boolean, targetClass?: string) {
    if (!humanReview) return objects.filter((object) => !isEvaluationPrediction(object));
    const targetKey = evaluationClassKey({ classType: targetClass });
    return objects.filter(
        (object) =>
            !isEvaluationPrediction(object) ||
            (!!targetKey && evaluationClassKey(object) === targetKey),
    );
}
export default class Editor extends BaseEditor {
    businessManager: BusinessManager;
    dataManager: DataManager;
    multiFrameMergeManager: MultiFrameMergeManager;
    v2vBoxManager: V2vBoxManager;
    bsState: IBSState = getDefault();
    private evaluationFrameObjectsLoading?: Promise<void>;
    private evaluationSavedFrameIds = new Set<string>();

    getEvaluationSavedFrameIds() {
        return Array.from(this.evaluationSavedFrameIds);
    }

    clearEvaluationSavedFrameIds() {
        this.evaluationSavedFrameIds.clear();
    }
    constructor() {
        super();

        this.businessManager = new BusinessManager(this);
        this.dataManager = new DataManager(this);
        this.multiFrameMergeManager = new MultiFrameMergeManager(this);
        this.v2vBoxManager = new V2vBoxManager(this);
    }

    getClassType(name: string | IUserData): IClassType | undefined {
        if (!name) return undefined;
        const direct = super.getClassType(name);
        if (direct) return direct;

        const rawKey = typeof name === 'string' ? name : name.classId || name.classType || '';
        const lowerKey = String(rawKey).toLowerCase();
        const exact = this.state.classTypes.find((item) => item.name.toLowerCase() === lowerKey);
        if (exact) return exact;

        const candidates: Record<string, string[]> = {
            mining_truck: ['MineTruck'],
            excavator_body: ['Excavator', 'Vehicle2'],
            excavator_head: ['Excavator_head', 'Vehicle2_head'],
            pedestrian: ['Pedestrian'],
            truck: ['Truck', 'Vehicle', 'Vehicle1', 'Tram'],
            car: ['Car'],
        };
        const candidateNames = candidates[evaluationClassKey({ classType: rawKey })] || [];
        return this.state.classTypes.find((item) => candidateNames.includes(item.name));
    }

    async loadFrame(index: number, showLoading: boolean = true, force: boolean = false) {
        this.multiFrameMergeManager.captureDisplayLabels();
        await super.loadFrame(index, showLoading, force);
        await this.ensureEvaluationFrameObjects();
        await this.multiFrameMergeManager.refreshDisplayForCurrentFrame();
        await this.v2vBoxManager.refreshCurrentFrame();
    }

    private async ensureEvaluationFrameObjects() {
        if (!this.bsState.query.showEvaluation || !this.state.isSeriesFrame) return;
        const currentFrame = this.getCurrentFrame();
        const missingFrameIds = currentFrame && !this.dataManager.getFrameObject(currentFrame.id)
            ? [currentFrame.id]
            : [];
        if (missingFrameIds.length === 0) return;

        if (!this.evaluationFrameObjectsLoading) {
            this.evaluationFrameObjectsLoading = this.dataManager
                .loadMissingFrameObjects(missingFrameIds)
                .then(() => {
                    if (this.currentTrack) {
                        this.dispatchEvent({
                            type: Event.CURRENT_TRACK_CHANGE,
                            data: this.currentTrack,
                        });
                    }
                })
                .finally(() => {
                    this.evaluationFrameObjectsLoading = undefined;
                });
        }
        await this.evaluationFrameObjectsLoading;
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

            // Evaluation predictions are display-only unless the user explicitly entered
            // human review from the evaluation page.
            const humanReview = bsState.query.humanReview === '1';
            let data = utils.convertAnnotate2Object(annotates, this);
            if (bsState.query.showEvaluation || bsState.query.evaluationId) {
                data = prepareEvaluationGroundTruth(
                    data,
                    humanReview,
                    bsState.query.evaluationTargetClass,
                );
            }
            let infos = [] as any[];
            let dataAnnotations = [] as any[];
            data.forEach((e) => {
                let classConfig = this.getClassType(e.classId || e.classType || '');
                const promotedPrediction = isEvaluationPrediction(e);
                e.uuid = undefined;
                e.sourceId = this.state.config.withoutTaskId;
                e.sourceType = SourceType.DATA_FLOW;
                e.modelRun = '';
                e.modelRunLabel = '';
                e.confidence = undefined;
                e.modelClass = '';
                if (promotedPrediction) {
                    e.trackName = String(e.trackId || e.trackID || '');
                }
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

        const savedDataIds = new Set(dataInfos.map((info) => String(info.dataId)));
        let objectInfo = {
            datasetId: bsState.datasetId,
            dataInfos: dataInfos,
            promoteModelResults: bsState.query.humanReview === '1',
        };
        bsState.saving = true;
        try {
            // debugger
            await api.saveObject(objectInfo).then((keyMap) => {
                this.updateBackId(keyMap);
                frames.forEach((frame) => {
                    if (!savedDataIds.has(String(frame.id))) return;
                    const annotates = this.dataManager.getFrameObject(frame.id) || [];
                    annotates.forEach((annotate: any) => {
                        if (
                            isEvaluationPrediction(annotate.userData) &&
                            evaluationClassKey(annotate.userData) !==
                                evaluationClassKey({
                                    classType: bsState.query.evaluationTargetClass,
                                })
                        ) {
                            return;
                        }
                        annotate.userData.sourceId = this.state.config.withoutTaskId;
                        annotate.userData.sourceType = SourceType.DATA_FLOW;
                        annotate.userData.modelRun = '';
                        annotate.userData.modelRunLabel = '';
                    });
                });
            });
            frames.forEach((e) => {
                if (!savedDataIds.has(String(e.id))) return;
                e.needSave = false;
            });
            if (bsState.query.humanReview === '1') {
                dataInfos.forEach((info) => this.evaluationSavedFrameIds.add(String(info.dataId)));
            }
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
                if (this.bsState.query.preAnnotationId) {
                    sources.push({
                        name: 'Pre-annotation',
                        sourceId: 'PRE_ANNOTATION',
                        sourceType: SourceType.MODEL,
                    });
                }
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
