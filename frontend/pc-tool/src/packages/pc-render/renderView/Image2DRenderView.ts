import * as THREE from 'three';
import Render from './Render';
import PointCloud from '../PointCloud';
import PointsMaterial, { IUniformOption } from '../material/PointsMaterial';
import * as _ from 'lodash';
import { Object2D, Box, Rect, Vector2Of4, Box2D, AnnotateObject } from '../objects';
import { IRenderViewConfig, ICameraInternal } from '../type';
import {
    createMatrixFromCameraInternal,
    getMaxMinV2,
} from '../utils';
import { get } from '../utils/tempVar';
import Image2DRenderProxy from './Image2DRenderProxy';
import { Event } from '../config/';

const defaultActions: string[] = [
    'select',
    'render-2d-shape',
    'create-obj',
    'edit-2d',
    'transform-2d',
];
// const defaultActions: string[] = ['select-2d'];

type ActionType =
    | 'select'
    | 'render-2d-shape'
    | 'create-obj'
    | 'edit-2d'
    | 'transform-2d'
    | 'render-2d-track';

interface IOption {
    cameraInternal: ICameraInternal;
    cameraExternal: Array<number>;
    imgSize?: [number, number];
    imgUrl?: string;
    imgObject: HTMLImageElement;
    projectionType?: 'pinhole' | 'fisheye' | 'cylindrical';
}

const boxLineIndices = [
    [0, 1],
    [0, 3],
    [0, 4],
    [1, 2],
    [1, 5],
    [3, 2],
    [3, 7],
    [4, 5],
    [4, 7],
    [2, 6],
    [5, 6],
    [6, 7],
];

let positionsFrontV3 = [...Array(4)].map((e) => new THREE.Vector3());
let positionsBackV3 = [...Array(4)].map((e) => new THREE.Vector3());

let positionsFrontV2 = [...Array(4)].map((e) => new THREE.Vector2());
let positionsBackV2 = [...Array(4)].map((e) => new THREE.Vector2());

let rotate180 = new THREE.Matrix4().makeRotationAxis(new THREE.Vector3(0, 0, 1), Math.PI);
let imgNdc = new THREE.Vector3();

export default class Image2DRenderView extends Render {
    container: HTMLDivElement;
    // matrix
    // proxy offset matrix
    proxyOffset: THREE.Vector2 = new THREE.Vector2();
    proxyTransformMatrix: THREE.Matrix4 = new THREE.Matrix4();
    // local matrix
    containerMatrix: THREE.Matrix4 = new THREE.Matrix4();
    fitMatrix: THREE.Matrix4 = new THREE.Matrix4();
    transformMatrix: THREE.Matrix4 = new THREE.Matrix4();
    pointCloud: PointCloud;
    width: number;
    height: number;
    // proxy
    proxy: Image2DRenderProxy;
    clientRect: DOMRect = {} as DOMRect;
    // 2d
    // canvas?: HTMLCanvasElement;
    // context?: CanvasRenderingContext2D;
    // 3d renderer
    // renderer?: THREE.WebGLRenderer;
    clipCamera: THREE.PerspectiveCamera;
    camera: THREE.PerspectiveCamera;
    cameraHelper: THREE.CameraHelper;
    option: IOption = {} as IOption;
    group: THREE.Group;
    // project matrix
    matrixExternal: THREE.Matrix4 = new THREE.Matrix4();
    matrixInternal: THREE.Matrix4 = new THREE.Matrix4();
    matrix: THREE.Matrix4 = new THREE.Matrix4();
    // img
    img: HTMLImageElement | null = null;
    imgSize: THREE.Vector2 = new THREE.Vector2(1, 1);
    imgAspectRatio: number = 1;
    // color
    // selectColor: THREE.Color = new THREE.Color(1, 0, 0);
    // selectColorCSS: string = '#FF0000';
    // highlightColor: THREE.Color = new THREE.Color(1, 0, 0);
    // box filter matrix
    boxInvertMatrix: THREE.Matrix4 = new THREE.Matrix4();
    // render flag
    renderBox: boolean = true;
    renderPoints: boolean = false;
    renderRect: boolean = true;
    renderBox2D: boolean = true;
    hasCameraConfig: boolean = false;
    // render config
    lineWidth: number = 1;

