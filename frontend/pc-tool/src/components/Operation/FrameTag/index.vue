<template>
    <div v-if="isViewMode" class="frame-tag-panel">
        <div class="panel-title">逐帧筛选标签</div>
        <div class="tag-list">
            <button
                v-for="item in tagOptions"
                :key="item.value"
                :class="['tag-button', { active: state.tag === item.value }]"
                :disabled="state.loading || state.saving"
                @click="selectTag(item.value)"
            >
                {{ item.label }}
            </button>
        </div>
        <div class="tag-status">
            <span>{{ state.saving ? '保存中…' : state.tag ? `当前：${tagLabel(state.tag)}` : '当前：未标记' }}</span>
            <button class="clear" :disabled="state.loading || state.saving || !state.tag" @click="selectTag(undefined)">
                清除
            </button>
        </div>

        <div class="export-block">
            <div class="export-title">筛选并导出原始数据</div>
            <label v-for="item in tagOptions" :key="`export-${item.value}`" class="check-item">
                <input v-model="state.exportTags" type="checkbox" :value="item.value" />
                {{ item.label }}（{{ state.counts[item.value] || 0 }}）
            </label>
            <select v-model="state.scope" class="scope-select">
                <option value="scene">当前 Clip</option>
                <option value="dataset">整个数据集</option>
            </select>
            <button
                class="export-button"
                :disabled="state.exporting || state.exportTags.length === 0"
                @click="startExport"
            >
                {{ state.exporting ? `导出中 ${state.progress}%` : '导出已标记帧' }}
            </button>
            <div v-if="state.exportMessage" class="export-message">{{ state.exportMessage }}</div>
        </div>
    </div>
</template>

