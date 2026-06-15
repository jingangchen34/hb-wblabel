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
        this.editor.pc.annotate3D.visible = this.annotateVisibleBeforeMerge;
        this.version++;
        this.syncState();
        this.restoreCurrentFrameResource();
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

            const [poseRoot, obstacleRoot] = await Promise.all([
                api.getUrl(metaConfig.poseUrl),
                metaConfig.obstacleUrl ? api.getUrl(metaConfig.obstacleUrl).catch(() => undefined) : undefined,
            ]);

            const merged = this.mergePointData(frames, configs, poseRoot, obstacleRoot, options.removeBoxPoints);
            const pointInfo = this.editor.dataResource.calculatePointInfo(merged);
            this.editor.state.config.pointColorMode = ColorModeEnum.RGB;
            this.resetPointViewRange();
            this.editor.setPointCloudData(merged, pointInfo.ground, pointInfo.intensityRange);
            this.focusMergedPointCloud(merged.position);
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
            const shouldConvertAxis = this.shouldConvertLidarCarToPoseEgo(config);
            const point = new THREE.Vector3();

            for (let i = 0; i < sourcePosition.length / 3; i++) {
                point.fromArray(sourcePosition, i * 3);
                if (boxes.length > 0 && this.isInsideAnyBox(point, boxes)) continue;

                if (shouldConvertAxis) this.lidarCarToPoseEgo(point);
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

    private shouldConvertLidarCarToPoseEgo(config: IDataResource) {
        return (config.viewConfig || []).length >= 7;
    }

    private lidarCarToPoseEgo(point: THREE.Vector3) {
        const right = point.x;
        const front = point.y;
        point.set(front, -right, point.z);
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
        const egoFile = this.findEgoFile(frame, config, obstacleRoot);
        const poseNode = this.findNodeByKey(poseRoot, egoFile) || this.findNodeByFrame(poseRoot, frame, config);
        const pose = this.parsePose(poseNode);
        if (!pose) {
            throw new Error(`Pose not found for frame ${config.name || frame.id}`);
        }
        return pose;
    }

    private findEgoFile(frame: IFrame, config: IDataResource, obstacleRoot: any) {
        const node = this.findNodeByFrame(obstacleRoot, frame, config);
        return node?.ego_file || node?.egoFile || this.extractFrameToken(config.name || '') || config.name || frame.id;
    }

    private findNodeByFrame(root: any, frame: IFrame, config: IDataResource): any {
        const tokens = [config.name, this.extractFrameToken(config.name || ''), frame.id]
            .filter(Boolean)
            .map((item) => String(item));
        return this.walkFind(root, (node, key) => {
            if (tokens.some((token) => key === token || key.includes(token))) return true;
            const values = [node?.filepath, node?.filePath, node?.name, node?.timestamp, node?.FrameID];
            return values.some((value) => value !== undefined && tokens.some((token) => String(value).includes(token)));
        });
    }

    private findNodeByKey(root: any, key: string) {
        if (!key) return undefined;
        return this.walkFind(root, (_node, nodeKey) => nodeKey === key || nodeKey.includes(key));
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
        const quaternion = this.parseQuaternion(pose.rotation || pose.quaternion || pose.orientation || pose.q || pose);
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

    private parseQuaternion(value: any) {
        if (Array.isArray(value) && value.length >= 4) {
            const items = value.slice(0, 4).map((item) => Number(item));
            if (items.every((item) => Number.isFinite(item))) {
                return this.chooseVehiclePoseQuaternion(
                    new THREE.Quaternion(items[0], items[1], items[2], items[3]).normalize(),
                    new THREE.Quaternion(items[1], items[2], items[3], items[0]).normalize(),
                );
            }
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

    private chooseVehiclePoseQuaternion(xyzw: THREE.Quaternion, wxyz: THREE.Quaternion) {
        const up = new THREE.Vector3(0, 0, 1);
        const xyzwUp = up.clone().applyQuaternion(xyzw);
        const wxyzUp = up.clone().applyQuaternion(wxyz);
        return xyzwUp.z >= wxyzUp.z ? xyzw : wxyz;
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