    constructor(
        container: HTMLDivElement,
        pointCloud: PointCloud,
        config: IRenderViewConfig<ActionType> & { proxy?: Image2DRenderProxy } = {},
    ) {
        super(config.name || '');

        this.container = container;
        this.pointCloud = pointCloud;

        this.width = this.container.clientWidth || 10;
        this.height = this.container.clientHeight || 10;

        let group = new THREE.Group();
        this.pointCloud.scene.add(group);
        this.group = group;

        if (config.proxy) {
            this.proxy = config.proxy;
        } else {
            this.proxy = new Image2DRenderProxy(pointCloud);
            this.proxy.attach(this.container);
        }
        this.proxy.addView(this);

        this.camera = new THREE.PerspectiveCamera(50, this.width / this.height, 1, 1000);
        // this.camera = new THREE.OrthographicCamera(-10, 10, 10, -10, 0.001, 1000);
        this.group.add(this.camera);

        const helper = new THREE.CameraHelper(this.camera);
        helper.visible = false;
        this.group.add(helper);
        // @ts-ignore
        this.cameraHelper = helper;

        // clip
        this.clipCamera = new THREE.PerspectiveCamera(100, this.width / this.height, 0.01, 100);
        // let clipHelper = new THREE.CameraHelper(this.clipCamera);
        // this.group.add(clipHelper);

        this.setActions(config.actions || defaultActions);

        // @ts-ignore
        window.imgView = this;
    }

    init(): void {}

    destroy(): void {
        // this.renderer.dispose();
        // this.pointCloud.scene.remove(this.group);
        // this.cameraHelper.dispose();
    }

    updateSize() {
        let width = this.container.clientWidth || 100;
        let height = this.container.clientHeight || 100;

        if (width !== this.width || height !== this.height) {
            this.width = width;
            this.height = height;
            this.updateAspectRatioConfig();
        }
    }

    updateAspectRatioConfig() {
        let { imgSize, width, height, img } = this;

        if (!img) return;

        let scaleX = imgSize.x / width;
        let scaleY = imgSize.y / height;

        let scale = 1;
        let offsetX = 0;
        let offsetY = 0;
        if (scaleX > scaleY) {
            scale = 1 / scaleX;
            offsetY = (height - imgSize.y * scale) / 2;
        } else {
            scale = 1 / scaleY;
            offsetX = (width - imgSize.x * scale) / 2;
        }
        this.fitMatrix.makeScale(scale, scale, 1);

        let translate = get(THREE.Matrix4);
        translate.makeTranslation(offsetX, offsetY, 0);
        this.fitMatrix.premultiply(translate);
    }

    setOptions(option: IOption) {
        this.option = option;

        let imgObject = option.imgObject;

        this.img = imgObject;

        this.imgSize.set(imgObject.naturalWidth, imgObject.naturalHeight);
        this.imgAspectRatio = this.imgSize.x / this.imgSize.y;
        this.updateAspectRatioConfig();

        this.hasCameraConfig = !!(
            option.cameraInternal &&
            option.cameraExternal &&
            option.cameraExternal.length === 16
        );
        if (!this.hasCameraConfig) {
            this.render();
            return;
        }

        this.matrixInternal.copy(
            createMatrixFromCameraInternal(option.cameraInternal, this.imgSize.x, this.imgSize.y),
        );

        // @ts-ignore
        this.matrixExternal.set(...option.cameraExternal);

        // @ts-ignore
        let matrix = new THREE.Matrix4().set(...option.cameraExternal);
        matrix.premultiply(new THREE.Matrix4().makeScale(1, -1, -1));
        matrix.invert();
        matrix.decompose(this.camera.position, this.camera.quaternion, this.camera.scale);
        this.camera.updateMatrixWorld();

        this.matrix.copy(this.matrixInternal).multiply(this.camera.matrixWorldInverse);

        this.camera.projectionMatrix.copy(this.matrixInternal);
        this.camera.projectionMatrixInverse.copy(this.camera.projectionMatrix).invert();
        // @ts-ignore
        this.cameraHelper.update();

        // clip
        this.clipCamera.position.copy(this.camera.position);
        this.clipCamera.quaternion.copy(this.camera.quaternion);
        this.clipCamera.scale.copy(this.camera.scale);
        this.clipCamera.updateMatrixWorld();
        // this.testFrustum();

        this.render();
    }

