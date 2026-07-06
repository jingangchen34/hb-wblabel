<template>
    <div class="main-view-setting">
        <div class="item">
            <label>{{ $$('height-range') }}:</label>
        </div>
        <div class="item">
            <a-input-number
                v-model:value="config.heightRange[0]"
                size="small"
                @change="update"
                @blur="onBlur"
                :formatter="formatter"
                :min="config.pointInfo.min.z"
                :max="config.heightRange[1] || config.pointInfo.max.z"
                :step="0.1"
                style="width: 60px"
            ></a-input-number>
            <span>~</span>
            <a-input-number
                v-model:value="config.heightRange[1]"
                size="small"
                @change="update"
                @blur="onBlur"
                :formatter="formatter"
                :min="config.heightRange[0] || config.pointInfo.min.z"
                :max="config.pointInfo.max.z"
                :step="0.1"
                style="width: 60px"
            ></a-input-number>
            <a-button
                :title="$$('reset')"
                size="small"
                style="border: none; float: right"
                @click="onReset"
            >
                <template #icon>
                    <RetweetOutlined />
                </template>
            </a-button>
        </div>
        <div v-if="currentPointRange" class="point-range-block">
            <div class="point-range-title">{{ mergeActive ? 'Frame' : 'Point cloud' }}</div>
            <div>X {{ formatRange(currentPointRange.xMin, currentPointRange.xMax) }}</div>
            <div>Y {{ formatRange(currentPointRange.yMin, currentPointRange.yMax) }}</div>
            <div>Z {{ formatRange(currentPointRange.zMin, currentPointRange.zMax) }}</div>
            <div class="point-range-count">Points {{ formatCount(currentPointRange.count) }}</div>
        </div>
        <div v-if="mergeActive && mergedPointRange" class="point-range-block merged">
            <div class="point-range-title">Merged</div>
            <div>X {{ formatRange(mergedPointRange.xMin, mergedPointRange.xMax) }}</div>
            <div>Y {{ formatRange(mergedPointRange.yMin, mergedPointRange.yMax) }}</div>
            <div>Z {{ formatRange(mergedPointRange.zMin, mergedPointRange.zMax) }}</div>
            <div class="point-range-count">Points {{ formatCount(mergedPointRange.count) }}</div>
        </div>
        <!-- <div class="toggle-btn">
            <a-button style="width: 100%" size="small" @click="onVisible">
                <template #icon>
                    <UpOutlined v-if="visible" />
                    <DownOutlined v-else />
                </template>
            </a-button>
        </div> -->
    </div>
