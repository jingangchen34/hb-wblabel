import * as THREE from 'three';
import { ColorModeEnum, utils } from 'pc-editor';
import type { IFrame, IDataResource } from 'pc-editor';
import { ResourceLoader } from '../packages/pc-editor/common/DataResource';
import { buildPointLabelColors } from '../packages/pc-render/occ/pointLabel';
import type Editor from './Editor';
import * as api from '../api';

type PoseInfo = {
    translation: THREE.Vector3;
    quaternion: THREE.Quaternion;
};

type QuaternionOrder = 'xyzw' | 'wxyz';

type MergeOptions = {
    frames: IFrame[];
    removeBoxPoints: boolean;
};

export type MergedPointSource = {
    frameId: string;
    pointIndex: number;
};

export default class MultiFrameMergeManager {
    editor: Editor;
    selectedFrameIds = new Set<string>();
    active = false;
    mergedSources: MergedPointSource[] = [];
    mergedBaseLabels?: Uint8Array;
    private mergedGlobalData?: Record<string, any>;
    private poseRoot?: any;
    private obstacleRoot?: any;
    private poseQuaternionOrder: QuaternionOrder = 'xyzw';
    private pointSizeBeforeMerge?: number;
    private pointColorModeBeforeMerge?: ColorModeEnum;
    annotateVisibleBeforeMerge = true;
    version = 0;

    constructor(editor: Editor) {
        this.editor = editor;
        this.syncState();
    }

    toggleFrame(frame: IFrame) {
        const frameId = String(frame.id);
        if (this.selectedFrameIds.has(frameId)) {
            this.selectedFrameIds.delete(frameId);
        } else {
            this.selectedFrameIds.add(frameId);
        }
        this.syncState();
    }

    clearSelection() {
        this.selectedFrameIds.clear();
        this.syncState();
    }

    getSelectedFrames() {
        const { frames } = this.editor.state;
        return frames.filter((frame) => this.selectedFrameIds.has(String(frame.id)));
    }

    async mergeSelected(removeBoxPoints: boolean) {
        let frames = this.getSelectedFrames();
        if (frames.length === 0) {
            frames = [this.editor.getCurrentFrame()].filter(Boolean);
        }
        return this.merge({ frames, removeBoxPoints });
    }

    async mergeAll(removeBoxPoints: boolean) {
        return this.merge({ frames: this.editor.state.frames, removeBoxPoints });
    }

    cancel() {
        this.active = false;
        this.mergedSources = [];
        this.mergedBaseLabels = undefined;
        this.mergedGlobalData = undefined;
        this.poseRoot = undefined;
        this.obstacleRoot = undefined;
        this.restorePointDisplayConfig();
        this.editor.pc.annotate3D.visible = this.annotateVisibleBeforeMerge;
        this.version++;
        this.syncState();
        this.restoreCurrentFrameResource();
    }

    captureDisplayLabels() {
        if (!this.active || !this.mergedGlobalData) return;
        const labels = this.editor.pc.getPointLabels();
        if (labels && labels.length === this.mergedSources.length) {
            this.mergedGlobalData.pointLabels = new Uint8Array(labels);
        }
    }

    async refreshDisplayForCurrentFrame() {
        if (!this.active || !this.mergedGlobalData || !this.poseRoot) return;
        this.captureDisplayLabels();
        const frame = this.editor.getCurrentFrame();
        if (!frame) return;
        const config = await this.getResource(frame);
        const displayData = this.projectMergedToFrame(
            this.mergedGlobalData,
            frame,
            config,
            this.poseRoot,
            this.obstacleRoot,
        );
        this.showMergedData(displayData);
    }

    restoreCurrentFrameResource() {
        const frame = this.editor.getCurrentFrame();
        const resource = frame ? this.editor.dataResource.dataMap[frame.id] : undefined;
        if (resource) {
            this.resetPointViewRange();
            this.editor.setPointCloudData(resource.pointsData, resource.ground || 0, resource.intensityRange);
            this.focusPointCloud(resource.pointsData.position as Float32Array);
            if (resource.occData) {
                this.editor.setOccGridData(resource.occData);
            } else {
                this.editor.pc.clearOccGrid();
            }
        }
    }

