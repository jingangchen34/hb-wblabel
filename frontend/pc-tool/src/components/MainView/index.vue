<template>
    <div class="main-view">
        <div ref="dom" style="height: 100%; width: 100%; position: relative"></div>
        <Labels :data="state.labels" v-show="editor.state.config.showLabel" />
        <Labels :data="state.predictionLabels" />
        <Labels :data="state.lineLabels" />
        <div v-if="editor.state.config.activePointMeasure" class="point-measure-panel">
            <div class="point-measure-header">
                <span>点云测量</span>
                <span>
                    <button @click.stop="clearMeasurement">清除</button>
                    <button @click.stop="closeMeasurement">退出</button>
                </span>
            </div>
            <div class="point-measure-modes">
                <button
                    :class="{ active: measurementMode === 'point' }"
                    @click.stop="setMeasurementMode('point')"
                >
                    {{ tool$$('point_measure_point_mode') }}
                </button>
                <button
                    :class="{ active: measurementMode === 'distance' }"
                    @click.stop="setMeasurementMode('distance')"
                >
                    {{ tool$$('point_measure_distance_mode') }}
                </button>
            </div>
            <div class="point-measure-hint">
                {{
                    measurementMode === 'point'
                        ? '单击点云读取该点坐标；右键或 Esc 清除'
                        : '依次单击两个点进行连线测量；右键或 Esc 清除'
                }}
            </div>
            <div v-if="measurementPoints.length > 0">
                P1: X {{ formatValue(measurementPoints[0].x) }},
                Y {{ formatValue(measurementPoints[0].y) }},
                Z {{ formatValue(measurementPoints[0].z) }}
            </div>
            <div v-if="measurementMode === 'distance' && measurementPoints.length > 1">
                P2: X {{ formatValue(measurementPoints[1].x) }},
                Y {{ formatValue(measurementPoints[1].y) }},
                Z {{ formatValue(measurementPoints[1].z) }}
            </div>
            <div v-if="measurementMode === 'distance' && measurementResult" class="point-measure-result">
                <b>距离 {{ formatValue(measurementResult.distance) }} m</b>
                <span>Δx {{ formatSigned(measurementResult.dx) }} m</span>
                <span>Δy {{ formatSigned(measurementResult.dy) }} m</span>
                <span>Δz {{ formatSigned(measurementResult.dz) }} m</span>
            </div>
        </div>
        <div class="point-measure-labels">
            <div
                v-for="item in state.measurementLabels"
                :key="item.key"
                :class="['point-measure-label', item.type]"
                :style="{ transform: `translate(${item.x}px, ${item.y}px)` }"
            >
                {{ item.name }}
            </div>
        </div>
        <!-- <Annotation :data="state.annotations" v-show="editor.state.config.showAnnotation" /> -->
        <slot name="info" v-if="$slots.info"></slot>
        <Info v-else />
        <Image2DMax />
        <slot name="editClass" v-if="$slots.editClass"></slot>
    </div>
</template>