    testFrustum() {
        let frustum = new THREE.Frustum();
        frustum.setFromProjectionMatrix(
            this.clipCamera.projectionMatrix.clone().multiply(this.clipCamera.matrixWorldInverse),
        );
        let planeHelper = new THREE.PlaneHelper(frustum.planes[1], 100, 0xcccccc);
        console.log('frustum.planes[1]', frustum.planes[1].normal);

        this.group.add(planeHelper);
    }

    worldToImg(pos: THREE.Vector3, target?: THREE.Vector3) {
        // let domElement = this.renderer.domElement;
        target = target || pos;
        if (!this.hasCameraConfig) return target.copy(pos);

        target.copy(pos);
        const distortion = this.option.cameraInternal?.distortion;
        if (distortion?.length) {
            target.applyMatrix4(this.camera.matrixWorldInverse);

            if (Math.abs(target.z) > 1e-6) {
                const { fx, fy, cx, cy } = this.option.cameraInternal;
                const [k1 = 0, k2 = 0, p1 = 0, p2 = 0, k3 = 0] = distortion;
                const x = -target.x / target.z;
                const y = target.y / target.z;
                const r2 = x * x + y * y;
                const r4 = r2 * r2;
                const r6 = r4 * r2;
                const radial = 1 + k1 * r2 + k2 * r4 + k3 * r6;
                const xDistort = x * radial + 2 * p1 * x * y + p2 * (r2 + 2 * x * x);
                const yDistort = y * radial + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y;

                imgNdc.copy(pos).applyMatrix4(this.camera.matrixWorldInverse);
                imgNdc.applyMatrix4(this.camera.projectionMatrix);

                target.x = fx * xDistort + cx;
                target.y = fy * yDistort + cy;
                target.z = imgNdc.z;

                return target;
            }
        }

        let matrix = get(THREE.Matrix4);
        matrix.copy(this.camera.projectionMatrix);
        matrix.multiply(this.camera.matrixWorldInverse);

        // pos.applyMatrix4(e.matrixWorld);
        target.applyMatrix4(matrix);
        target.x = ((target.x + 1) / 2) * this.imgSize.x;
        target.y = (-(target.y - 1) / 2) * this.imgSize.y;

        return target;
    }

    projectToImg(pos: THREE.Vector3, target?: THREE.Vector3) {
        // let domElement = this.renderer.domElement;
        target = target || pos;
        pos.x = ((pos.x + 1) / 2) * this.imgSize.x;
        pos.y = (-(pos.y - 1) / 2) * this.imgSize.y;

        return target;
    }

    projectWorldToImg(pos: THREE.Vector3, target?: THREE.Vector3) {
        target = target || pos;
        if (!this.hasCameraConfig) return target.copy(pos);

        target.copy(pos);
        target.applyMatrix4(this.matrixExternal);

        const { fx, fy, cx, cy } = this.option.cameraInternal;
        const x = target.x;
        const y = target.y;
        const z = target.z;
        let xNorm = 0;
        let yNorm = 0;

        if (this.option.projectionType === 'cylindrical') {
            xNorm = Math.atan2(x, z);
            yNorm = y / Math.max(Math.sqrt(x * x + z * z), 1e-5);
        } else if (this.option.projectionType === 'fisheye') {
            const radius = Math.max(Math.sqrt(x * x + y * y), 1e-8);
            const theta = Math.atan2(radius, z);
            const [k1 = 0, k2 = 0, k3 = 0, k4 = 0] =
                this.option.cameraInternal?.distortion || [];
            const theta2 = theta * theta;
            const theta4 = theta2 * theta2;
            const theta6 = theta4 * theta2;
            const theta8 = theta4 * theta4;
            const thetaDistorted =
                theta * (1 + k1 * theta2 + k2 * theta4 + k3 * theta6 + k4 * theta8);

            xNorm = (thetaDistorted * x) / radius;
            yNorm = (thetaDistorted * y) / radius;
        } else {
            const depth = Math.min(Math.max(z, 1e-5), 1e5);
            xNorm = x / depth;
            yNorm = y / depth;
        }

        target.x = fx * xNorm + cx;
        target.y = fy * yNorm + cy;
        target.z = z;

        return target;
    }

