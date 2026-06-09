import { IDataResource, IFrame, IFileConfig, PointAttr, PointAttrValue } from '../type';
import { LabelBinLoader, PCDLoader } from 'pc-render';
import Editor from '../Editor';
// import * as api from '../api';
import * as utils from '../utils';
import Event from '../config/event';
import { IImgViewConfig } from 'pc-editor';

export type LoadMode = 'current' | 'near_2' | 'all';
export class ResourceLoader {
    manual: boolean = false;
    data: IFrame;
    dataResource: DataResource;
    promise: Promise<IDataResource> = {} as Promise<IDataResource>;
    constructor(dataResource: DataResource, data: IFrame) {
        this.data = data;
        this.dataResource = dataResource;
        this.handleProgress = this.handleProgress.bind(this);
    }
    remove() {
        this.dataResource.loaders = this.dataResource.loaders.filter(
            (e) => e.data.id !== this.data.id,
        );

        const delay = this.manual ? 250 : 500;
        window.setTimeout(() => {
            this.dataResource.load();
        }, delay);
    }
    get() {
        return this.promise;
    }
    load() {
        let promise: Promise<IDataResource> = new Promise(async (resolve, reject) => {
            const startedAt = performance.now();
            const logStep = (step: string, stepStartedAt: number) => {
                console.log(
                    `[pc-perf] frame=${this.data.id} step=${step} ms=${Math.round(
                        performance.now() - stepStartedAt,
                    )} total=${Math.round(performance.now() - startedAt)}`,
                );
            };
            try {
                let config = this.dataResource.dataMap[this.data.id];
                this.data.loadState = 'loading';

                this.dataResource.editor.dispatchEvent({
                    type: Event.RESOURCE_LOAD_LOADING,
                    data: this.data,
                });

                if (!config) {
                    const stepStartedAt = performance.now();
                    config = await this.dataResource.loadDataConfig(this.data);
                    logStep('loadDataConfig', stepStartedAt);
                }

                // test resource
                // if (import.meta.env.DEV) {
                //     config.pointsUrl = '/case-padaset/00.pcd';
                // }

                const loadPointsStartedAt = performance.now();
                let pointsData = await this.dataResource.loadPoints(
                    config.pointsUrl,
                    this.handleProgress,
                    {
                        labelUrl: config.labelUrl,
                        pointCacheUrl: config.pointCacheUrl,
                        binPointDim: config.binPointDim,
                        labelColorMap: config.labelColorMap,
                    },
                );
                logStep('loadPoints', loadPointsStartedAt);

                const pointInfoStartedAt = performance.now();
                let pointsInfo = this.dataResource.calculatePointInfo(pointsData);
                logStep('calculatePointInfo', pointInfoStartedAt);

                config.time = Date.now();
                config.pointsData = pointsData;
                config.ground = pointsInfo.ground;
                config.intensityRange = pointsInfo.intensityRange;

                const setResourceStartedAt = performance.now();
                this.dataResource.setResource(this.data, config);
                logStep('setResource', setResourceStartedAt);
                const imagePromise = this.manual && config.viewConfig.length > 0
                    ? this.dataResource.loadImage(config.viewConfig, this.data.id + '')
                    : Promise.resolve();
                imagePromise.then(() => {
                    if (this.dataResource.editor.getCurrentFrame()?.id === this.data.id) {
                        this.dataResource.editor.viewManager.setImgViews(config.viewConfig);
                    }
                }).catch((error) => {
                    console.warn(`load image: ${this.data.id} err`, error);
                });

                console.log(`load resource: ${this.data.id} completed`);
                this.data.loadState = 'complete';
                this.remove();

                this.dataResource.editor.dispatchEvent({
                    type: Event.RESOURCE_LOAD_COMPLETE,
                    data: this.data,
                });
                resolve(config);
            } catch (e) {
                console.log(`load resource: ${this.data.id} err`);
                this.data.loadState = 'error';
                this.remove();
                this.dataResource.editor.dispatchEvent({
                    type: Event.RESOURCE_LOAD_ERROR,
                    data: this.data,
                });
                reject(e);
            }
        });

        this.promise = promise;
    }
    handleProgress(percent: number) {
        this.onProgress(percent);
    }
    onProgress(percent: number) {
        // console.log(percent);
    }
}

export default class DataResource {
    loadMax: number = 500;
    loadMode: LoadMode = 'current';
    editor: Editor;
    dataMap: Record<string, IDataResource> = {};
    loaders: ResourceLoader[] = [];
    pointsLoader: PCDLoader = new PCDLoader();
    labelBinLoader: LabelBinLoader = new LabelBinLoader();
    constructor(editor: Editor) {
        this.editor = editor;
    }

    clear() {
        this.dataMap = {};
        this.loaders = [];
    }

    async loadDataConfig(data: IFrame) {
        return await this.editor.businessManager.loadFrameConfig(data);
    }

