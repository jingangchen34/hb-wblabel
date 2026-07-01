import { IFrame, IFileConfig } from '../type';
import { IImgViewConfig, IUserData } from 'pc-editor';
import DataManager from '../common/DataManager';
import * as THREE from 'three';

export function isMatrixColumnMajor(elements: number[]) {
    let rightZero = elements[3] === 0 && elements[7] === 0 && elements[11] === 0;
    let bottomHasOne = !!elements[12] || !!elements[13] || !!elements[14];
    return rightZero && bottomHasOne;
}

function flatNumberArray(value: any): number[] {
    if (!Array.isArray(value)) return [];
    return value.flat
        ? value.flat(Infinity).map(Number)
        : ([] as number[]).concat(...value).map(Number);
}

function numberValue(value: any) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
}

function firstNumberValue(value: any, keys: string[]) {
    if (!value || typeof value !== 'object') return null;
    for (const key of keys) {
        const n = numberValue(value[key]);
        if (n !== null) return n;
    }
    return null;
}

function vector3Value(value: any) {
    const array = flatNumberArray(value);
    if (array.length >= 3) return array.slice(0, 3);
    if (!value || typeof value !== 'object') return [];

    const x = firstNumberValue(value, ['x', 'tx', '0']);
    const y = firstNumberValue(value, ['y', 'ty', '1']);
    const z = firstNumberValue(value, ['z', 'tz', '2']);
    return x !== null && y !== null && z !== null ? [x, y, z] : [];
}

function quaternionWxyzValue(value: any) {
    const array = flatNumberArray(value);
    if (array.length >= 4) return array.slice(0, 4);
    if (!value || typeof value !== 'object') return [];

    const w = firstNumberValue(value, ['w', 'qw', '0']);
    const x = firstNumberValue(value, ['x', 'qx', '1']);
    const y = firstNumberValue(value, ['y', 'qy', '2']);
    const z = firstNumberValue(value, ['z', 'qz', '3']);
    return w !== null && x !== null && y !== null && z !== null ? [w, x, y, z] : [];
}

function matrixToRowMajor(matrix: THREE.Matrix4) {
    const e = matrix.elements;
    return [
        e[0],
        e[4],
        e[8],
        e[12],
        e[1],
        e[5],
        e[9],
        e[13],
        e[2],
        e[6],
        e[10],
        e[14],
        e[3],
        e[7],
        e[11],
        e[15],
    ];
}

function toMatrix4(elements: number[]) {
    return new THREE.Matrix4().set(...(elements as [
        number, number, number, number,
        number, number, number, number,
        number, number, number, number,
        number, number, number, number,
    ]));
}

function normalizeCameraName(value: any) {
    return `${value || ''}`.toLowerCase().replace(/[^a-z0-9]/g, '');
}

function getCameraToken(value: any) {
    const text = `${value || ''}`;
    const match = text.match(/camera[_-][a-z0-9_]+?(?=_[0-9]{6,}|\.|$)/i);
    return normalizeCameraName(match ? match[0] : text);
}

function getDistortionParameter(info: any) {
    const cameraInternal = info?.cameraInternal || info?.camera_internal;
    const distortion = flatNumberArray(
        info?.distortion_parameter ||
            info?.distortionParameter ||
            info?.distortion_parameters ||
            info?.distortion ||
            info?.D ||
            cameraInternal?.distortion_parameter ||
            cameraInternal?.distortionParameter ||
            cameraInternal?.distortion_parameters ||
            cameraInternal?.distortion ||
            cameraInternal?.D,
    );

    return distortion.length ? distortion.slice(0, 5) : undefined;
}

function getCameraInternal(info: any) {
    const cameraInternal = info?.cameraInternal || info?.camera_internal;
    const distortion = getDistortionParameter(info);
    if (cameraInternal) return distortion && !cameraInternal.distortion
        ? { ...cameraInternal, distortion }
        : cameraInternal;

    const intrinsic = flatNumberArray(
        info?.intrinsic ||
            info?.intrinsics ||
            info?.cameraIntrinsic ||
            info?.camera_intrinsic ||
            info?.cameraMatrix ||
            info?.camera_matrix ||
            info?.cam_K ||
            info?.camK ||
            info?.K,
    );
    if (intrinsic.length >= 9) {
        return {
            fx: intrinsic[0],
            fy: intrinsic[4],
            cx: intrinsic[2],
            cy: intrinsic[5],
            distortion,
        };
    }

    return null;
}