    private async merge(options: MergeOptions) {
        const frames = options.frames.filter(Boolean);
        if (frames.length === 0) return;

        this.editor.showLoading({
            type: 'loading',
            content: `Merging ${frames.length} frames...`,
        });
        try {
            if (options.removeBoxPoints) {
                await this.ensureFrameObjects(frames);
            }
            const configs = await Promise.all(frames.map((frame) => this.getResource(frame)));
            const metaConfig = configs.find((config) => config.poseUrl && config.obstacleUrl) || configs[0];
            if (!metaConfig?.poseUrl) {
                throw new Error('pose.json not found in current scene files');
            }

            const [poseRoot, obstacleRoot, poseMetadataRoot] = await Promise.all([
                api.getUrl(metaConfig.poseUrl),
                metaConfig.obstacleUrl ? api.getUrl(metaConfig.obstacleUrl).catch(() => undefined) : undefined,
                metaConfig.poseMetadataUrl ? api.getUrl(metaConfig.poseMetadataUrl).catch(() => undefined) : undefined,
            ]);

            this.poseQuaternionOrder = this.detectPoseQuaternionOrder(
                poseRoot,
                obstacleRoot,
                configs,
                poseMetadataRoot,
            );
            this.savePointDisplayConfig();
            const mergedGlobal = this.mergePointData(frames, configs, poseRoot, obstacleRoot, options.removeBoxPoints);
            this.poseRoot = poseRoot;
            this.obstacleRoot = obstacleRoot;
            this.mergedGlobalData = mergedGlobal;
            const currentFrame = this.editor.getCurrentFrame() || frames[0];
            const currentConfig = configs[frames.indexOf(currentFrame)] || await this.getResource(currentFrame);
            const merged = this.projectMergedToFrame(
                mergedGlobal,
                currentFrame,
                currentConfig,
                poseRoot,
                obstacleRoot,
            );
            this.showMergedData(merged);
            this.annotateVisibleBeforeMerge = this.editor.pc.annotate3D.visible;
            this.editor.pc.annotate3D.visible = false;
            this.active = true;
            this.version++;
            this.selectedFrameIds.clear();
            this.syncState();
            this.editor.showMsg('success', `Merged ${frames.length} frames`);
        } catch (error: any) {
            this.editor.handleErr(error, 'Merge frames failed');
        } finally {
            this.editor.showLoading(false);
        }
    }

    private showMergedData(merged: Record<string, any>) {
        const pointInfo = this.editor.dataResource.calculatePointInfo(merged);
        const labels = merged.pointLabels as Uint8Array | undefined;
        if (labels && (!this.isViewMode() || this.hasOccLabels(labels))) {
            merged.color = buildPointLabelColors(labels, this.getLabelColorMap());
        }
        this.applyMergedPointDisplay(labels);
        this.resetPointViewRange();
        this.editor.setPointCloudData(merged, pointInfo.ground, pointInfo.intensityRange);
        this.focusMergedPointCloud(merged.position);
    }

    private projectMergedToFrame(
        mergedGlobal: Record<string, any>,
        frame: IFrame,
        config: IDataResource,
        poseRoot: any,
        obstacleRoot: any,
    ) {
        const pose = this.getFramePose(frame, config, poseRoot, obstacleRoot);
        const inversePose = new THREE.Matrix4()
            .compose(pose.translation, pose.quaternion, new THREE.Vector3(1, 1, 1))
            .invert();
        const sourcePosition = mergedGlobal.position as Float32Array;
        const position = new Float32Array(sourcePosition.length);
        const point = new THREE.Vector3();
        for (let index = 0; index < sourcePosition.length; index += 3) {
            point.set(sourcePosition[index], sourcePosition[index + 1], sourcePosition[index + 2]);
            point.applyMatrix4(inversePose);
            position[index] = point.x;
            position[index + 1] = point.y;
            position[index + 2] = point.z;
        }

        return {
            ...mergedGlobal,
            position,
            intensity: mergedGlobal.intensity,
            pointLabels: new Uint8Array(mergedGlobal.pointLabels as Uint8Array),
            color: mergedGlobal.color,
        };
    }