<script setup lang="ts">
    import { onMounted, onBeforeUnmount, ref, reactive, computed, watch } from 'vue';
    import { MainRenderView, Event } from 'pc-render';
    import { useInjectEditor } from '../../state';
    import * as _ from 'lodash';
    import * as THREE from 'three';

    import Labels from './Labels.vue';
    import Annotation from './Annotation.vue';
    import Info from './Info.vue';
    import Image2DMax from '../ImgView/Image2DMax.vue';
    import * as toolLocale from '../Tool/lang';

    import { IUserData, IClassType, SourceType } from 'pc-editor';

    interface ILabel {
        name: string;
        x: number;
        y: number;
        scale: number;
    }

    interface IMeasurementLabel extends ILabel {
        key: string;
        type: 'point' | 'distance';
    }

    let dom = ref<HTMLDivElement | null>(null);
    let editor = useInjectEditor();
    let tool$$ = editor.bindLocale(toolLocale);
    let pc = editor.pc;
    let view = {} as MainRenderView;
    let state = reactive({
        labels: [] as ILabel[],
        predictionLabels: [] as ILabel[],
        lineLabels: [] as ILabel[],
        measurementLabels: [] as IMeasurementLabel[],
        annotations: [] as any[],
    });
    const measurementPoints = reactive<THREE.Vector3[]>([]);
    const measurementMode = ref<'point' | 'distance'>('point');
    const measurementGroup = new THREE.Group();
    const measurementRaycaster = new THREE.Raycaster();
    const measurementMouseDown = new THREE.Vector2();
    let measurementClickValid = false;

    const measurementResult = computed(() => {
        if (measurementPoints.length < 2) return null;
        const start = measurementPoints[0];
        const end = measurementPoints[1];
        return {
            dx: end.x - start.x,
            dy: end.y - start.y,
            dz: end.z - start.z,
            distance: start.distanceTo(end),
        };
    });

    function formatValue(value: number) {
        return Number(value).toFixed(3);
    }

    function formatSigned(value: number) {
        const formatted = formatValue(value);
        return value > 0 ? `+${formatted}` : formatted;
    }

    function disposeMeasurementObject(object: THREE.Object3D) {
        const mesh = object as THREE.Mesh;
        mesh.geometry?.dispose();
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(material)) material.forEach((item) => item.dispose());
        else material?.dispose();
    }

    function clearMeasurement() {
        measurementPoints.splice(0, measurementPoints.length);
        measurementGroup.children.slice().forEach((object) => {
            measurementGroup.remove(object);
            disposeMeasurementObject(object);
        });
        state.measurementLabels = [];
        pc.render();
    }

    function closeMeasurement() {
        editor.state.config.activePointMeasure = false;
    }

    function setMeasurementMode(mode: 'point' | 'distance') {
        if (measurementMode.value === mode) return;
        measurementMode.value = mode;
        clearMeasurement();
    }

    function createMeasurementMarker(position: THREE.Vector3) {
        const marker = new THREE.Points(
            new THREE.BufferGeometry().setFromPoints([position]),
            new THREE.PointsMaterial({
                color: 0xff3030,
                size: 3,
                sizeAttenuation: false,
                depthTest: false,
                depthWrite: false,
            }),
        );
        marker.renderOrder = 1000;
        measurementGroup.add(marker);
    }

    function refreshMeasurementObjects() {
        measurementGroup.children.slice().forEach((object) => {
            measurementGroup.remove(object);
            disposeMeasurementObject(object);
        });
        measurementPoints.forEach((point) => createMeasurementMarker(point));
        if (measurementMode.value === 'distance' && measurementPoints.length === 2) {
            const geometry = new THREE.BufferGeometry().setFromPoints(measurementPoints);
            const material = new THREE.LineBasicMaterial({
                color: 0xff3030,
                linewidth: 2,
                depthTest: false,
                depthWrite: false,
            });
            const line = new THREE.Line(geometry, material);
            line.renderOrder = 999;
            measurementGroup.add(line);
        }
        pc.render();
    }

    function pickCloudPoint(event: MouseEvent) {
        const canvas = view.renderer.domElement;
        const rect = canvas.getBoundingClientRect();
        const mouse = new THREE.Vector2(
            ((event.clientX - rect.left) / rect.width) * 2 - 1,
            -((event.clientY - rect.top) / rect.height) * 2 + 1,
        );
        measurementRaycaster.params.Points = {
            threshold: THREE.MathUtils.clamp(view.camera.position.length() * 0.005, 0.08, 0.8),
        };
        measurementRaycaster.setFromCamera(mouse, view.camera);
        const intersections = measurementRaycaster.intersectObjects(pc.groupPoints.children, true);
        return intersections.length > 0 ? intersections[0].point.clone() : null;
    }

    function onMeasurementMouseDown(event: MouseEvent) {
        if (!editor.state.config.activePointMeasure || event.button !== 0) return;
        measurementMouseDown.set(event.clientX, event.clientY);
        measurementClickValid = false;
        event.stopImmediatePropagation();
    }

    function onMeasurementMouseUp(event: MouseEvent) {
        if (!editor.state.config.activePointMeasure || event.button !== 0) return;
        measurementClickValid =
            measurementMouseDown.distanceTo(new THREE.Vector2(event.clientX, event.clientY)) < 6;
        event.stopImmediatePropagation();
    }

    function onMeasurementClick(event: MouseEvent) {
        if (!editor.state.config.activePointMeasure) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        if (!measurementClickValid) return;
        const point = pickCloudPoint(event);
        if (!point) {
            editor.showMsg('warning', '未拾取到点云点，请放大后重试');
            return;
        }
        if (measurementMode.value === 'point' || measurementPoints.length >= 2) clearMeasurement();
        measurementPoints.push(point);
        refreshMeasurementObjects();
    }

    function onMeasurementContextMenu(event: MouseEvent) {
        if (!editor.state.config.activePointMeasure) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        clearMeasurement();
    }

    function onMeasurementKeyDown(event: KeyboardEvent) {
        if (!editor.state.config.activePointMeasure || event.key !== 'Escape') return;
        if (measurementPoints.length > 0) clearMeasurement();
        else closeMeasurement();
    }

    function updateMeasurementLabels() {
        if (!editor.state.config.activePointMeasure || measurementPoints.length === 0) {
            state.measurementLabels = [];
            return;
        }
        const matrix = new THREE.Matrix4()
            .copy(view.camera.projectionMatrix)
            .multiply(view.camera.matrixWorldInverse);
        const labels: IMeasurementLabel[] = [];
        const addLabel = (
            key: string,
            type: 'point' | 'distance',
            position: THREE.Vector3,
            name: string,
        ) => {
            const screen = position.clone().applyMatrix4(matrix);
            if (Math.abs(screen.z) > 1) return;
            labels.push({
                key,
                type,
                name,
                x: ((screen.x + 1) / 2) * view.width,
                y: (-(screen.y - 1) / 2) * view.height,
                scale: 1,
            });
        };
        measurementPoints.forEach((point, index) => {
            addLabel(
                `point-${index}`,
                'point',
                point,
                `P${index + 1} (${formatValue(point.x)}, ${formatValue(point.y)}, ${formatValue(point.z)})`,
            );
        });
        if (
            measurementMode.value === 'distance' &&
            measurementResult.value &&
            measurementPoints.length === 2
        ) {
            const result = measurementResult.value;
            addLabel(
                'distance',
                'distance',
                measurementPoints[0].clone().add(measurementPoints[1]).multiplyScalar(0.5),
                `D ${formatValue(result.distance)}m  Δx ${formatSigned(result.dx)}  Δy ${formatSigned(result.dy)}  Δz ${formatSigned(result.dz)}`,
            );
        }
        state.measurementLabels = labels;
    }

    let classTypeMap = computed(() => {
        let map = {} as Record<string, IClassType>;
        editor.state.classTypes.forEach((e) => {
            map[e.name] = e;
        });
        return map;
    });

    // let updateAnnotation = () => {
    //     if (!editor.state.config.showAnnotation) return;
    //     let data = editor.state.annotationInfos;
    //     let camera = view.camera;
    //     let matrix = new THREE.Matrix4();
    //     matrix.copy(camera.projectionMatrix);
    //     matrix.multiply(camera.matrixWorldInverse);

    //     let object3d = editor.pc.getAnnotate3D();
    //     let idMap: Record<string, THREE.Object3D> = {};
    //     object3d.forEach((obj) => {
    //         idMap[obj.uuid] = obj;
    //     });

    //     let annotations = [] as any[];
    //     let pos = new THREE.Vector3();
    //     data.forEach((e) => {
    //         if (e.position) {
    //             pos.copy(e.position);
    //         } else if (e.objectId) {
    //             let obj = idMap[e.objectId];
    //             if (!obj) return;
    //             pos.copy(obj.position);
    //         }

    //         pos.applyMatrix4(matrix);

    //         pos.x = ((pos.x + 1) / 2) * view.width;
    //         pos.y = (-(pos.y - 1) / 2) * view.height;

    //         let obj = {
    //             name: e.msg,
    //             x: pos.x,
    //             y: pos.y,
    //             scale: 1,
    //         };
    //         annotations.push(obj);
    //     });

    //     state.annotations = annotations;
    // };

    let updateLabel = () => {
        // if (!editor.state.config.showLabel) return;
        let measureLineObjects = editor.pc.groupTrack;
        let camera = view.camera;
        let matrix = new THREE.Matrix4();
        matrix.copy(camera.projectionMatrix);
        matrix.multiply(camera.matrixWorldInverse);

        let objects = pc.getAnnotate3D();

        let list: ILabel[] = [];
        let predictionList: ILabel[] = [];
        let list1: ILabel[] = [];
        let pos = new THREE.Vector3();
        let pos1 = new THREE.Vector3();

        if (measureLineObjects.visible) {
            measureLineObjects.children.forEach((e) => {
                if (!e.visible) return;
                const size = e.scale.x;
                pos.set(0, 0, 0);
                pos.applyMatrix4(e.matrixWorld);
                pos.x += size;
                pos.applyMatrix4(matrix);
                pos.x = ((pos.x + 1) / 2) * view.width;
                pos.y = (-(pos.y - 1) / 2) * view.height;
                if (Math.abs(pos.z) > 1) return;
                let obj = {
                    name: size + 'm',
                    x: pos.x,
                    y: pos.y - 6,
                    scale: 1,
                };
                list1.push(obj);
            });
        }

        objects.forEach((e) => {
            if (!e.visible) return;
            let userData = e.userData as IUserData;
            const trackID =
                (userData as any).TrackID ?? userData.trackID ?? userData.trackId ?? userData.trackName ?? '';

            // Annotate boxes use unit geometry and store their dimensions in
            // object.scale. matrixWorld applies that scale, so the local
            // top-right corner must remain at half a unit.
            pos.set(0.5, 0.5, 0.5);
            pos.applyMatrix4(e.matrixWorld);
            pos.applyMatrix4(matrix);
            pos.x = ((pos.x + 1) / 2) * view.width;
            pos.y = (-(pos.y - 1) / 2) * view.height;
            // pos.z = 0;

            if (Math.abs(pos.z) > 1) return;

            const isPrediction = userData.sourceType === SourceType.MODEL;
            const confidence = userData.confidence;
            const predictionName = userData.modelClass || userData.classType || 'unknown';
            const predictionText =
                confidence === undefined || confidence === null
                    ? predictionName
                    : `${predictionName} ${Number(confidence).toFixed(2)}`;
            let obj = {
                name: isPrediction ? predictionText : `ID:${trackID}`,
                x: pos.x + 8,
                y: pos.y - 8,
                scale: 1,
            };
            (isPrediction ? predictionList : list).push(obj);
        });
        state.labels = list;
        state.predictionLabels = predictionList;
        state.lineLabels = list1;
    };

    function update() {
        updateLabel();
        updateMeasurementLabels();
        // updateAnnotation();
    }

    onMounted(() => {
        if (dom.value) {
            view = new MainRenderView(dom.value, pc, { name: 'main-view' });
            pc.addRenderView(view);
            measurementGroup.name = 'point-measurement';
            pc.scene.add(measurementGroup);
            const canvas = view.renderer.domElement;
            canvas.addEventListener('mousedown', onMeasurementMouseDown, true);
            canvas.addEventListener('mouseup', onMeasurementMouseUp, true);
            canvas.addEventListener('click', onMeasurementClick, true);
            canvas.addEventListener('contextmenu', onMeasurementContextMenu, true);
            window.addEventListener('keydown', onMeasurementKeyDown);
        }
        view.addEventListener(Event.RENDER_AFTER, update);
    });
    onBeforeUnmount(() => {
        view.removeEventListener(Event.RENDER_AFTER, update);
        const canvas = view.renderer?.domElement;
        canvas?.removeEventListener('mousedown', onMeasurementMouseDown, true);
        canvas?.removeEventListener('mouseup', onMeasurementMouseUp, true);
        canvas?.removeEventListener('click', onMeasurementClick, true);
        canvas?.removeEventListener('contextmenu', onMeasurementContextMenu, true);
        window.removeEventListener('keydown', onMeasurementKeyDown);
        clearMeasurement();
        pc.scene.remove(measurementGroup);
    });

    watch(
        () => editor.state.config.activePointMeasure,
        (active) => {
            if (view.renderer?.domElement) {
                view.renderer.domElement.style.cursor = active ? 'crosshair' : '';
            }
            if (!active) clearMeasurement();
        },
    );

    watch(
        () => editor.state.frameIndex,
        () => clearMeasurement(),
    );
