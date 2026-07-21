import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';
import { useInjectEditor } from '../../state';
import { Event, IFrame, StatusType } from 'pc-editor';
import * as _ from 'lodash';
import * as api from '../../api';
import * as locale from './lang';
import screenFull from 'screenfull';
import { Modal } from 'ant-design-vue';
import { SideRenderView } from 'pc-render';

export default function useHeader() {
    let editor = useInjectEditor();
    let $$ = editor.bindLocale(locale);
    let { state, bsState } = editor;
    let editorState = editor.state;
    let dataIndex = ref(state.frameIndex + 1);
    let removeBoxPoints = ref(true);
    let selectedMergeCount = computed(() => ((state as any).mergeSelectedFrameIds || []).length);
    let mergeActive = computed(() => !!(state as any).mergeActive);
    let currentSeriesIndex = computed(() => {
        const list = bsState.seriesFrameList || [];
        return list.findIndex((item) => item.id === bsState.seriesFrameId);
    });
    let hasPreSeriesFrame = computed(() => state.isSeriesFrame && currentSeriesIndex.value > 0);
    let hasNextSeriesFrame = computed(
        () =>
            state.isSeriesFrame &&
            currentSeriesIndex.value >= 0 &&
            currentSeriesIndex.value < (bsState.seriesFrameList || []).length - 1,
    );
    let iState = reactive({
        fullScreen: false,
        dataName: '',
        frameName: '',
    });
    const evaluationSceneCache = new Map<string, Promise<{ name: string; frames: IFrame[] }>>();
    let nameUpdateVersion = 0;
    watch(
        () => state.frameIndex,
        () => {
            if (dataIndex.value !== state.frameIndex + 1) dataIndex.value = state.frameIndex + 1;
            updateName();
        },
    );
    watch(
        () => bsState.seriesFrameName,
        () => updateName(),
    );

    onMounted(() => {
        editor.addEventListener(Event.RESOURCE_LOAD_COMPLETE, updateName);
    });

    let currentFrame = computed(() => {
        let { frameIndex, frames } = editor.state;
        return frames[frameIndex];
    });

    let onIndexChange = _.debounce(() => {
        console.log('change', dataIndex.value);
        if (dataIndex.value && dataIndex.value - 1 >= 0) editor.loadFrame(dataIndex.value - 1);
    }, 200);

    function onIndexBlur() {
        if (!dataIndex.value) dataIndex.value = state.frameIndex + 1;
    }
    async function onFullScreen() {
        if (iState.fullScreen) {
            await screenFull.exit();
        } else {
            await screenFull.request();
        }
        iState.fullScreen = !iState.fullScreen;
        setTimeout(() => {
            editor.pc.renderViews.forEach((view) => {
                if (view instanceof SideRenderView) view.fitObject();
                view.render();
            });
        }, 400);
    }

    let updateName = async () => {
        const version = ++nameUpdateVersion;
        const frame = currentFrame.value;
        if (!frame) return;
        const resourceName = editor.dataResource.dataMap[frame.id]?.name || '';
        iState.frameName = resourceName || frame.name || frame.orderName || '';

        const query = bsState.query || {};
        if (query.evaluationDataIds || query.evaluationFrameSetKey) {
            try {
                const frameInfo = await api.getDataInfo(frame.id);
                const frameName = frameInfo?.name || iState.frameName;
                const sceneId = frameInfo?.parentId ? String(frameInfo.parentId) : '';
                if (!sceneId) {
                    if (version === nameUpdateVersion) iState.dataName = frameName;
                    return;
                }

                if (!evaluationSceneCache.has(sceneId)) {
                    evaluationSceneCache.set(
                        sceneId,
                        Promise.all([
                            api.getDataName(sceneId),
                            api.getFrameSeriesData(String(frame.datasetId || query.datasetId), sceneId),
                        ]).then(([name, frames]) => ({ name, frames })),
                    );
                }
                const scene = await evaluationSceneCache.get(sceneId)!;
                if (version !== nameUpdateVersion) return;
                const originalIndex = scene.frames.findIndex((item) => item.id === String(frame.id));
                const position = originalIndex >= 0 ? `（${originalIndex + 1}/${scene.frames.length}）` : '';
                iState.frameName = frameName;
                iState.dataName = [scene.name, frameName].filter(Boolean).join(' / ') + position;
                return;
            } catch (_) {
                if (version !== nameUpdateVersion) return;
            }
        }

        iState.dataName = bsState.seriesFrameName
            ? [bsState.seriesFrameName, iState.frameName].filter(Boolean).join(' / ')
            : iState.frameName;
    };
    function onSave() {
        editor.saveObject();
    }

    function onMergeSelected() {
        editor.multiFrameMergeManager.mergeSelected(removeBoxPoints.value);
    }

    function onMergeAll() {
        editor.multiFrameMergeManager.mergeAll(removeBoxPoints.value);
    }

    function onCancelMerge() {
        editor.multiFrameMergeManager.cancel();
    }

    function onPre() {
        editor.loadFrame(state.frameIndex - 1);
    }
    function onNext() {
        editor.loadFrame(state.frameIndex + 1);
    }

    async function onPreSeriesFrame() {
        await jumpSeriesFrame(currentSeriesIndex.value - 1);
    }

    async function onNextSeriesFrame() {
        await jumpSeriesFrame(currentSeriesIndex.value + 1);
    }

    async function jumpSeriesFrame(index: number) {
        const list = bsState.seriesFrameList || [];
        const item = list[index];
        if (!item || blocking.value) return;
        if (editor.needSave()) {
            const shouldSwitch = await editor
                .showConfirm({
                    title: 'Save Change',
                    subTitle: 'Do you want to save changes before switching clip?',
                    okText: 'Save',
                })
                .then(async () => {
                    await editor.saveObject();
                    return true;
                })
                .catch(() => false);
            if (!shouldSwitch) return;
        }
        const url = new URL(window.location.href);
        url.searchParams.set('dataId', item.id);
        url.searchParams.set('dataType', 'scene');
        url.searchParams.set('type', 'readOnly');
        window.location.href = url.toString();
    }

    async function onClose() {
        let status = '';
        if (editor.needSave()) {
            status = await editor
                .showModal('ModalConfirm', {
                    title: '',
                    closable: false,
                    data: {
                        // btns: ['ok'],
                        okText: 'Save',
                        content: 'Save Change',
                        subContent: 'Do you want to save changes?',
                    },
                })
                .then(
                    async (_status: 'discard' | 'ok') => {
                        return _status;
                    },
                    async (error) => 'cancel',
                );
        }

        if (status === 'ok') {
            await editor.saveObject();
        } else if (status === 'discard') {
            // clear save status
            editor.state.frames.forEach((e) => {
                e.needSave = false;
            });
        } else if (status === 'cancel') {
            return;
        }

        await unlockData();
    }

    async function unlockData() {
        if (editor.state.modeConfig.name !== 'view') {
            await api.unlockRecord(editor.bsState.recordId);
        }
        closeTab();
    }

    function closeTab() {
        let win = window.open('about:blank', '_self');
        win && win.close();
    }

    let blocking = computed(() => {
        return (
            bsState.saving ||
            bsState.validing ||
            bsState.submitting ||
            bsState.modifying ||
            editorState.status === StatusType.Loading ||
            editorState.status === StatusType.Create ||
            editorState.status === StatusType.Play
        );
    });

    function onHelp() {
        editor.showModal('ModelHelp', { title: 'Help', width: 1000 }).catch(() => {});
    }

    async function onToggleValid() {
        let { frameIndex, frames } = editor.state;
        let frame = frames[frameIndex];

        bsState.validing = true;
        try {
            if (frame.dataStatus === 'INVALID') {
                await api.validData(frame.id);
                frame.dataStatus = 'VALID';
            } else {
                await api.invalidData(frame.id);
                frame.dataStatus = 'INVALID';
            }
        } catch (error: any) {
            editor.handleErr(error, 'Operation Error');
        }
        bsState.validing = false;
    }

    async function onToggleSkip() {
        let { frameIndex, frames } = editor.state;
        // frame.skipped = !frame.skipped;
        await editor.saveObject([frames[frameIndex]]);
        if (frameIndex < frames.length - 1) {
            await editor.loadFrame(frameIndex + 1);
        } else {
            editor.showMsg('warning', 'This is last data');
        }
    }
    async function onSubmit() {
        let { frameIndex, frames, isSeriesFrame } = editor.state;
        const seriesFrameId = editor.bsState.seriesFrameId;
        let frame = frames[frameIndex];

        let objects = editor.dataManager.getFrameObject(frame.id) || [];
        if (isSeriesFrame) {
            objects = [];
            frames.forEach((f) => {
                const objs = editor.dataManager.getFrameObject(f.id) || [];
                objects.push(...objs);
            });
        }
        let continueFlag = true;
        if (frame.dataStatus === 'VALID' && objects.length === 0) {
            await editor
                .showConfirm({
                    title: 'Tip',
                    subTitle:
                        "you don't have any annotation yet, are you sure you want to submit this data? If you can't annotate this data, you'd better mark this data as invalid. Cancel/ submit anyway",
                })
                .then(async () => {
                    // await onToggleValid();
                })
                .catch(() => {
                    continueFlag = false;
                });
        }

        if (!continueFlag) return;

        // if (frame.skipped) return;
        bsState.submitting = true;
        try {
            if (isSeriesFrame) {
                await editor.saveObject(frames, true);
                await api.submitData(seriesFrameId ?? '');
                // await updateDataStatus(frames);
                unlockData();
                bsState.submitting = false;
                return;
            } else {
                await editor.saveObject([frame], true);
                await api.submitData(frame.id);
                await updateDataStatus([frame]);
            }

            editor.showMsg('success', 'Submit Success');
        } catch (error: any) {
            editor.handleErr(error, 'Operation Error');
        }
        bsState.submitting = false;

        // not last frame
        if (frameIndex !== frames.length - 1) {
            editor.loadFrame(frameIndex + 1);
        } else {
            // last frame
            let next = nextNotAnnotate();
            if (next < 0) {
                editor
                    .showConfirm({
                        title: 'Well Done!',
                        subTitle: 'You have finish all the annotation!',
                        okText: 'Close and release those data',
                        centered: true,
                    })
                    .then(() => {
                        unlockData();
                    })
                    .catch(() => {});
            } else {
                editor.loadFrame(next);
            }
        }
    }

    async function updateDataStatus(frames: IFrame[]) {
        let statusMap = await api.getDataStatus(frames.map((e) => e.id));
        frames.forEach((frame) => {
            if (statusMap[frame.id]) {
                let status = statusMap[frame.id];
                frame.dataStatus = status.status || 'VALID';
                frame.annotationStatus = status.annotationStatus || 'NOT_ANNOTATED';
            }
        });
    }

    function nextNotAnnotate() {
        let { frames } = editor.state;

        let frame = frames.find((e) => {
            return e.annotationStatus === 'NOT_ANNOTATED';
        });
        if (frame) return editor.getFrameIndex(frame.id);
        return -1;
    }

    async function onModify() {
        let { bsState } = editor;
        let frame = editor.getCurrentFrame();
        let config = {
            dataIds: [frame.id],
            operateItemType: 'SINGLE_DATA',
            datasetId: bsState.datasetId,
        };

        const isEvaluationAnomalySet =
            !!bsState.query.evaluationDataIds || !!bsState.query.evaluationFrameSetKey;
        if (isEvaluationAnomalySet) {
            config.dataIds = editor.state.frames.map((item) => item.id);
            config.operateItemType = 'SINGLE_DATA';
        } else if (editor.state.isSeriesFrame) {
            const seriesFrameId = bsState.seriesFrameId ?? '';
            config.dataIds = [seriesFrameId];
            config.operateItemType = 'SCENE';
        }

        bsState.modifying = true;
        try {
            let recordInfo = await api.getLockRecord(bsState.datasetId);
            if (recordInfo.data && recordInfo.data.recordId) {
                editor.showMsg('warning', 'You have 1 data occupied');
                bsState.modifying = false;
                return;
            }

            let data = await api.annotateData(config);
            if (data.code === 'OK' && data.data) {
                let recordId = data.data;
                let host = location.host || location.hostname;
                let pathname = location.pathname;
                let protocol = location.protocol;
                const url = new URL(`${protocol}//${host + pathname}${location.search}`);
                url.searchParams.set('recordId', recordId);
                url.searchParams.delete('type');
                if (url.searchParams.get('evaluationId')) {
                    url.searchParams.set('humanReview', '1');
                }
                location.href = url.toString();
            } else {
                editor.showMsg('warning', data.message || `Operation Failed`);
            }
        } catch (error: any) {
            editor.handleErr(error, 'Operation Failed');
        }
        bsState.modifying = false;
    }

    return {
        $$,
        iState,
        currentFrame,
        blocking,
        dataIndex,
        removeBoxPoints,
        selectedMergeCount,
        mergeActive,
        currentSeriesIndex,
        hasPreSeriesFrame,
        hasNextSeriesFrame,
        onIndexChange,
        onFullScreen,
        onHelp,
        onIndexBlur,
        onSave,
        onMergeSelected,
        onMergeAll,
        onCancelMerge,
        onPre,
        onNext,
        onPreSeriesFrame,
        onNextSeriesFrame,
        onClose,
        onToggleValid,
        onToggleSkip,
        onSubmit,
        onModify,
    };
}