    private getLabelColorMap() {
        return Object.values(this.editor.dataResource.dataMap)
            .map((resource: any) => resource?.labelColorMap)
            .find(Boolean);
    }

    private applyMergedPointDisplay(labels?: Uint8Array) {
        const config = this.editor.state.config;
        const hasOccLabels = this.hasOccLabels(labels);
        config.pointColorMode = hasOccLabels || !this.isViewMode() ? ColorModeEnum.RGB : ColorModeEnum.HEIGHT;
        if (!hasOccLabels) {
            config.pointSize = Math.min(config.pointSize, 0.03);
        }
    }

    private hasOccLabels(labels?: Uint8Array) {
        return !!labels?.some((label) => label > 0);
    }

    private isViewMode() {
        return this.editor.state.modeConfig?.name === 'view';
    }

    private savePointDisplayConfig() {
        const config = this.editor.state.config;
        if (this.pointSizeBeforeMerge === undefined) {
            this.pointSizeBeforeMerge = config.pointSize;
            this.pointColorModeBeforeMerge = config.pointColorMode;
        }
    }

    private restorePointDisplayConfig() {
        const config = this.editor.state.config;
        if (this.pointSizeBeforeMerge !== undefined) {
            config.pointSize = this.pointSizeBeforeMerge;
            this.pointSizeBeforeMerge = undefined;
        }
        if (this.pointColorModeBeforeMerge !== undefined) {
            config.pointColorMode = this.pointColorModeBeforeMerge;
            this.pointColorModeBeforeMerge = undefined;
        }
    }

    private async getResource(frame: IFrame): Promise<IDataResource> {
        const resource = this.editor.dataResource.getResource(frame);
        if (resource instanceof ResourceLoader) {
            return await resource.get();
        }
        return resource;
    }

    private async ensureFrameObjects(frames: IFrame[]) {
        const unloadedFrames = frames.filter((frame) => !this.editor.dataManager.getFrameObject(frame.id));
        if (unloadedFrames.length === 0) return;

        const data = await this.editor.businessManager.getFrameObject(unloadedFrames);
        unloadedFrames.forEach((frame) => {
            frame.queryTime = data.queryTime;
            const objects = data.objectsMap[frame.id] || [];
            const annotates = utils.convertObject2Annotate(objects, this.editor);
            this.editor.dataManager.setFrameObject(frame.id, annotates);
            if (this.editor.state.isSeriesFrame) {
                this.editor.trackManager.addTrackCount(annotates, frame);
            }
        });
    }