function matrixFromCameraToLidar(info: any) {
    let cameraToLidar =
        info?.cameraToLidar ||
        info?.camera_to_lidar ||
        info?.lidar2camera?.inverse ||
        info?.extrinsic ||
        info?.transform;
    if (cameraToLidar) {
        let elements = flatNumberArray(cameraToLidar);
        if (elements.length === 16) {
            if (info.rowMajor === false || isMatrixColumnMajor(elements)) {
                let matrix = new THREE.Matrix4();
                matrix.elements = elements;
                matrix.transpose();
                elements = matrix.elements;
            }
            return toMatrix4(elements);
        }
    }

    const rotationValue =
        info?.rotation ||
        info?.quaternion ||
        info?.quat ||
        info?.rotation_quaternion ||
        info?.rotation_matrix;
    const rotation = flatNumberArray(rotationValue);
    const translation = vector3Value(
        info?.translation ||
            info?.translation_vector ||
            info?.t ||
            info?.T,
    );
    if (translation.length !== 3) return null;

    const quaternionWxyz = quaternionWxyzValue(rotationValue);
    if (quaternionWxyz.length === 4) {
        const [w, x, y, z] = quaternionWxyz;
        const quaternion = new THREE.Quaternion(x, y, z, w).normalize();
        return new THREE.Matrix4()
            .makeRotationFromQuaternion(quaternion)
            .setPosition(translation[0], translation[1], translation[2]);
    }

    if (rotation.length !== 9) return null;

    return new THREE.Matrix4().set(
        rotation[0],
        rotation[1],
        rotation[2],
        translation[0],
        rotation[3],
        rotation[4],
        rotation[5],
        translation[1],
        rotation[6],
        rotation[7],
        rotation[8],
        translation[2],
        0,
        0,
        0,
        1,
    );
}

export function translateCameraConfig(info: any) {
    let cameraExternal = info?.cameraExternal || info?.camera_external;
    let cameraInternal = getCameraInternal(info);
    let externalIsCameraToLidar = !!cameraExternal;

    const cameraToLidarMatrix = matrixFromCameraToLidar(info);
    if (cameraToLidarMatrix) {
        cameraExternal = matrixToRowMajor(cameraToLidarMatrix.invert());
        externalIsCameraToLidar = false;
    }

    if (!info || !cameraExternal || cameraExternal.length !== 16) return null;

    // to rowMajor
    if (info.rowMajor === false || isMatrixColumnMajor(cameraExternal)) {
        let matrix = new THREE.Matrix4();
        matrix.elements = cameraExternal;
        matrix.transpose();
        cameraExternal = matrix.elements;
    }

    const direction = normalizeCameraName(
        info.externalDirection || info.external_direction || info.cameraExternalDirection,
    );
    if (externalIsCameraToLidar && direction === 'camera_to_lidar') {
        cameraExternal = matrixToRowMajor(
            toMatrix4(cameraExternal).invert(),
        );
    }

    return { cameraExternal, cameraInternal };
}

function normalizeCameraInfo(cameraInfo: any) {
    if (Array.isArray(cameraInfo)) return cameraInfo;
    if (!cameraInfo || typeof cameraInfo !== 'object') return [];

    if (getCameraInternal(cameraInfo) || cameraInfo.cameraExternal || cameraInfo.camera_external) {
        return [cameraInfo];
    }

    return Object.keys(cameraInfo).map((key) => ({
        ...cameraInfo[key],
        __cameraKey: key,
    }));
}

function findCameraInfo(cameraInfo: any[], index: number, config: IImgViewConfig, dirName?: string) {
    const byIndex = cameraInfo[index];
    const imageNames = [config.name, dirName].map(getCameraToken).filter(Boolean);
    const byName = cameraInfo.find((info) => {
        const names = [
            info?.__cameraKey,
            info?.frame_id,
            info?.frameId,
            info?.camera_name,
            info?.cameraName,
            info?.name,
        ]
            .map(getCameraToken)
            .filter(Boolean);

        return imageNames.some((imageName) =>
            names.some((cameraName) => imageName.includes(cameraName) || cameraName.includes(imageName)),
        );
    });

    return byName || byIndex;
}

export function clamRange(v: number, min: number, max: number) {
    return Math.max(Math.min(max, v), min);
}

