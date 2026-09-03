import { defHttp } from '/@/utils/http/axios';

const base = '/preAnnotation';

export const createPreAnnotationApi = (params: any) =>
  defHttp.post<number>({ url: `${base}/create`, params });

export const getPreAnnotationPageApi = (params: { pageNo?: number; pageSize?: number }) =>
  defHttp.get<any>({ url: `${base}/page`, params });

export const commitPreAnnotationApi = (id: number) =>
  defHttp.post<any>({ url: `${base}/${id}/commit` });

export const deletePreAnnotationApi = (id: number) =>
  defHttp.post<void>({ url: `${base}/delete/${id}` });
