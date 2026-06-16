<template>
    <div class="occ-label-panel">
        <div
            v-show="brushPreview.visible"
            class="brush-preview"
            :style="{
                width: `${state.radius * 2}px`,
                height: `${state.radius * 2}px`,
                transform: `translate(${brushPreview.x - state.radius}px, ${brushPreview.y - state.radius}px)`,
            }"
        ></div>
        <div class="panel-title">OCC Labels</div>
        <div class="legend">
            <button
                v-for="item in labels"
                :key="item.value"
                :class="['legend-item', { active: state.label === item.value }]"
                @click="state.label = item.value"
            >
                <span class="swatch" :style="{ backgroundColor: item.color }"></span>
                <span class="label-id">{{ item.value }}</span>
                <span class="label-name">{{ item.name }}</span>
            </button>
        </div>
        <div class="brush-row">
            <label>Brush</label>
            <input v-model.number="state.radius" min="2" max="80" type="range" />
            <span>{{ state.radius }}px</span>
        </div>
        <div class="control-row">
            <label>Point Size</label>
            <input
                v-model.number="config.pointSize"
                min="0.01"
                max="0.4"
                step="0.01"
                type="range"
                @input="updatePointSize"
            />
            <span>{{ config.pointSize.toFixed(2) }}</span>
        </div>
        <div class="actions">
            <button :class="{ active: state.enabled }" @click="toggleBrush">
                {{ state.enabled ? 'Brush On' : 'Brush Off' }}
            </button>
            <button :disabled="undoStack.length === 0" @click="undoLastAction">Undo</button>
            <button @click="fillSelectedBox">Fill Box</button>
            <button @click="saveLabels">Save</button>
        </div>
        <div class="hint">Brush points, or select a 3D box and fill all points inside it.</div>
    </div>
</template>