    getBoxRect(object: Box) {
        // let bbox = object.geometry.boundingBox as THREE.Box3;

        let box2dInfo = this.getBox2DBox(object);
        let rectInfo = getMaxMinV2([...box2dInfo.positionsBack, ...box2dInfo.positionsFront]);

        // let matrix = get(THREE.Matrix4);
        // matrix.copy(this.camera.projectionMatrix);
        // matrix.multiply(this.camera.matrixWorldInverse);
        // matrix.multiply(object.matrixWorld);

        // let box = get(THREE.Box3).copy(bbox);
        // box.applyMatrix4(matrix);

        // this.projectToImg(box.max);
        // this.projectToImg(box.min);

        // let rect = new Rect();
        let center = new THREE.Vector2().set(
            (rectInfo.minX + rectInfo.maxX) / 2,
            (rectInfo.minY + rectInfo.maxY) / 2,
        );
        let size = new THREE.Vector2().set(
            Math.abs(rectInfo.maxX - rectInfo.minX),
            Math.abs(rectInfo.maxY - rectInfo.minY),
        );
        return { center, size };
    }

    getBox2DBox(object: Box) {
        let bbox = object.geometry.boundingBox as THREE.Box3;

        // let newBBox = bbox.clone().applyMatrix4(object.matrixWorld);
        getPositions(bbox, positionsFrontV3, positionsBackV3);
        // if (isInCamera(newBBox, this.camera)) {
        //     // console.log('isInCamera');
        // }

        let matrix = get(THREE.Matrix4).identity();
        // matrix.copy(this.camera.projectionMatrix);
        // matrix.multiply(this.camera.matrixWorldInverse);
        matrix.multiply(object.matrixWorld);

        positionsFrontV3.forEach((v) => {
            v.applyMatrix4(matrix);
            // if (v.z > 0) v.applyMatrix4(rotate180);
            // v.applyMatrix4(this.camera.projectionMatrix);
            // this.projectToImg(v);
        });
        positionsBackV3.forEach((v) => {
            v.applyMatrix4(matrix);
            // if (v.z > 0) v.applyMatrix4(rotate180);
            // v.applyMatrix4(this.camera.projectionMatrix);
            // this.projectToImg(v);
        });

        positionsFrontV3.forEach((v) => {
            this.projectWorldToImg(v);
        });
        positionsBackV3.forEach((v) => {
            this.projectWorldToImg(v);
        });

        // let points = [...positionsFrontV3, ...positionsBackV3];
        // console.log('z>0', points.filter((e) => e.z > 0).length);

        positionsFrontV2.forEach((v2, index) => {
            let v3 = positionsFrontV3[index];
            v2.set(v3.x, v3.y);
        });
        positionsBackV2.forEach((v2, index) => {
            let v3 = positionsBackV3[index];
            v2.set(v3.x, v3.y);
        });

        return { positionsBack: positionsBackV2, positionsFront: positionsFrontV2 };
    }

    getBoxWorldCorners(object: Box) {
        let bbox = object.geometry.boundingBox as THREE.Box3;
        getPositions(bbox, positionsFrontV3, positionsBackV3);

        let matrix = get(THREE.Matrix4).identity();
        matrix.multiply(object.matrixWorld);

        const corners = [...positionsFrontV3, ...positionsBackV3];
        return corners.map((v) => v.clone().applyMatrix4(matrix));
    }

    get2DObject() {
        return this.pointCloud.getAnnotate2D();
    }

    get3DObject() {
        return this.pointCloud.getAnnotate3D();
    }

    boxIntersectsImage(box: Box) {
        const box2dInfo = this.getBox2DBox(box);
        const maxX = this.imgSize.x;
        const maxY = this.imgSize.y;

        return [...box2dInfo.positionsFront, ...box2dInfo.positionsBack].some(
            (pos) =>
                Number.isFinite(pos.x) &&
                Number.isFinite(pos.y) &&
                pos.x >= 0 &&
                pos.x <= maxX &&
                pos.y >= 0 &&
                pos.y <= maxY,
        );
    }

    showMask(obj: AnnotateObject) {
        return false;
    }

    isHighlight(obj: AnnotateObject) {
        return false;
    }

    isRenderable(obj: Object2D) {
        let flag1 = (this.renderId && obj.viewId === this.renderId) || obj.viewId === this.id;

        let flag2 =
            (this.renderRect && obj instanceof Rect) || (this.renderBox2D && obj instanceof Box2D);
        // (this.renderBox && obj instanceof Box);

        return obj.visible && flag1 && flag2;
    }

