<template>
    <div class="main-view">
        <div ref="dom" style="height: 100%; width: 100%; position: relative"></div>
        <Labels :data="state.labels" v-show="editor.state.config.showLabel" />
        <Labels :data="state.predictionLabels" />
        <Labels :data="state.lineLabels" />
        <!-- <Annotation :data="state.annotations" v-show="editor.state.config.showAnnotation" /> -->
        <slot name="info" v-if="$slots.info"></slot>
        <Info v-else />
        <Image2DMax />
        <slot name="editClass" v-if="$slots.editClass"></slot>
    </div>
</template>

<script setup lang="ts">
    import { onMounted, onBeforeUnmount, ref, reactive, computed } from 'vue';
    import { MainRenderView, Event } from 'pc-render';
    import { useInjectEditor } from '../../state';
    import * as _ from 'lodash';
    import * as THREE from 'three';

    import Labels from './Labels.vue';
    import Annotation from './Annotation.vue';
    import Info from './Info.vue';
    import Image2DMax from '../ImgView/Image2DMax.vue';

    import { IUserData, IClassType, SourceType } from 'pc-editor';

    interface ILabel {
        name: string;
        x: number;
        y: number;
        scale: number;
    }

    let dom = ref<HTMLDivElement | null>(null);
    let editor = useInjectEditor();
    let pc = editor.pc;
    let view = {} as MainRenderView;
    let state = reactive({
        labels: [] as ILabel[],
        predictionLabels: [] as ILabel[],
        lineLabels: [] as ILabel[],
        annotations: [] as any[],
    });

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
        // updateAnnotation();
    }

    onMounted(() => {
        if (dom.value) {
            view = new MainRenderView(dom.value, pc, { name: 'main-view' });
            pc.addRenderView(view);
        }
        view.addEventListener(Event.RENDER_AFTER, update);
    });
    onBeforeUnmount(() => {
        view.removeEventListener(Event.RENDER_AFTER, update);
    });
</script>

<style lang="less">
    .main-view {
        height: 100%;
        position: relative;
        overflow: hidden;
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