<script setup lang="ts">
    import { reactive, onBeforeUnmount } from 'vue';
    import * as THREE from 'three';
    import { Box, PointsMaterial } from 'pc-render';
    import { useInjectEditor } from '../../../state';
    import { buildPointLabelColors } from '../../../packages/pc-render/occ/pointLabel';
    import * as api from '../../../api';

    const labels = [
        { value: 0, name: 'unlabeled', color: '#ffffff' },
        { value: 1, name: 'freespace', color: '#808080' },
        { value: 2, name: 'noise', color: '#00ff00' },
        { value: 3, name: 'movable', color: '#0000ff' },
        { value: 4, name: 'stationary', color: '#ffff00' },
        { value: 5, name: 'passable', color: '#00ffff' },
        { value: 6, name: 'unfree', color: '#ff0000' },
    ];

    const colorMap = labels.reduce((map, item) => {
        map[item.value] = item.color;
        return map;
    }, {} as Record<number, string>);

    const editor = useInjectEditor();
    const config = editor.state.config;
    const state = reactive({
        enabled: false,
        painting: false,
        label: 6,
        radius: 12,
    });
    const brushPreview = reactive({
        visible: false,
        x: 0,
        y: 0,
    });
    const screenPos = new THREE.Vector3();
    const boxPoint = new THREE.Vector3();
    const boxInvertMatrix = new THREE.Matrix4();
    const dirtyPointIndices = new Set<number>();
    const undoStack = reactive<{ indices: number[]; labels: number[] }[]>([]);
    let activeUndo: Map<number, number> | undefined;
    let dirtyMergeVersion = -1;

    function getMainCanvas() {
        const view = editor.viewManager.getMainView();
        return view?.renderer?.domElement as HTMLCanvasElement | undefined;
    }

    function getPoints() {
        return editor.pc.groupPoints.children[0] as THREE.Points | undefined;
    }

    function toggleBrush() {
        state.enabled = !state.enabled;
        const canvas = getMainCanvas();
        if (!canvas) return;
        if (state.enabled) {
            attach(canvas);
        } else {
            detach(canvas);
        }
    }

    function attach(canvas: HTMLCanvasElement) {
        canvas.addEventListener('pointerdown', onPointerDown, true);
        canvas.addEventListener('pointermove', onPointerMove, true);
        canvas.addEventListener('pointerup', onPointerUp, true);
        canvas.addEventListener('pointercancel', onPointerUp, true);
        canvas.addEventListener('pointerleave', onPointerLeave, true);
        canvas.style.cursor = 'crosshair';
    }

    function detach(canvas: HTMLCanvasElement) {
        canvas.removeEventListener('pointerdown', onPointerDown, true);
        canvas.removeEventListener('pointermove', onPointerMove, true);
        canvas.removeEventListener('pointerup', onPointerUp, true);
        canvas.removeEventListener('pointercancel', onPointerUp, true);
        canvas.removeEventListener('pointerleave', onPointerLeave, true);
        canvas.style.cursor = '';
        state.painting = false;
        brushPreview.visible = false;
        finishUndoAction();
    }

    function onPointerDown(event: PointerEvent) {
        if (!state.enabled) return;
        event.preventDefault();
        event.stopPropagation();
        updateBrushPreview(event);
        state.painting = true;
        activeUndo = new Map();
        paint(event);
    }

    function onPointerMove(event: PointerEvent) {
        if (!state.enabled) return;
        event.preventDefault();
        event.stopPropagation();
        updateBrushPreview(event);
        if (!state.painting) return;
        paint(event);
    }

    function onPointerUp(event: PointerEvent) {
        if (!state.enabled) return;
        event.preventDefault();
        event.stopPropagation();
        updateBrushPreview(event);
        state.painting = false;
        finishUndoAction();
    }

    function onPointerLeave(event: PointerEvent) {
        if (!state.enabled) return;
        event.preventDefault();
        event.stopPropagation();
        brushPreview.visible = false;
        state.painting = false;
        finishUndoAction();
    }

    function updateBrushPreview(event: PointerEvent) {
        brushPreview.visible = state.enabled;
        brushPreview.x = event.clientX;
        brushPreview.y = event.clientY;
    }

    function paint(event: PointerEvent) {
        const view = editor.viewManager.getMainView();
        const points = getPoints();
        if (!view || !points) return;
        const labels = editor.pc.exportPointLabels();
        const position = points.geometry.getAttribute('position') as THREE.BufferAttribute;
        if (!labels || !position || labels.length !== position.count) return;

        const rect = view.renderer.domElement.getBoundingClientRect();
        const px = event.clientX - rect.left;
        const py = event.clientY - rect.top;
        const radius2 = state.radius * state.radius;
        const indices: number[] = [];

        for (let index = 0; index < position.count; index++) {
            screenPos.fromBufferAttribute(position, index);
            screenPos.applyMatrix4(points.matrixWorld);
            screenPos.project(view.camera);
            if (screenPos.z < -1 || screenPos.z > 1) continue;
            const sx = ((screenPos.x + 1) / 2) * rect.width;
            const sy = ((-screenPos.y + 1) / 2) * rect.height;
            const dx = sx - px;
            const dy = sy - py;
            if (dx * dx + dy * dy <= radius2) indices.push(index);
        }

        if (indices.length > 0) {
            applyLabelIndices(indices, state.label);
        }
    }

    function applyLabelIndices(indices: number[], label: number) {
        const labels = editor.pc.exportPointLabels();
        if (!labels) return;
        const changed = indices.filter((index) => index >= 0 && index < labels.length && labels[index] !== label);
        if (changed.length === 0) return;
        recordUndo(changed, labels);
        editor.pc.setPointLabelByIndices(changed, label, colorMap);
        markDirtyIndices(changed);
    }

    function recordUndo(indices: number[], labels: Uint8Array) {
        if (!activeUndo) activeUndo = new Map();
        indices.forEach((index) => {
            if (!activeUndo?.has(index)) activeUndo?.set(index, labels[index]);
        });
    }

    function finishUndoAction() {
        if (!activeUndo || activeUndo.size === 0) {
            activeUndo = undefined;
            return;
        }
        undoStack.push({
            indices: [...activeUndo.keys()],
            labels: [...activeUndo.values()],
        });
        if (undoStack.length > 20) undoStack.shift();
        activeUndo = undefined;
    }

    function undoLastAction() {
        finishUndoAction();
        const action = undoStack.pop();
        const labels = editor.pc.exportPointLabels();
        if (!action || !labels) return;
        action.indices.forEach((pointIndex, index) => {
            if (pointIndex >= 0 && pointIndex < labels.length) {
                labels[pointIndex] = action.labels[index];
            }
        });
        editor.pc.setPointLabels(labels, colorMap);
        markDirtyIndices(action.indices);
    }

    function updatePointSize() {
        const points = getPoints();
        const material = points?.material as PointsMaterial | undefined;
        if (!material) return;
        material.setUniforms({ pointSize: config.pointSize * 10 });
        editor.pc.render();
    }

    function getSelectedBox() {
        return editor.pc.selection.find((item) => item instanceof Box) as Box | undefined;
    }

    function getPointIndicesInBox(box: Box) {
        const points = getPoints();
        if (!points) return [];

        const position = points.geometry.getAttribute('position') as THREE.BufferAttribute;
        if (!position) return [];

        box.updateMatrixWorld();
        if (!box.geometry.boundingBox) box.geometry.computeBoundingBox();
        const bounds = box.geometry.boundingBox;
        if (!bounds) return [];

        boxInvertMatrix.copy(box.matrixWorld).invert();
        const indices: number[] = [];
        for (let index = 0; index < position.count; index++) {
            boxPoint.fromBufferAttribute(position, index).applyMatrix4(boxInvertMatrix);
            if (bounds.containsPoint(boxPoint)) indices.push(index);
        }
        return indices;
    }

    function fillSelectedBox() {
        const labels = editor.pc.exportPointLabels();
        if (!labels) {
            editor.showMsg('warning', 'No OCC labels loaded');
            return;
        }

        const box = getSelectedBox();
        if (!box) {
            editor.showMsg('warning', 'Select a 3D box first');
            return;
        }

        const indices = getPointIndicesInBox(box);
        if (indices.length === 0) {
            editor.showMsg('warning', 'No points inside selected box');
            return;
        }

        activeUndo = new Map();
        applyLabelIndices(indices, state.label);
        finishUndoAction();
        editor.showMsg('success', `Relabeled ${indices.length} points`);
    }

    async function saveLabels() {
        const frame = editor.getCurrentFrame();
        if (!frame) {
            editor.showMsg('warning', 'No OCC labels loaded');
            return;
        }
        editor.showLoading({
            type: 'loading',
            content: 'Preparing OCC labels...',
        });
        await nextFrame();

        try {
            if (editor.multiFrameMergeManager.active) {
                await saveMergedLabels();
                return;
            }
            const labels = editor.pc.exportPointLabels();
            if (!labels) {
                editor.showMsg('warning', 'No OCC labels loaded');
                return;
            }
            await api.modifyPointLabels(frame.id, labels, frame.id);
            updateFrameResourceLabels(frame.id, labels);
            dirtyPointIndices.clear();
            undoStack.splice(0, undoStack.length);
            editor.showMsg('success', 'OCC labels saved');
        } catch (error) {
            console.error(error);
            editor.showMsg('error', 'OCC label save failed');
        } finally {
            editor.showLoading(false);
        }
    }

    async function saveMergedLabels() {
        const sources = editor.multiFrameMergeManager.mergedSources;
        const mergedLabels = editor.pc.getPointLabels();
        if (!sources.length || !mergedLabels || sources.length !== mergedLabels.length) {
            editor.showMsg('warning', 'Merged OCC labels are not aligned with source frames');
            return;
        }

        if (dirtyPointIndices.size > 0 && dirtyMergeVersion !== editor.multiFrameMergeManager.version) {
            dirtyPointIndices.clear();
        }

        const patches = new Map<string, { indices: number[]; labels: number[]; pointCount: number }>();
        const dirtyIndices = await getDirtyMergedIndices(mergedLabels, sources.length);
        if (dirtyIndices.length === 0) {
            editor.showMsg('warning', 'No OCC label changes to save');
            return;
        }
        const chunkSize = 50000;
        for (let dirtyIndex = 0; dirtyIndex < dirtyIndices.length; dirtyIndex++) {
            const mergedIndex = dirtyIndices[dirtyIndex];
            const source = sources[mergedIndex];
            if (!source) continue;

            let patch = patches.get(source.frameId);
            if (!patch) {
                patch = {
                    indices: [],
                    labels: [],
                    pointCount: getFramePointCount(source.frameId),
                };
                patches.set(source.frameId, patch);
            }
            patch.indices.push(source.pointIndex);
            patch.labels.push(mergedLabels[mergedIndex]);

            if (dirtyIndex % chunkSize === 0) {
                editor.showLoading({
                    type: 'loading',
                    content: `Preparing OCC patch ${Math.round((dirtyIndex / dirtyIndices.length) * 100)}%...`,
                });
                await nextFrame();
            }
        }

        if (patches.size === 0) {
            editor.showMsg('warning', 'No source frame labels to save');
            return;
        }

        const entries = [...patches.entries()];
        for (let index = 0; index < entries.length; index++) {
            const [frameId, patch] = entries[index];
            editor.showLoading({
                type: 'loading',
                content: `Saving OCC labels ${index + 1}/${entries.length}...`,
            });
            await api.patchPointLabels(
                frameId,
                patch.indices,
                new Uint8Array(patch.labels),
                patch.pointCount,
            );
            updateFrameResourcePatch(frameId, patch.indices, patch.labels);
            await new Promise((resolve) => window.setTimeout(resolve, 0));
        }
        dirtyPointIndices.clear();
        undoStack.splice(0, undoStack.length);
        editor.multiFrameMergeManager.mergedBaseLabels = new Uint8Array(mergedLabels);
        editor.showMsg('success', `OCC label changes saved to ${patches.size} frames`);
    }

    async function getDirtyMergedIndices(mergedLabels: Uint8Array, pointCount: number) {
        if (dirtyPointIndices.size > 0) {
            return [...dirtyPointIndices].filter((index) => index >= 0 && index < pointCount);
        }

        const baseLabels = editor.multiFrameMergeManager.mergedBaseLabels;
        if (!baseLabels || baseLabels.length !== mergedLabels.length) {
            return Array.from({ length: pointCount }, (_item, index) => index);
        }

        const changed: number[] = [];
        const chunkSize = 200000;
        for (let index = 0; index < mergedLabels.length; index++) {
            if (mergedLabels[index] !== baseLabels[index]) changed.push(index);
            if (index % chunkSize === 0) {
                editor.showLoading({
                    type: 'loading',
                    content: `Checking OCC changes ${Math.round((index / mergedLabels.length) * 100)}%...`,
                });
                await nextFrame();
            }
        }
        return changed;
    }

    function getFramePointCount(frameId: string) {
        const resource = editor.dataResource.dataMap[frameId];
        const pointsData = resource?.pointsData as any;
        const position = pointsData?.position as Float32Array | undefined;
        const labels = pointsData?.pointLabels as Uint8Array | undefined;
        return labels?.length || (position ? position.length / 3 : 0);
    }

    function updateFrameResourcePatch(frameId: string, indices: number[], patchLabels: number[]) {
        const resource = editor.dataResource.dataMap[frameId];
        if (!resource?.pointsData) return;
        const pointsData = resource.pointsData as any;
        const pointCount = getFramePointCount(frameId);
        const labels = pointsData.pointLabels?.length
            ? new Uint8Array(pointsData.pointLabels)
            : new Uint8Array(pointCount);
        indices.forEach((pointIndex, index) => {
            if (pointIndex >= 0 && pointIndex < labels.length) {
                labels[pointIndex] = patchLabels[index];
            }
        });
        pointsData.pointLabels = labels;
        pointsData.color = buildPointLabelColors(labels, colorMap);
        resource.savedPointLabels = new Uint8Array(labels);
    }

    function updateFrameResourceLabels(frameId: string, labels: Uint8Array) {
        const resource = editor.dataResource.dataMap[frameId];
        if (!resource?.pointsData) return;
        const pointsData = resource.pointsData as any;
        const position = pointsData.position as Float32Array | undefined;
        const pointCount = position ? position.length / 3 : labels.length;
        if (labels.length !== pointCount) {
            console.warn(`saved point labels length ${labels.length} does not match point count ${pointCount}`);
            return;
        }
        pointsData.pointLabels = new Uint8Array(labels);
        pointsData.color = buildPointLabelColors(labels, colorMap);
        resource.savedPointLabels = new Uint8Array(labels);
    }

    function markDirtyIndices(indices: number[]) {
        if (editor.multiFrameMergeManager.active) {
            dirtyMergeVersion = editor.multiFrameMergeManager.version;
        }
        indices.forEach((index) => dirtyPointIndices.add(index));
    }

    function nextFrame() {
        return new Promise((resolve) => window.setTimeout(resolve, 0));
    }

    onBeforeUnmount(() => {
        const canvas = getMainCanvas();
        if (canvas) detach(canvas);
    });