    private mergePointData(
        frames: IFrame[],
        configs: IDataResource[],
        poseRoot: any,
        obstacleRoot: any,
        removeBoxPoints: boolean,
    ) {
        const counts = configs.map((config, index) =>
            this.countKeptPoints(config, frames[index], removeBoxPoints),
        );
        const total = counts.reduce((sum, count) => sum + count, 0);
        const position = new Float32Array(total * 3);
        const intensity = new Float32Array(total);
        const pointLabels = new Uint8Array(total);
        const sources: MergedPointSource[] = new Array(total);

        let targetIndex = 0;
        configs.forEach((config, configIndex) => {
            const frame = frames[configIndex];
            const pose = this.getFramePose(frame, config, poseRoot, obstacleRoot);
            const sourcePosition = config.pointsData.position as Float32Array;
            const sourceIntensity = config.pointsData.intensity as Float32Array | undefined;
            const sourceLabels = config.pointsData.pointLabels as Uint8Array | undefined;
            const boxes = removeBoxPoints ? this.getFrameBoxes(frame) : [];
            const point = new THREE.Vector3();

            for (let i = 0; i < sourcePosition.length / 3; i++) {
                point.fromArray(sourcePosition, i * 3);
                if (boxes.length > 0 && this.isInsideAnyBox(point, boxes)) continue;

                point.applyQuaternion(pose.quaternion).add(pose.translation);
                position[targetIndex * 3] = point.x;
                position[targetIndex * 3 + 1] = point.y;
                position[targetIndex * 3 + 2] = point.z;
                intensity[targetIndex] = sourceIntensity?.[i] || 0;
                pointLabels[targetIndex] = sourceLabels?.[i] || 0;
                sources[targetIndex] = {
                    frameId: String(frame.id),
                    pointIndex: i,
                };
                targetIndex++;
            }
        });

        this.mergedSources = sources;
        this.mergedBaseLabels = new Uint8Array(pointLabels);
        const colorMap = configs.find((config) => config.labelColorMap)?.labelColorMap;
        const color = buildPointLabelColors(pointLabels, colorMap);
        return { position, intensity, pointLabels, color };
    }

    private resetPointViewRange() {
        const config = this.editor.state.config;
        config.heightRange = [-10000, 10000];
        config.pointHeight = [-Infinity, Infinity];
        config.pointIntensity = [-Infinity, Infinity];
    }

    private focusMergedPointCloud(position: Float32Array) {
        this.focusPointCloud(position);
    }

    private focusPointCloud(position: Float32Array) {
        if (!position.length) return;
        const box = new THREE.Box3();
        const point = new THREE.Vector3();
        for (let index = 0; index < position.length; index += 3) {
            point.set(position[index], position[index + 1], position[index + 2]);
            box.expandByPoint(point);
        }
        if (box.isEmpty()) return;
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        const radius = Math.max(size.x, size.y, size.z, 10);
        const view = this.editor.viewManager.getMainView();
        if (!view) return;

        const distance = Math.max(radius * 1.8, 80);
        const direction = new THREE.Vector3(0, -0.35, 1).normalize();
        view.camera.position.copy(center).add(direction.multiplyScalar(distance));
        view.camera.near = Math.max(0.1, distance / 10000);
        view.camera.far = Math.max(30000, distance * 6);
        view.camera.updateProjectionMatrix();
        view.camera.lookAt(center);

        const orbitAction = view.getAction('orbit-control') as any;
        if (orbitAction?.control) {
            orbitAction.control.target.copy(center);
            orbitAction.control.maxDistance = Math.max(1000, distance * 4);
            orbitAction.control.update();
        }
        view.render();
    }

    private countKeptPoints(config: IDataResource, frame: IFrame, removeBoxPoints: boolean) {
        const sourcePosition = config.pointsData.position as Float32Array;
        if (!removeBoxPoints) return sourcePosition.length / 3;

        const boxes = this.getFrameBoxes(frame);
        if (boxes.length === 0) return sourcePosition.length / 3;

        let count = 0;
        const point = new THREE.Vector3();
        for (let i = 0; i < sourcePosition.length / 3; i++) {
            point.fromArray(sourcePosition, i * 3);
            if (!this.isInsideAnyBox(point, boxes)) count++;
        }
        return count;
    }

    private getFrameBoxes(frame: IFrame) {
        return (this.editor.dataManager.getFrameObject(frame.id) || []).filter((object: any) => {
            return object instanceof THREE.Object3D && object.visible !== false;
        }) as THREE.Object3D[];
    }

    private isInsideAnyBox(point: THREE.Vector3, boxes: THREE.Object3D[]) {
        const localPoint = new THREE.Vector3();
        return boxes.some((box) => {
            box.updateMatrixWorld(true);
            localPoint.copy(point).applyMatrix4(new THREE.Matrix4().copy(box.matrixWorld).invert());
            return Math.abs(localPoint.x) <= 0.5 &&
                Math.abs(localPoint.y) <= 0.5 &&
                Math.abs(localPoint.z) <= 0.5;
        });
    }