    imgToDom(imgPos: THREE.Vector2 | THREE.Vector3) {
        let pos = get(THREE.Vector3, 0);
        pos.set(imgPos.x, imgPos.y, 0).applyMatrix4(this.transformMatrix);
        imgPos.x = pos.x;
        imgPos.y = pos.y;
    }

    domToImg(imgPos: THREE.Vector2 | THREE.Vector3) {
        let pos = get(THREE.Vector3, 0);
        let invertMatrix = get(THREE.Matrix4, 0).copy(this.transformMatrix).invert();
        pos.set(imgPos.x, imgPos.y, 0).applyMatrix4(invertMatrix);
        imgPos.x = pos.x;
        imgPos.y = pos.y;
    }

    getScale() {
        return this.transformMatrix.elements[0] || 1;
    }

    setViewport() {
        let { imgSize, height: canvasHeight } = this;
        let { renderer, clientRect, context } = this.proxy;

        // left-bottom corn
        let pos = get(THREE.Vector2, 0).set(0, imgSize.y);
        this.imgToDom(pos);
        pos.y = canvasHeight - pos.y;
        let scale = this.getScale();

        let width = imgSize.x * scale;
        let height = imgSize.y * scale;

        // proxy relative offset
        let top = this.clientRect.top - clientRect.top;
        let left = this.clientRect.left - clientRect.left;
        let bottom = clientRect.bottom - this.clientRect.bottom;

        pos.x += left;
        pos.y += bottom;
        renderer.setViewport(pos.x, pos.y, width, height);
        renderer.setScissor(pos.x, pos.y, width, height);

        // clip view region
        context.beginPath();
        context.rect(left, top, this.clientRect.width, this.clientRect.height);
        context.closePath();
        // context.stroke();
        context.clip();
    }

    render() {
        if (!this.isEnable()) return;
        this.proxy.render();
    }

    isViewRenderable() {
        let { clientRect } = this.proxy;
        let rect = this.container.getBoundingClientRect();
        this.clientRect = rect;

        let needRender =
            rect.bottom >= clientRect.top &&
            rect.top <= clientRect.bottom &&
            rect.left <= clientRect.right &&
            rect.right >= clientRect.left;

        return needRender;
    }

    updateTransform() {
        let { clientRect } = this.proxy;

        const left = this.clientRect.left - clientRect.left;
        const top = this.clientRect.top - clientRect.top;

        this.proxyOffset.set(left, top);
        let offsetMatrix = get(THREE.Matrix4).makeTranslation(left, top, 0);
        this.transformMatrix.copy(this.containerMatrix).multiply(this.fitMatrix);
        this.proxyTransformMatrix.copy(offsetMatrix).multiply(this.transformMatrix);
    }

    renderFrame() {
        // console.log('renderFrame');
        if (!this.isViewRenderable()) return;

        this.dispatchEvent({ type: Event.RENDER_BEFORE });
        this.proxy.renderN++;

        this.updateSize();
        this.updateTransform();
        this.setViewport();

        this.renderImage();
        this.renderObjects();

        this.dispatchEvent({ type: Event.RENDER_AFTER });
    }

    renderObjects() {
        if (!this.renderBox || !this.hasCameraConfig) return;

        let { groupPoints, selection, selectColor } = this.pointCloud;
        let { renderer } = this.proxy;
        let selection3Ds = selection.filter((e) => e instanceof THREE.Object3D);
        let object3Ds = this.get3DObject();

        if (this.renderBox && this.renderPoints && selection3Ds.length > 0) {
            let groupPoint = groupPoints.children[0] as THREE.Points;
            let box = selection[0] as Box;
            box.updateMatrixWorld();
            if (!box.geometry.boundingBox) box.geometry.computeBoundingBox();

            let bbox = box.geometry.boundingBox;
            let material = groupPoint.material as PointsMaterial;
            // groupPoint.material = this.materialPc;

            let oldDepthTest = material.depthTest;
            let oldHasFilterBox = material.getUniforms('hasFilterBox');
            let oldType = material.getUniforms('boxInfo').type;

            material.depthTest = false;
            material.setUniforms({
                hasFilterBox: 1,
                boxInfo: {
                    type: 1,
                    min: bbox?.min,
                    max: bbox?.max,
                    color: selectColor,
                    matrix: this.boxInvertMatrix.copy(box.matrixWorld).invert(),
                },
            });
            renderer.render(groupPoint, this.camera);
            material.setUniforms({ hasFilterBox: oldHasFilterBox, boxInfo: { type: oldType } });
            material.depthTest = oldDepthTest;

            // this.renderer.render(groupPoint, this.camera);
            // groupPoint.material = oldMaterial;
        }

        if (this.renderBox) {
            const rendered = new Set<string>();
            object3Ds.forEach((box) => {
                if (!box.visible || !this.boxIntersectsImage(box as Box)) return;
                rendered.add(box.uuid);
                this.renderBoxData(box as Box);
            });
            selection3Ds.forEach((box) => {
                if (rendered.has(box.uuid) || !box.visible || !this.boxIntersectsImage(box as Box))
                    return;
                this.renderBoxData(box as Box);
            });
        }
    }