</script>

<style lang="less" scoped>
    .occ-label-panel {
        padding: 10px 8px;
        border-bottom: 6px solid #2b2c31;
        color: #d7d9df;

        .panel-title {
            color: #b8bac2;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 8px;
        }

        .legend {
            display: grid;
            gap: 4px;
        }

        .legend-item {
            display: grid;
            grid-template-columns: 14px 18px 1fr;
            align-items: center;
            gap: 6px;
            min-height: 26px;
            border: 1px solid #3f424a;
            background: #22242a;
            color: #d7d9df;
            text-align: left;
            cursor: pointer;
        }

        .legend-item.active {
            border-color: #4f8cff;
            background: #2d3d5f;
        }

        .swatch {
            width: 12px;
            height: 12px;
            border: 1px solid rgba(0, 0, 0, 0.45);
        }

        .label-id {
            color: #aeb4c2;
            font-variant-numeric: tabular-nums;
        }

        .brush-row,
        .control-row {
            display: grid;
            grid-template-columns: 64px 1fr 44px;
            align-items: center;
            gap: 6px;
            margin-top: 10px;
            font-size: 12px;
        }

        .actions {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr 1fr;
            gap: 6px;
            margin-top: 10px;
        }

        .actions button {
            min-height: 28px;
            border: 1px solid #4b4f58;
            background: #30323a;
            color: #f3f4f6;
            cursor: pointer;
        }

        .actions button.active {
            border-color: #40a9ff;
            background: #155996;
        }

        .actions button:disabled {
            opacity: 0.45;
            cursor: not-allowed;
        }

        .hint {
            margin-top: 8px;
            color: #8f949f;
            font-size: 11px;
            line-height: 16px;
        }
    }

    .brush-preview {
        position: fixed;
        left: 0;
        top: 0;
        z-index: 10000;
        pointer-events: none;
        border: 1px dashed rgba(255, 255, 255, 0.95);
        border-radius: 50%;
        box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.45);
        will-change: transform, width, height;
    }
</style>
