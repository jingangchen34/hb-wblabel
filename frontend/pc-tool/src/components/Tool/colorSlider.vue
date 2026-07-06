<template>
    <div
        v-if="[ColorModeEnum.HEIGHT].includes(config.pointColorMode)"
        class="title3"
        style="padding: 6px 0 0 14px"
        >{{ $$('setting_colorheight') }}
        <a-button
            :title="$$('setting_pointreset')"
            size="small"
            style="border: none; float: right"
            @click="onResetHeight"
        >
            <template #icon>
                <RetweetOutlined />
            </template>
        </a-button>

        <a-input-number
            v-model:value="config.pointHeight[1]"
            size="small"
            :step="0.1"
            :formatter="formatter"
            @blur="onBlur"
            @change="() => updateHeight(false)"
            :min="config.pointHeight[0] || config.pointInfo.min.z"
            :max="config.pointInfo.max.z"
            style="float: right; width: 60px"
        ></a-input-number>
        <a-input-number
            v-model:value="config.pointHeight[0]"
            size="small"
            :step="0.1"
            :formatter="formatter"
            @change="() => updateHeight(false)"
            @blur="onBlur"
            :min="config.pointInfo.min.z"
            :max="config.pointHeight[1] || config.pointInfo.max.z"
            style="float: right; width: 60px"
        ></a-input-number>
    </div>
    <div v-if="currentPointRange" class="point-range-panel">
        <div class="point-range-title">{{ mergeActive ? 'Current frame' : 'Point cloud' }}</div>
        <div class="point-range-grid">
            <span>X</span>
            <span>{{ formatRange(currentPointRange.xMin, currentPointRange.xMax) }}</span>
            <span>Y</span>
            <span>{{ formatRange(currentPointRange.yMin, currentPointRange.yMax) }}</span>
            <span>Z</span>
            <span>{{ formatRange(currentPointRange.zMin, currentPointRange.zMax) }}</span>
        </div>
        <div class="point-range-count">Points {{ formatCount(currentPointRange.count) }}</div>
    </div>
    <div v-if="mergeActive && mergedPointRange" class="point-range-panel merged">
        <div class="point-range-title">Merged frames</div>
        <div class="point-range-grid">
            <span>X</span>
            <span>{{ formatRange(mergedPointRange.xMin, mergedPointRange.xMax) }}</span>
            <span>Y</span>
            <span>{{ formatRange(mergedPointRange.yMin, mergedPointRange.yMax) }}</span>
            <span>Z</span>
            <span>{{ formatRange(mergedPointRange.zMin, mergedPointRange.zMax) }}</span>
        </div>
        <div class="point-range-count">Points {{ formatCount(mergedPointRange.count) }}</div>
    </div>
    <div
        v-if="[ColorModeEnum.VELOCITY].includes(config.pointColorMode)"
        class="title3"
        style="padding-top: 6px"
        >{{ $$('setting_colorvelocity') }}
        <a-button
            :title="$$('setting_pointreset')"
            size="small"
            style="border: none; float: right"
            @click="onResetVelocity"
        >
            <template #icon>
                <RetweetOutlined />
            </template>
        </a-button>
        <a-input-number
            v-model:value="config.pointVelocity[1]"
            size="small"
            :step="0.1"
            :formatter="formatter"
            @blur="onBlur"
            @change="() => updateVelocity(false)"
            :min="config.pointVelocity[0] || config.pointInfo.vRange.x"
            :max="config.pointInfo.vRange.y"
            style="float: right; width: 60px"
        ></a-input-number>
        <a-input-number
            v-model:value="config.pointVelocity[0]"
            size="small"
            :step="0.1"
            :formatter="formatter"
            @change="() => updateVelocity(false)"
            @blur="onBlur"
            :min="config.pointInfo.vRange.x"
            :max="config.pointVelocity[1] || config.pointInfo.vRange.y"
            style="float: right; width: 60px"
        ></a-input-number>
    </div>
    <div class="color-item-container" v-show="config.pointColorMode === ColorModeEnum.HEIGHT">
        <a-tooltip trigger="click" placement="topLeft">
            <template #title>
                <color-picker
                    :isWidget="true"
                    pickerType="chrome"
                    useType="pure"
                    :disableAlpha="true"
                    :disableHistory="true"
                    v-model:pureColor="config.edgeColor[0]"
                    @pureColorChange="() => asyncUpdate('edgeColor')"
                ></color-picker>
            </template>
            <div class="color-span" :style="{ background: config.edgeColor[0] }"></div>
        </a-tooltip>
        <div :style="{ background: colorCodeBg() }" class="color-slider">
            <!-- <div class="color-slider-indicator" :style="{ left: range[0] + '%' }"></div>
              <div class="color-slider-indicator" :style="{ left: range[1] + '%' }"></div> -->
            <a-slider
                v-if="config.pointColorMode === ColorModeEnum.HEIGHT"
                style="margin: 0; width: 100%"
                :value="_pointHeight"
                range
                :min="round(config.pointInfo.min.z)"
                :max="round(config.pointInfo.max.z)"
                :step="0.1"
                :tipFormatter="tipFormatter"
                @change="onChangeHeight"
                @afterChange="() => updateHeight(true)"
            />
            <a-slider
                v-else-if="config.pointColorMode === ColorModeEnum.VELOCITY"
                style="margin: 0; width: 100%"
                :value="_pointVelocity"
                range
                :min="round(config.pointInfo.vRange.x)"
                :max="round(config.pointInfo.vRange.y)"
                :step="0.1"
                :tipFormatter="tipFormatter"
                @change="onChangeVelocity"
                @afterChange="() => updateVelocity(true)"
            />
        </div>
        <a-tooltip trigger="click" placement="topLeft">
            <template #title>
                <color-picker
                    :isWidget="true"
                    pickerType="chrome"
                    useType="pure"
                    :disableAlpha="true"
                    :disableHistory="true"
                    v-model:pureColor="config.edgeColor[1]"
                    @pureColorChange="() => asyncUpdate('edgeColor')"
                />
            </template>
            <div class="color-span" :style="{ background: config.edgeColor[1] }"></div>
        </a-tooltip>
    </div>
    <div class="color-item-container" v-show="config.pointColorMode === ColorModeEnum.PURE">
        <a-tooltip trigger="click" placement="topLeft">
            <template #title>
                <color-picker
                    :isWidget="true"
                    pickerType="chrome"
                    useType="pure"
                    :disableAlpha="true"
                    :disableHistory="true"
                    v-model:pureColor="config.singleColor"
                    @pureColorChange="() => asyncUpdate('singleColor')"
                />
            </template>
            <div class="color-span" :style="{ background: config.singleColor }"></div>
        </a-tooltip>
    </div>
    <div class="title3" style="margin-top: 10px; margin-bottom: 4px; height: 24px">
        <a-button type="dashed" class="reset" size="small" @click="onResetColor">{{
            $$('setting_colorreset')
        }}</a-button>
    </div>