    private getFramePose(frame: IFrame, config: IDataResource, poseRoot: any, obstacleRoot: any): PoseInfo {
        const obstacleNode = this.findNodeByFrame(obstacleRoot, frame, config);
        const poseKey = this.findPoseKey(frame, config, obstacleNode);
        const poseNode = this.findNodeByKey(poseRoot, poseKey) || this.findNodeByFrame(poseRoot, frame, config);
        const pose = this.parsePose(poseNode);
        if (!pose) {
            throw new Error(`Pose not found for frame ${config.name || frame.id}`);
        }
        return pose;
    }

    private findPoseKey(frame: IFrame, config: IDataResource, node: any) {
        return this.normalizePoseKey(node?.ego_pose) ||
            this.normalizePoseKey(node?.egoPose) ||
            this.normalizePoseKey(node?.ego_file) ||
            this.normalizePoseKey(node?.egoFile) ||
            this.extractFrameToken(config.name || '') ||
            config.name ||
            frame.id;
    }

    private normalizePoseKey(value: any) {
        if (value === undefined || value === null || value === '') return '';
        if (typeof value === 'string' || typeof value === 'number') return String(value);
        if (typeof value === 'object') {
            return this.normalizePoseKey(value.ego_file) ||
                this.normalizePoseKey(value.egoFile) ||
                this.normalizePoseKey(value.timestamp) ||
                this.normalizePoseKey(value.time) ||
                this.normalizePoseKey(value.key);
        }
        return '';
    }

    private findNodeByFrame(root: any, frame: IFrame, config: IDataResource): any {
        const tokens = [config.name, this.extractFrameToken(config.name || '')]
            .filter(Boolean)
            .map((item) => String(item));
        return this.walkFind(root, (node, key) => {
            if (tokens.some((token) => key === token)) return true;
            const values = [node?.filepath, node?.filePath, node?.name, node?.timestamp, node?.FrameID];
            return values.some((value) => value !== undefined && tokens.some((token) => String(value).includes(token)));
        });
    }

    private findNodeByKey(root: any, key: string) {
        if (!key) return undefined;
        const normalizedKey = String(key);
        return this.walkFind(root, (_node, nodeKey) => nodeKey === normalizedKey);
    }

    private walkFind(root: any, predicate: (node: any, key: string) => boolean): any {
        if (!root || typeof root !== 'object') return undefined;
        const stack: { node: any; key: string }[] = [{ node: root, key: '' }];
        while (stack.length > 0) {
            const current = stack.pop() as { node: any; key: string };
            if (current.node && typeof current.node === 'object' && predicate(current.node, current.key)) {
                return current.node;
            }
            Object.keys(current.node || {}).forEach((key) => {
                const value = current.node[key];
                if (value && typeof value === 'object') stack.push({ node: value, key });
            });
        }
        return undefined;
    }

    private parsePose(node: any): PoseInfo | undefined {
        if (!node) return undefined;
        const pose = node.ego_pose || node.pose || node;
        const translation = this.parseVector(pose.translation || pose.position || pose.location || pose.xyz || pose);
        const quaternion = this.parseQuaternion(pose.rotation || pose.quaternion || pose.orientation || pose.q || pose, pose);
        if (!translation || !quaternion) return undefined;
        return { translation, quaternion };
    }

    private parseVector(value: any) {
        if (Array.isArray(value) && value.length >= 3) {
            return new THREE.Vector3(Number(value[0]), Number(value[1]), Number(value[2]));
        }
        if (value && ['x', 'y', 'z'].every((key) => Number.isFinite(Number(value[key])))) {
            return new THREE.Vector3(Number(value.x), Number(value.y), Number(value.z));
        }
        return undefined;
    }