    async loadImage(viewConfigs: IImgViewConfig[], frameId?: string) {
        const startedAt = performance.now();
        let requests = [] as Promise<HTMLImageElement | null>[];

        viewConfigs.forEach((config) => {
            if (!config.imgObject) {
                requests.push(createRequest(config));
            }
        });

        if (requests.length) {
            await Promise.all(requests);
        }

        console.log(
            `[pc-perf] frame=${frameId || ''} step=loadImage ms=${Math.round(
                performance.now() - startedAt,
            )} images=${requests.length}`,
        );

        if (viewConfigs.filter((e) => !e.imgObject).length > 0) throw 'load image error';

        function createRequest(config: IImgViewConfig): Promise<HTMLImageElement | null> {
            return new Promise((resolve, reject) => {
                let img = document.createElement('img') as HTMLImageElement;
                img.src = config.imgUrl;
                img.onload = () => {
                    config.imgObject = img;
                    config.imgSize = [img.naturalWidth, img.naturalHeight];
                    resolve(img);
                };
                img.onerror = () => {
                    resolve(null);
                };
                img.onabort = () => {
                    resolve(null);
                };
            });
        }
    }
    setGround(ground: number, frameId: string) {
        const source = this.dataMap[frameId];
        if (source.pointsData) {
            source.ground = ground;
        }
    }
    calculatePointInfo(data: Record<PointAttr, PointAttrValue>) {
        let position = data.position || [];
        let intensity = data.intensity || [];

        let intensityRange = undefined;
        let ground = 0;
        if (position.length > 0) ground = utils.getPositionGround(position as any);
        if (intensity.length > 0) {
            let min = Infinity;
            let max = -Infinity;
            for (let i = 0; i < intensity.length; i++) {
                min = Math.min(intensity[i], min);
                max = Math.max(intensity[i], max);
                intensityRange = [min, max] as [number, number];
            }
        }
        return { ground, intensityRange };
    }

    async loadPoints(
        pointsUrl: string,
        onProgress?: (percent: number) => void,
        option?: Pick<IDataResource, 'labelUrl' | 'pointCacheUrl' | 'binPointDim' | 'labelColorMap'>,
    ): Promise<any> {
        return new Promise((resolve, reject) => {
            const onLoad = (data: any) => resolve(data);
            const onProgressInner = (e: any) => {
                if (onProgress) onProgress(e.loaded / e.total);
            };
            const onError = (error?: any) => reject(error);
            if (option?.pointCacheUrl || /\.xyzl($|\?)/i.test(pointsUrl)) {
                this.labelBinLoader.load(pointsUrl, onLoad, onProgressInner, onError, {
                    pointCache: true,
                    colorMap: option?.labelColorMap,
                });
            } else if (option?.labelUrl || /\.bin($|\?)/i.test(pointsUrl)) {
                this.labelBinLoader.load(pointsUrl, onLoad, onProgressInner, onError, {
                    labelUrl: option.labelUrl,
                    pointDim: option.binPointDim || [6, 7, 4],
                    colorMap: option.labelColorMap,
                });
            } else {
                this.pointsLoader.load(pointsUrl, onLoad, onProgressInner, onError);
            }
        });
    }

    setLoadMode(mode: LoadMode) {
        this.loadMode = mode;
        this.editor.state.config.autoLoad = mode === 'all';
    }

    load(fromIndex?: number) {
        let { frameIndex } = this.editor.state;
        if (this.loaders.length > 0) return;

        let loaderN = Object.keys(this.dataMap).filter((e) => this.dataMap[e]).length;
        if (loaderN > this.loadMax) return;

        fromIndex = fromIndex || frameIndex;
        let data = this.getNext(fromIndex < 0 ? 0 : fromIndex);

        if (!data) {
            console.log('load complete');
            return;
        }

        this.loadNext(data);
    }

    getNext(fromIndex: number) {
        let { frames } = this.editor.state;

        let hasLoader = {} as Record<string, boolean>;
        this.loaders.forEach((e) => {
            hasLoader[e.data.id] = true;
        });

        let nextDataIndex = -1;
        let maxWeight = -1;

        for (let i = 0; i < frames.length; i++) {
            let data = frames[i];
            if (data.loadState !== '') continue;

            let isNear2 = Math.abs(i - fromIndex) <= 1;
            let isFuture = i >= fromIndex;
            let weight = isFuture ? 100000 - (i - fromIndex) : 1000 - (fromIndex - i);
            weight = isNear2 ? Infinity - Math.abs(i - fromIndex) : weight;
            if (
                this.loadMode === 'all' ||
                (this.loadMode === 'near_2' && isNear2) ||
                (this.loadMode === 'current' && i === fromIndex)
            ) {
                if (weight > maxWeight) {
                    maxWeight = weight;
                    nextDataIndex = i;
                }
            }
        }

        console.log('nextDataIndex', nextDataIndex);

        if (nextDataIndex < 0) return null;
        else return frames[nextDataIndex];
    }

    getResource(data: IFrame) {
        let resource = this.dataMap[data.id];
        if (resource) {
            resource.time = Date.now();
            return resource;
        }
        return this.loadNext(data, true);
    }

    setResource(data: IFrame, resource: IDataResource) {
        this.dataMap[data.id] = resource;
    }

    loadNext(data: IFrame, manual: boolean = false) {
        let oldLoader = this.loaders.find((e) => e.data.id === data.id);
        if (this.loaders.length > 0 && oldLoader) return oldLoader;

        let loader = new ResourceLoader(this, data);
        loader.manual = manual;
        this.loaders.push(loader);
        loader.load();

        return loader;
    }
}