<script setup lang="ts">
    import { computed, onBeforeUnmount, onMounted, reactive, watch } from 'vue';
    import { useInjectEditor } from '../../../state';
    import * as api from '../../../api';
    import type { FrameTag, IFrameTagCounts } from '../../../api/common';

    const tagOptions: Array<{ value: FrameTag; label: string }> = [
        { value: 'splash', label: '水花' },
        { value: 'rut', label: '车辙' },
        { value: 'dust', label: '灰尘' },
    ];

    const editor = useInjectEditor();
    const state = reactive({
        tag: undefined as FrameTag | undefined,
        loading: false,
        saving: false,
        exportTags: tagOptions.map((item) => item.value) as FrameTag[],
        scope: 'scene' as 'scene' | 'dataset',
        counts: { splash: 0, rut: 0, dust: 0 } as IFrameTagCounts,
        exporting: false,
        progress: 0,
        exportMessage: '',
    });
    let pollTimer: number | undefined;
    let loadSequence = 0;

    const isViewMode = computed(() => editor.bsState.query.type === 'readOnly');
    const currentDataId = computed(() => editor.getCurrentFrame()?.id || '');
    const currentSceneId = computed(() => editor.bsState.seriesFrameId || '');

    onMounted(async () => {
        await Promise.all([loadTag(), loadCounts()]);
    });
    onBeforeUnmount(() => window.clearTimeout(pollTimer));
    watch(currentDataId, loadTag);
    watch(currentSceneId, loadCounts);
    watch(() => state.scope, loadCounts);

    function tagLabel(tag: FrameTag) {
        return tagOptions.find((item) => item.value === tag)?.label || tag;
    }

    async function loadTag() {
        if (!isViewMode.value || !currentDataId.value) return;
        const sequence = ++loadSequence;
        state.loading = true;
        try {
            const result = await api.getFrameTag(currentDataId.value);
            if (sequence === loadSequence) state.tag = result.subType as FrameTag | undefined;
        } catch (error: any) {
            editor.handleErr(error);
        } finally {
            if (sequence === loadSequence) state.loading = false;
        }
    }

    async function selectTag(tag?: FrameTag) {
        if (!currentDataId.value || state.saving) return;
        state.saving = true;
        try {
            await api.saveFrameTag(currentDataId.value, editor.bsState.datasetId, tag);
            state.tag = tag;
            await loadCounts();
            editor.showMsg('success', tag ? `已标记：${tagLabel(tag)}` : '已清除帧标签');
        } catch (error: any) {
            editor.handleErr(error);
        } finally {
            state.saving = false;
        }
    }

    async function loadCounts() {
        if (!editor.bsState.datasetId) return;
        try {
            const sceneId = state.scope === 'scene' ? currentSceneId.value || undefined : undefined;
            state.counts = await api.getFrameTagCounts(editor.bsState.datasetId, sceneId);
        } catch (error: any) {
            editor.handleErr(error);
        }
    }

    async function startExport() {
        state.exporting = true;
        state.progress = 0;
        state.exportMessage = '正在创建导出任务…';
        try {
            const serialNumber = await api.exportTaggedFrames({
                datasetId: editor.bsState.datasetId,
                sceneId: state.scope === 'scene' ? currentSceneId.value || undefined : undefined,
                tags: [...state.exportTags],
            });
            if (!serialNumber) throw new Error('导出任务创建失败');
            pollExport(serialNumber);
        } catch (error: any) {
            state.exporting = false;
            state.exportMessage = error?.message || '导出失败';
            editor.handleErr(error);
        }
    }

    async function pollExport(serialNumber: string) {
        try {
            const record = await api.getExportRecord(serialNumber);
            const total = record.totalNum || 0;
            state.progress = total > 0 ? Math.min(99, Math.round(((record.generatedNum || 0) * 100) / total)) : 0;
            if (record.status === 'COMPLETED') {
                state.exporting = false;
                state.progress = 100;
                state.exportMessage = `导出完成：${record.fileName || ''}`;
                if (record.filePath) {
                    const link = document.createElement('a');
                    link.href = record.filePath;
                    link.download = record.fileName || 'selected-frames.zip';
                    link.rel = 'noopener';
                    document.body.appendChild(link);
                    link.click();
                    link.remove();
                }
                return;
            }
            if (record.status === 'FAILED') throw new Error('服务器生成导出文件失败');
            state.exportMessage = `正在导出 ${record.generatedNum || 0}/${record.totalNum || 0} 帧`;
            pollTimer = window.setTimeout(() => pollExport(serialNumber), 2000);
        } catch (error: any) {
            state.exporting = false;
            state.exportMessage = error?.message || '查询导出进度失败';
            editor.handleErr(error);
        }
    }
</script>

<style lang="less" scoped>
    .frame-tag-panel {
        padding: 12px 14px;
        border-bottom: 1px solid #2f3036;
        color: #d9d9df;
    }
    .panel-title,
    .export-title {
        margin-bottom: 8px;
        font-size: 15px;
        font-weight: 600;
    }
    .tag-list {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 6px;
    }
    button,
    select {
        border: 1px solid #4a4d57;
        background: #2a2c33;
        color: #e6e6ea;
    }
    button {
        cursor: pointer;
    }
    button:disabled {
        cursor: not-allowed;
        opacity: 0.55;
    }
    .tag-button {
        padding: 7px 4px;
    }
    .tag-button.active {
        border-color: #2f80ed;
        background: #2c4a80;
    }
    .tag-status {
        display: flex;
        min-height: 28px;
        align-items: center;
        justify-content: space-between;
        margin-top: 6px;
        color: #aeb3c2;
        font-size: 12px;
    }
    .clear {
        padding: 3px 10px;
    }
    .export-block {
        display: grid;
        gap: 7px;
        margin-top: 10px;
        padding-top: 10px;
        border-top: 1px solid #3b3d45;
    }
    .check-item {
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .scope-select,
    .export-button {
        width: 100%;
        padding: 7px;
    }
    .export-button {
        border-color: #2f80ed;
        background: #2468bd;
    }
    .export-message {
        color: #aeb3c2;
        font-size: 12px;
        word-break: break-all;
    }
</style>
