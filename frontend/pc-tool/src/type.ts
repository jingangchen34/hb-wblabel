export interface IUser {
    id: string;
    nickname: string;
    email?: string;
    status?: string;
    username?: string;
}

export interface IBSState {
    query: Record<string, string>;
    // flow
    saving: boolean;
    validing: boolean;
    submitting: boolean;
    modifying: boolean;
    recordId: string;
    // dataset info
    datasetId: string;
    datasetName: string;
    datasetType: string;
    seriesFrameId?: string;
    seriesFrameName?: string;
    seriesFrameList?: ISeriesFrameInfo[];
    //
    user: IUser;
}

export interface ISeriesFrameInfo {
    id: string;
    firstDataId?: string;
    name: string;
}

export type IAction = 'save' | 'close';

export interface IOption {
    label: string;
    value: string;
}

export interface IPageHandler {
    init: () => void;
    onAction: (e: IAction) => void;
}