    private parseQuaternion(value: any, context?: any) {
        if (value?.wxyz) return this.quaternionFromArray(value.wxyz, 'wxyz');
        if (value?.xyzw) return this.quaternionFromArray(value.xyzw, 'xyzw');
        if (Array.isArray(value) && value.length >= 4) {
            return this.quaternionFromArray(
                value,
                this.findQuaternionOrderMarker(context) || this.poseQuaternionOrder,
            );
        }
        if (value) {
            const w = value.w ?? value.qw;
            const x = value.x ?? value.qx;
            const y = value.y ?? value.qy;
            const z = value.z ?? value.qz;
            if ([w, x, y, z].every((item) => Number.isFinite(Number(item)))) {
                return new THREE.Quaternion(Number(x), Number(y), Number(z), Number(w)).normalize();
            }
        }
        return undefined;
    }

    private quaternionFromArray(value: any, order: QuaternionOrder) {
        if (!Array.isArray(value) || value.length < 4) return undefined;
        const items = value.slice(0, 4).map((item) => Number(item));
        if (!items.every((item) => Number.isFinite(item))) return undefined;
        const [a, b, c, d] = items;
        return order === 'wxyz'
            ? new THREE.Quaternion(b, c, d, a).normalize()
            : new THREE.Quaternion(a, b, c, d).normalize();
    }

    private detectPoseQuaternionOrder(
        poseRoot: any,
        obstacleRoot: any,
        configs: IDataResource[],
        poseMetadataRoot?: any,
    ): QuaternionOrder {
        const explicit = this.findQuaternionOrderMarker(poseMetadataRoot) ||
            this.findQuaternionOrderMarker(poseRoot) ||
            this.findQuaternionOrderMarker(obstacleRoot);
        if (explicit) return explicit;

        const cameraCount = this.detectCameraCount(obstacleRoot, configs);
        return cameraCount > 0 && cameraCount <= 5 ? 'wxyz' : 'xyzw';
    }

    private findQuaternionOrderMarker(root: any): QuaternionOrder | undefined {
        if (!root || typeof root !== 'object') return undefined;
        const stack: any[] = [root];
        const keyReg = /(quat|quaternion|rotation|orientation).*?(order|format|sequence)|(order|format|sequence).*?(quat|quaternion|rotation|orientation)/i;
        let visited = 0;
        while (stack.length > 0 && visited < 2000) {
            const node = stack.pop();
            visited++;
            if (!node || typeof node !== 'object') continue;
            for (const key of Object.keys(node)) {
                const value = node[key];
                if (keyReg.test(key) && typeof value === 'string') {
                    const text = value.toLowerCase();
                    if (text.includes('wxyz')) return 'wxyz';
                    if (text.includes('xyzw')) return 'xyzw';
                }
                if (value && typeof value === 'object') stack.push(value);
            }
        }
        return undefined;
    }

    private detectCameraCount(obstacleRoot: any, configs: IDataResource[]) {
        let cameraCount = configs.reduce((max, config) => Math.max(max, config.viewConfig?.length || 0), 0);
        if (!obstacleRoot || typeof obstacleRoot !== 'object') return cameraCount;

        const stack = [obstacleRoot];
        let visited = 0;
        while (stack.length > 0 && visited < 5000) {
            const node = stack.pop();
            visited++;
            if (!node || typeof node !== 'object') continue;
            if (node.cam_files && typeof node.cam_files === 'object') {
                cameraCount = Math.max(cameraCount, Object.keys(node.cam_files).length);
            }
            Object.keys(node).forEach((key) => {
                const value = node[key];
                if (value && typeof value === 'object') stack.push(value);
            });
        }
        return cameraCount;
    }

    private extractFrameToken(name: string) {
        const match = String(name).match(/(\d{13,})/);
        return match?.[1] || '';
    }

    private syncState() {
        const state = this.editor.state as any;
        state.mergeSelectedFrameIds = [...this.selectedFrameIds];
        state.mergeActive = this.active;
        state.mergePointCount = this.mergedSources.length;
    }
}
