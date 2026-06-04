<template>
    <div class="occ-label-panel">
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
        <div class="actions">
            <button :class="{ active: state.enabled }" @click="toggleBrush">
                {{ state.enabled ? 'Brush On' : 'Brush Off' }}
            </button>
            <button @click="saveLabels">Save</button>
        </div>
        <div class="hint">Press and drag in the point cloud view to relabel points.</div>
    </div>
</template>

<script setup lang="ts">
    import { reactive, onBeforeUnmount } from 'vue';
    import * as THREE from 'three';
    import { useInjectEditor } from '../../../state';
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
    const state = reactive({
        enabled: false,
        painting: false,
        label: 6,
        radius: 12,
    });
    const screenPos = new THREE.Vector3();

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
        canvas.addEventListener('pointerleave', onPointerUp, true);
        canvas.style.cursor = 'crosshair';
    }

    function detach(canvas: HTMLCanvasElement) {
        canvas.removeEventListener('pointerdown', onPointerDown, true);
        canvas.removeEventListener('pointermove', onPointerMove, true);
        canvas.removeEventListener('pointerup', onPointerUp, true);
        canvas.removeEventListener('pointerleave', onPointerUp, true);
        canvas.style.cursor = '';
        state.painting = false;
    }

    function onPointerDown(event: PointerEvent) {
        if (!state.enabled) return;
        event.preventDefault();
        event.stopPropagation();
        state.painting = true;
        paint(event);
    }

    function onPointerMove(event: PointerEvent) {
        if (!state.enabled || !state.painting) return;
        event.preventDefault();
        event.stopPropagation();
        paint(event);
    }

    function onPointerUp(event: PointerEvent) {
        if (!state.enabled) return;
        event.preventDefault();
        event.stopPropagation();
        state.painting = false;
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
            editor.pc.setPointLabelByIndices(indices, state.label, colorMap);
        }
    }

    async function saveLabels() {
        const frame = editor.getCurrentFrame();
        const labels = editor.pc.exportPointLabels();
        if (!frame || !labels) {
            editor.showMsg('warning', 'No OCC labels loaded');
            return;
        }
        try {
            await api.modifyPointLabels(frame.id, labels, frame.id);
            editor.showMsg('success', 'OCC labels saved');
        } catch (error) {
            console.error(error);
            editor.showMsg('error', 'OCC label save failed');
        }
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

        .brush-row {
            display: grid;
            grid-template-columns: 42px 1fr 44px;
            align-items: center;
            gap: 6px;
            margin-top: 10px;
            font-size: 12px;
        }

        .actions {
            display: grid;
            grid-template-columns: 1fr 1fr;
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

        .hint {
            margin-top: 8px;
            color: #8f949f;
            font-size: 11px;
            line-height: 16px;
        }
    }
</style>