export function createViewConfig(fileConfig: IFileConfig[], cameraInfo: any[]) {
    cameraInfo = normalizeCameraInfo(cameraInfo);
    let viewConfig = [] as IImgViewConfig[];
    let viewDirNames = [] as string[];
    let pointsUrl = '';
    let labelUrl = '';
    let pointCacheUrl = '';
    const regPointCache = new RegExp(/point(_?)cloud(_?)cache|point(_?)cache/i);
    const regLidar = new RegExp(/point(_?)cloud/i);
    const regLabel = new RegExp(/occ.*label|label/i);
    const regImage = new RegExp(/image/i);
    const regUndistortedImage = new RegExp(/cylindrical|undistort|rectified/i);
    const maxCameraIndex = Math.max(fileConfig.length, cameraInfo.length, 16);
    fileConfig.forEach((e) => {
        if ((regPointCache.test(e.dirName) || /\.xyzl$/i.test(e.name)) && /\.xyzl$/i.test(e.name)) {
            pointCacheUrl = e.url;
        } else if (regLidar.test(e.dirName) && /\.(bin|pcd)$/i.test(e.name)) {
            pointsUrl = e.url;
        } else if (regLabel.test(e.dirName) && /\.label$/i.test(e.name)) {
            labelUrl = e.url;
        } else if (
            regImage.test(e.dirName) &&
            !regUndistortedImage.test(e.dirName) &&
            !regUndistortedImage.test(e.name)
        ) {
            const match = e.dirName.match(/(?:^|[_-])(\d{1,3})$/);
            const parsedIndex = match ? Number.parseInt(match[1], 10) : NaN;
            const index =
                Number.isFinite(parsedIndex) && parsedIndex >= 0 && parsedIndex < maxCameraIndex
                    ? parsedIndex
                    : viewConfig.length;
            const imageConfig = {
                cameraInternal: { fx: 0, fy: 0, cx: 0, cy: 0 },
                cameraExternal: [],
                imgSize: [0, 0],
                imgUrl: e.url,
                name: e.name,
                imgObject: null as any,
            };
            if (index === viewConfig.length) {
                viewConfig.push(imageConfig);
                viewDirNames.push(e.dirName);
            } else {
                viewConfig[index] = imageConfig;
                viewDirNames[index] = e.dirName;
            }
        }
    });
    viewConfig = viewConfig.filter((e) => !!e);
    viewConfig.forEach((config, index) => {
        let info = findCameraInfo(cameraInfo, index, config, viewDirNames[index]);

        let translateInfo = translateCameraConfig(info);
        if (!translateInfo) return;

        config.cameraExternal = translateInfo.cameraExternal;
        config.cameraInternal = translateInfo.cameraInternal;
        config.imgSize = [info.width || info.image_width || config.imgSize[0], info.height || info.image_height || config.imgSize[1]];
        if (!config.projectionType && /fish/i.test(info.camera_model || info.cameraModel || '')) {
            config.projectionType = 'fisheye';
        }
        // config.rowMajor = info.rowMajor;
    });

    // Keep raw camera images visible when calibration exists but is incomplete.
    // Projection only works for views with valid intrinsics/extrinsics.
    const hasProjectableCamera = viewConfig.some((e) => e.cameraExternal.length === 16 && e.cameraInternal);
    viewConfig = hasProjectableCamera
        ? viewConfig.filter((e) => e.cameraExternal.length === 16 && e.cameraInternal)
        : viewConfig;

    return { pointsUrl: pointCacheUrl || pointsUrl, labelUrl: pointCacheUrl ? '' : labelUrl, pointCacheUrl, config: viewConfig };
}

export function rand(start: number, end: number) {
    return (Math.random() * (end - start) + start) | 0;
}

export function empty(value: any) {
    return value === null || value === undefined || value === '';
}

export function queryStr(data: Record<string, any> = {}) {
    let queryArr = [] as string[];
    Object.keys(data).forEach((name) => {
        let value = data[name];
        if (Array.isArray(value)) {
            queryArr.push(`${name}=${value.join(',')}`);
        } else {
            queryArr.push(`${name}=${value}`);
        }
    });

    return queryArr.join('&');
}

export function getTrackObject(dataInfos: IFrame[], dataManager: DataManager) {
    let trackObjects = {} as Record<string, { id: string; name: string }[]>;
    let idMap = {} as Record<string, boolean>;

    let maxNum = 0;
    dataInfos.forEach((data) => {
        let objects = dataManager.getFrameObject(data.id) || [];
        objects.forEach((object) => {
            let userData = object.userData as IUserData;
            let trackName = userData.trackName;
            let trackId = userData.trackId;
            if (!trackName || !trackId) return;

            let trackNumber = parseInt(trackName);
            if (isNaN(trackNumber)) return;

            let id = `${trackName}####${trackId}`;
            if (idMap[id]) return;

            maxNum = Math.max(maxNum, trackNumber);
            if (!trackObjects[trackNumber]) {
                trackObjects[trackNumber] = [];
            }

            trackObjects[trackNumber].push({ id: trackId, name: trackName });
            idMap[id] = true;
        });
    });

    let list = [] as { id: string; name: string }[];

    [...Array(maxNum + 1)].forEach((e, index) => {
        let objects = trackObjects[index];
        if (objects) {
            list.push(...objects);
        }
    });

    return list;
}

export function formatNumDot(str: string | number, precision: number = 2): string {
    str = '' + str;
    let regex = /(?!^)(?=(\d{3})+(\.|$))/g;
    str.replace(regex, ',');

    if (precision) {
        return (+str).toFixed(precision);
    } else {
        return str;
    }
}

export function formatNumStr(str: string | number, precision: number = 2): string {
    str = '' + str;
    if (precision) {
        return (+str).toFixed(precision);
    } else {
        return str;
    }
}

export function pickAttrs(obj: any, attrs: string[]) {
    let newObj = {};
    attrs.forEach((attr) => {
        newObj[attr] = obj[attr];
    });
    return newObj;
}