</template>
<script lang="ts" setup>
    import { RetweetOutlined } from '@ant-design/icons-vue';
    import { computed } from 'vue';
    import { ColorModeEnum, utils } from 'pc-editor';
    import * as THREE from 'three';
    import { PointsMaterial } from 'pc-render';
    import * as _ from 'lodash';
    import { useInjectEditor } from '../../state';
    import * as locale from './lang';
    import { utils as renderUtils } from 'pc-render';

    const editor = useInjectEditor();
    const config = editor.state.config;
    let $$ = editor.bindLocale(locale);
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
    const colorCodeBg = () => {
        let color: string[];
        if (config.pointColorMode === ColorModeEnum.VELOCITY) {
            const vRange = config.pointInfo.vRange;
            const velocity = config.pointVelocity;
            const value0 = ((velocity[0] - vRange.x) / (vRange.y - vRange.x)) * 100;
            const value1 = ((velocity[1] - vRange.x) / (vRange.y - vRange.x)) * 100;

            color = [`${config.edgeColor[0]} 0%`, `${config.edgeColor[0]} ${value0}%`];
            color.push(`${config.edgeColor[1]} ${value1}%`, `${config.edgeColor[1]} 100%`);
        } else {
            const colors = renderUtils.getThemeColor(config.edgeColor);
            const pointInfo = config.pointInfo;
            const _min = pointInfo.min.z;
            const _max = pointInfo.max.z;
            const [min, max] = config.pointHeight;
            const mapLinear = (value: number) => {
                const height = THREE.MathUtils.mapLinear(value, 0, colors.length - 1, min, max);
                const ratio = THREE.MathUtils.mapLinear(height, _min, _max, 0, 100);
                return ratio;
            };
            color = [`${config.edgeColor[0]} 0%`, `${config.edgeColor[0]} ${mapLinear(0)}%`];
            colors.forEach((item, index) => {
                color.push(`${item} ${mapLinear(index)}%`);
            });
            color.push(
                `${config.edgeColor[1]} ${mapLinear(colors.length - 1)}%`,
                `${config.edgeColor[1]} 100%`,
            );
        }

        return `linear-gradient(90deg, ${color.join(',')})`;
    };

    const update = (type: 'pointHeight' | 'edgeColor' | 'singleColor' | 'pointVelocity') => {
        let points = editor.pc.groupPoints.children[0] as THREE.Points;
        let material = points.material as PointsMaterial;
        switch (type) {
            case 'edgeColor':
                material.setUniforms({
                    edgeColor: config.edgeColor,
                });
                break;
            case 'singleColor':
                material.setUniforms({
                    singleColor: config.singleColor,
                });
                break;
            case 'pointVelocity':
                material.setUniforms({
                    pointVelocity: new THREE.Vector2().fromArray(config.pointVelocity),
                });
                break;
            case 'pointHeight':
                material.setUniforms({
                    pointHeight: new THREE.Vector2().fromArray(config.pointHeight),
                });
                editor.pc.ground.plane.constant = config.pointHeight[0];
                editor.pc.groupTrack.position.z = config.pointHeight[0];
                break;
        }
        editor.pc.render();
    };
    const asyncUpdate = _.throttle(update, 100);
    const _pointHeight = computed(() => {
        return config.pointHeight.map((value) => {
            return THREE.MathUtils.clamp(
                value,
                round(config.pointInfo.min.z),
                round(config.pointInfo.max.z),
            );
        });
    });
    const _pointVelocity = computed(() => {
        return config.pointVelocity.map((value) => {
            return THREE.MathUtils.clamp(
                value,
                round(config.pointInfo.vRange.x),
                round(config.pointInfo.vRange.y),
            );
        });
    });
    function onChangeHeight(value: any) {
        config.pointHeight = value;
        updateHeight();
    }
    function onChangeVelocity(value: any) {
        config.pointVelocity = value;
        updateVelocity();
    }
    function updateHeight(force = false) {
        if (config.pointHeight.find((value) => isNaN(value) || utils.empty(value))) return;
        const frame = editor.getCurrentFrame();
        editor.dataResource.setGround(config.pointHeight[0], frame?.id);
        if (force) {
            update('pointHeight');
            update('edgeColor');
        } else {
            asyncUpdate('pointHeight');
            asyncUpdate('edgeColor');
        }
    }
    function updateVelocity(force = false) {
        if (config.pointVelocity.find((value) => isNaN(value) || utils.empty(value))) return;
        if (force) {
            update('pointVelocity');
            update('edgeColor');
        } else {
            asyncUpdate('pointVelocity');
            asyncUpdate('edgeColor');
        }
    }
    function tipFormatter(value: any) {
        return Number(value).toFixed(1);
    }
    function onResetHeight() {
        const { frameIndex, frames } = editor.state;
        const dataId = frames[frameIndex].id;
        const ground = editor.dataResource.dataMap[dataId].ground || 0;
        config.pointHeight = [ground, config.pointInfo.max.z];
        updateHeight();
    }
    function onResetVelocity() {
        config.pointVelocity = [0, 1];
        updateVelocity();
    }

    function formatter(value: any) {
        const n = ('' + value).split('.');
        if (n[1] && n[1].length > 1) {
            return Number(value).toFixed(1);
        } else {
            return value;
        }
    }
    function onBlur() {
        const pointHeight = config.pointHeight;
        if (isNaN(pointHeight[0]) || utils.empty(pointHeight[0])) {
            pointHeight[0] = config.pointInfo.min.z;
        }
        if (isNaN(pointHeight[1]) || utils.empty(pointHeight[1])) {
            pointHeight[1] = config.pointInfo.max.z;
        }
        updateHeight();
    }
    function onResetColor() {
        const mode = config.pointColorMode;
        if (mode === ColorModeEnum.PURE) {
            config.singleColor = '#87abff';
            asyncUpdate('singleColor');
        } else if ([ColorModeEnum.HEIGHT, ColorModeEnum.VELOCITY].includes(mode)) {
            config.edgeColor = ['#000dff', '#ff0000'];
            asyncUpdate('edgeColor');
        }
    }
    function round(value: any) {
        return Math.round(value * 10) / 10;
    }
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
    .point-range-panel {
        margin: 8px 0 6px 14px;
        padding: 8px 10px;
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 4px;
        background: rgba(255, 255, 255, 0.05);
        color: rgba(255, 255, 255, 0.78);
        font-size: 12px;
        line-height: 18px;

        &.merged {
            border-color: rgba(46, 140, 240, 0.35);
            background: rgba(46, 140, 240, 0.1);
        }

        .point-range-title {
            margin-bottom: 4px;
            color: rgba(255, 255, 255, 0.92);
            font-weight: 500;
        }

        .point-range-grid {
            display: grid;
            grid-template-columns: 18px 1fr;
            column-gap: 8px;
            row-gap: 2px;

            span:nth-child(odd) {
                color: rgba(255, 255, 255, 0.48);
            }

            span:nth-child(even) {
                font-family: Consolas, 'Courier New', monospace;
            }
        }

        .point-range-count {
            margin-top: 4px;
            color: rgba(255, 255, 255, 0.55);
            font-family: Consolas, 'Courier New', monospace;
        }
    }
    .color-item-container {
        display: flex;
        margin-top: 8px;
        align-items: center;
        min-height: 10px;
        flex-direction: row;

        .color-span {
            border: 1px solid white;
            width: 16px;
            height: 16px;
        }

        .color-slider {
            position: relative;
            margin: 0 8px;
            height: 10px;
            flex: 1;

            .color-slider-indicator {
                position: absolute;
                top: -4px;
                bottom: -4px;
                border-radius: 2px;
                width: 4px;
                background: white;
                cursor: pointer;
            }

            .ant-slider-track {
                background-color: transparent !important;
            }

            .ant-slider-rail {
                background-color: transparent !important;
            }
        }
    }
</style>