    setContextTransform() {
        let { context } = this.proxy;
        let m = this.proxyTransformMatrix.elements;
        // let m = this.transformMatrix.elements;
        // `matrix(${m[0]},${m[1]},${m[4]},${m[5]},${m[12]},${m[13]})`;
        context.setTransform(m[0], m[1], m[4], m[5], m[12], m[13]);
    }
    renderImage() {
        let { width, height, imgSize } = this;
        let { context } = this.proxy;

        if (!this.img) return;

        this.setContextTransform();
        context.drawImage(this.img, 0, 0, imgSize.x, imgSize.y);
    }

    renderBoxData(box: Box) {
        let { selectionMap, selectColor, highlightColor } = this.pointCloud;

        let color = selectionMap[box.uuid] ? selectColor : box.color;
        let highFlag = this.isHighlight(box);
        color = highFlag ? highlightColor : color;

        this.renderProjectedBoxContour(box, color.getStyle(), box.dashed);
    }

    renderProjectedBoxContour(box: Box, color: string, dashed = false) {
        const { context } = this.proxy;
        const corners = this.getBoxWorldCorners(box);
        const maxX = this.imgSize.x * 1.2;
        const maxY = this.imgSize.y * 1.2;
        const minX = -this.imgSize.x * 0.2;
        const minY = -this.imgSize.y * 0.2;
        const valid = (pos: THREE.Vector2) =>
            Number.isFinite(pos.x) &&
            Number.isFinite(pos.y) &&
            pos.x >= minX &&
            pos.x <= maxX &&
            pos.y >= minY &&
            pos.y <= maxY;
        const world = get(THREE.Vector3);
        const img = get(THREE.Vector3, 1);

        this.setContextTransform();
        context.strokeStyle = color;
        context.lineWidth = 1 / this.getScale();

        context.setLineDash(dashed ? [5, 5] : []);
        boxLineIndices.forEach(([start, end]) => {
            const a = corners[start];
            const b = corners[end];
            const sampleCount = Math.max(Math.ceil(a.distanceTo(b) * 20), 2);
            let drawing = false;

            context.beginPath();
            for (let i = 0; i < sampleCount; i++) {
                world.lerpVectors(a, b, i / (sampleCount - 1));
                this.projectWorldToImg(world, img);

                if (!valid(img)) {
                    drawing = false;
                    continue;
                }

                if (!drawing) {
                    context.moveTo(img.x, img.y);
                    drawing = true;
                } else {
                    context.lineTo(img.x, img.y);
                }
            }
            context.stroke();
        });

        context.setLineDash([]);
    }
}

function getPositions(
    box: THREE.Box3,
    positionsFront: THREE.Vector3[],
    positionsBack: THREE.Vector3[],
) {
    // Keep the 2D projection point order aligned with Box.ts line geometry.
    positionsFront[0].set(box.max.x, box.max.y, box.max.z);
    positionsFront[1].set(box.min.x, box.max.y, box.max.z);
    positionsFront[2].set(box.min.x, box.min.y, box.max.z);
    positionsFront[3].set(box.max.x, box.min.y, box.max.z);

    positionsBack[0].set(box.max.x, box.max.y, box.min.z);
    positionsBack[1].set(box.min.x, box.max.y, box.min.z);
    positionsBack[2].set(box.min.x, box.min.y, box.min.z);
    positionsBack[3].set(box.max.x, box.min.y, box.min.z);
}