</script>

<style lang="less">
    .main-view {
        height: 100%;
        position: relative;
        overflow: hidden;
    }

    .point-measure-panel {
        position: absolute;
        top: 10px;
        left: 10px;
        z-index: 20;
        min-width: 350px;
        padding: 10px 12px;
        color: #eef7ff;
        background: rgba(18, 24, 31, 0.9);
        border: 1px solid #3b82f6;
        border-radius: 5px;
        font-size: 12px;
        line-height: 22px;
        user-select: text;

        .point-measure-header {
            display: flex;
            justify-content: space-between;
            font-size: 14px;
            font-weight: 600;

            button {
                margin-left: 6px;
                padding: 1px 8px;
                color: #dbeafe;
                background: #1e3a5f;
                border: 1px solid #3b82f6;
                border-radius: 3px;
                cursor: pointer;
            }
        }

        .point-measure-hint {
            color: #9ca3af;
        }

        .point-measure-modes {
            display: flex;
            gap: 6px;
            margin: 6px 0 4px;

            button {
                margin: 0;
                padding: 3px 12px;
                color: #cbd5e1;
                background: #263341;
                border: 1px solid #536273;
                border-radius: 3px;
                cursor: pointer;

                &.active {
                    color: white;
                    background: #2563eb;
                    border-color: #60a5fa;
                }
            }
        }

        .point-measure-result {
            display: grid;
            grid-template-columns: repeat(4, auto);
            gap: 12px;
            margin-top: 4px;
            padding-top: 4px;
            border-top: 1px solid #425466;
            color: #ffd600;
        }
    }

    .point-measure-labels {
        position: absolute;
        inset: 0;
        z-index: 19;
        pointer-events: none;

        .point-measure-label {
            position: absolute;
            max-width: 420px;
            padding: 2px 5px;
            color: white;
            background: rgba(220, 38, 38, 0.9);
            border-radius: 3px;
            font-size: 11px;
            white-space: nowrap;
            transform-origin: left bottom;

            &.distance {
                color: white;
                background: rgba(220, 38, 38, 0.94);
                font-weight: 600;
            }
        }
    }

    .main-view-tool {
        position: absolute;
        right: 6px;
        top: 6px;
        width: 32px;
        background: #333333;
        border-radius: 4px;
        z-index: 1;

        .item {
            display: inline-block;
            width: 32px;
            height: 32px;
            font-size: 18px;
            padding: 6px;
            border-radius: 4px;
            background: #333333;
            color: white;
            cursor: pointer;

            &:hover,
            &.active {
                background: #ffffff4d;
            }
        }
    }
</style>
