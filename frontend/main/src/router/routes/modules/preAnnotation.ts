import type { AppRouteModule } from '/@/router/types';
import { LAYOUT } from '/@/router/constant';

const route: AppRouteModule = {
  path: '/pre-annotation',
  name: 'PreAnnotation',
  component: LAYOUT,
  redirect: '/pre-annotation/list',
  meta: {
    hideChildrenInMenu: true,
    icon: 'models|svg',
    title: '预标注',
    orderNo: 9,
  },
  children: [{
    path: 'list',
    name: 'PreAnnotationList',
    component: () => import('/@/views/preAnnotation/index.vue'),
    meta: { title: '预标注', hideMenu: true },
  }],
};

export default route;