</template>
<script lang="ts" setup>
    import { reactive, ref, computed } from 'vue';
    import { RetweetOutlined, UpOutlined, DownOutlined } from '@ant-design/icons-vue';
    import { PointsMaterial } from 'pc-render';
    import { useInjectEditor } from '../../state';
    import * as THREE from 'three';
    import * as _ from 'lodash';
    import * as locale from './lang';
    import { utils } from 'pc-editor';
    const editor = useInjectEditor();
    const $$ = editor.bindLocale(locale);
    const config = editor.state.config;
    interface PointRange {
        xMin: number;
        xMax: number;
        yMin: number;
        yMax: number;
        zMin: number;
        zMax: number;
        count: number;
    }

    const pointRangeCache = new WeakMap<object, PointRange>();
    const mergeActive = computed(() => !!(editor.state as any).mergeActive);
    const mergedPointRange = computed(() => {
        if (!mergeActive.value) return null;
        return pointInfoToRange();
    });
    const currentPointRange = computed(() => {
        if (!mergeActive.value) return pointInfoToRange();
        const frame = editor.getCurrentFrame();
        const resource = frame ? editor.dataResource.dataMap[frame.id] : undefined;
        const position = resource?.pointsData?.position as ArrayLike<number> | undefined;
        return getPointRange(position) || pointInfoToRange();
    });
    function formatter(value: any) {
        let n = ('' + value).split('.');
        if (n[1] && n[1].length > 1) {
            return Number(value).toFixed(1);
        } else {
            return value;
        }
    }
    function verify() {
        const heightRange = config.heightRange;
        if (!heightRange[0]) {
            heightRange[0] = 0.0;
        }
        if (!heightRange[1]) {
            heightRange[1] = config.pointInfo.max.z;
        }
    }
    function onBlur() {
        verify();
        update();
    }
    function onReset() {
        config.heightRange[0] = config.pointInfo.min.z;
        config.heightRange[1] = config.pointInfo.max.z;
        update();
    }
    const update = _.debounce(() => {
        const heightRange = config.heightRange;
        if (isNaN(heightRange[0]) || isNaN(heightRange[1])) return;
        let points = editor.pc.groupPoints.children[0] as THREE.Points;
        let material = points.material as PointsMaterial;
        let option = {} as any;
        option.heightRange = new THREE.Vector2().fromArray(heightRange);
        material.setUniforms(option);
        editor.pc.render();
    }, 300);
    function pointInfoToRange(): PointRange | null {
        const { pointInfo } = config;
        if (!pointInfo || !Number.isFinite(pointInfo.count) || pointInfo.count <= 0) return null;
        return {
            xMin: pointInfo.min.x,
            xMax: pointInfo.max.x,
            yMin: pointInfo.min.y,
            yMax: pointInfo.max.y,
            zMin: pointInfo.min.z,
            zMax: pointInfo.max.z,
            count: pointInfo.count,
        };
    }

    function getPointRange(position?: ArrayLike<number>): PointRange | null {
        if (!position || position.length < 3) return null;
        if (typeof position === 'object') {
            const cached = pointRangeCache.get(position as object);
            if (cached) return cached;
        }
        let xMin = Infinity;
        let xMax = -Infinity;
        let yMin = Infinity;
        let yMax = -Infinity;
        let zMin = Infinity;
        let zMax = -Infinity;
        let count = 0;
        for (let index = 0; index + 2 < position.length; index += 3) {
            const x = position[index];
            const y = position[index + 1];
            const z = position[index + 2];
            if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) continue;
            xMin = Math.min(xMin, x);
            xMax = Math.max(xMax, x);
            yMin = Math.min(yMin, y);
            yMax = Math.max(yMax, y);
            zMin = Math.min(zMin, z);
            zMax = Math.max(zMax, z);
            count++;
        }
        if (count === 0) return null;
        const range = { xMin, xMax, yMin, yMax, zMin, zMax, count };
        if (typeof position === 'object') pointRangeCache.set(position as object, range);
        return range;
    }

    function formatRange(min: number, max: number) {
        return `${formatValue(min)} ~ ${formatValue(max)}`;
    }

    function formatValue(value: number) {
        if (!Number.isFinite(value)) return '--';
        return Number(value).toFixed(2);
    }

    function formatCount(value: number) {
        if (!Number.isFinite(value)) return '0';
        return Math.round(value).toLocaleString();
    }
</script>
<style lang="less">
    .main-view-setting {
        // text-align: left;
        pointer-events: all;
        > .item {
            clear: both;
            margin-bottom: 4px;
            > label {
                margin-right: 10px;
            }
        }
        .point-range-block {
            width: 196px;
            margin: 6px 0;
            padding: 6px 8px;
            border: 1px solid rgba(255, 255, 255, 0.16);
            border-radius: 4px;
            background: rgba(0, 0, 0, 0.32);
            color: rgba(255, 255, 255, 0.78);
            font-family: Consolas, 'Courier New', monospace;
            font-size: 12px;
            line-height: 18px;

            &.merged {
                border-color: rgba(46, 140, 240, 0.45);
                background: rgba(46, 140, 240, 0.12);
            }
        }

        .point-range-title {
            margin-bottom: 2px;
            color: rgba(255, 255, 255, 0.92);
            font-family: inherit;
            font-weight: 600;
        }

        .point-range-count {
            margin-top: 2px;
            color: rgba(255, 255, 255, 0.58);
        }
    }
</style>
