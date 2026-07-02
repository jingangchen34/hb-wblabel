<template>
  <div class="dataset-browser">
    <div class="browser-breadcrumb">
      <button class="crumb" :class="{ active: currentPath.length === 0 }" @click="goToLevel(0)">
        Datasets
      </button>
      <template v-for="(part, index) in currentPath" :key="`${part}-${index}`">
        <span class="separator">/</span>
        <button class="crumb" :class="{ active: index === currentPath.length - 1 }" @click="goToLevel(index + 1)">
          {{ part }}
        </button>
      </template>
    </div>

    <div v-if="currentPath.length" class="back-row" @click="goUp">
      <Icon icon="ant-design:arrow-left-outlined" size="16" />
      <span>Back</span>
    </div>

    <div v-if="folders.length" class="folder-grid" :class="{ 'source-grid': currentPath.length === 0 }">
      <button
        v-for="folder in folders"
        :key="folder.name"
        class="folder-item"
        :class="{ 'source-item': currentPath.length === 0 }"
        @click="openFolder(folder.name)"
      >
        <template v-if="currentPath.length === 0">
          <span class="source-icon" :class="getFolderMeta(folder.name).theme">
            <Icon :icon="getFolderMeta(folder.name).icon" size="24" />
          </span>
          <span class="source-main">
            <span class="source-title-row">
              <span class="source-title">{{ getFolderMeta(folder.name).title }}</span>
              <span class="source-badge" :class="getFolderMeta(folder.name).theme">
                {{ getFolderMeta(folder.name).badge }}
              </span>
            </span>
            <span class="source-description">{{ getFolderMeta(folder.name).description }}</span>
            <span class="source-footer">
              <span class="source-path">{{ folder.name }}</span>
              <span
                v-if="getFolderMeta(folder.name).statisticsEnabled"
                class="source-action"
                @click.stop="openStatistics(folder.name)"
              >
                &#x7edf;&#x8ba1;/&#x603b;&#x89c8;
              </span>
            </span>
          </span>
          <span class="source-count">
            <strong>{{ folder.count }}</strong>
            <span>&#x6570;&#x636e;&#x96c6;</span>
          </span>
          <Icon class="source-arrow" icon="ant-design:arrow-right-outlined" size="16" />
        </template>
        <template v-else>
          <Icon icon="ant-design:folder-outlined" size="22" />
          <span class="folder-name">{{ folder.name }}</span>
          <span class="folder-count">{{ folder.count }}</span>
        </template>
      </button>
    </div>

    <div v-if="datasets.length" class="dataset-grid">
      <ListCard
        v-for="item in datasets"
        :key="item.id"
        class="listcard"
        :data="item"
        :displayName="getDisplayName(item.name)"
        @fetchList="$emit('fetchList')"
        @closeCreateModal="$emit('closeCreateModal')"
      />
    </div>
  </div>
</template>

<script lang="ts" setup>
  import { computed, onMounted, ref, watch } from 'vue';
  import Icon from '/@/components/Icon';
  import { DatasetListItem } from '/@/api/business/model/datasetModel';
  import { RouteChildEnum } from '/@/enums/routeEnum';
  import { useGo } from '/@/hooks/web/usePage';
  import ListCard from './DatasetListCard.vue';

  const props = defineProps<{
    list: DatasetListItem[];
  }>();

  defineEmits(['fetchList', 'closeCreateModal']);

  const go = useGo();
  const currentPath = ref<string[]>([]);
  const storageKey = 'x1-dataset-browser-current-path';
  const folderMetaMap: Record<
    string,
    {
      title: string;
      description: string;
      badge: string;
      icon: string;
      theme: string;
      statisticsEnabled?: boolean;
    }
  > = {
    fusiondet_data: {
      title: '\u6d77\u535a\u91c7\u96c6\u6570\u636e',
      description: 'FusionDet \u91c7\u96c6\u6765\u6e90\uff0c\u5df2\u8fdb\u5165\u6570\u636e\u96c6\u7ba1\u7406\u6d41\u7a0b',
      badge: '\u6d77\u535a',
      icon: 'ant-design:database-outlined',
      theme: 'theme-cyan',
      statisticsEnabled: true,
    },
    new_clip: {
      title: '\u65b0\u91c7\u96c6\u5f85\u9001\u6807',
      description: '\u521a\u91c7\u96c6\u5b8c\u6210\uff0c\u6682\u672a\u9001\u6807\u7684\u6570\u636e\u6682\u5b58\u533a',
      badge: '\u5f85\u9001\u6807',
      icon: 'ant-design:inbox-outlined',
      theme: 'theme-amber',
    },
    xinchi_data: {
      title: '\u661f\u9a70\u91c7\u96c6\u6570\u636e',
      description: '\u661f\u9a70\u91c7\u96c6\u6765\u6e90\uff0c\u6309\u76ee\u5f55\u5f52\u6863\u7ba1\u7406',
      badge: '\u661f\u9a70',
      icon: 'ant-design:deployment-unit-outlined',
      theme: 'theme-violet',
    },
  };

  const getDatasetPathParts = (datasetName: string) =>
    datasetName
      .split('/')
      .map((part) => part.trim())
      .filter(Boolean);

  const startsWithCurrentPath = (parts: string[]) =>
    currentPath.value.every((part, index) => parts[index] === part);

  const datasets = computed(() =>
    props.list.filter((dataset) => {
      const parts = getDatasetPathParts(dataset.name);
      if (!startsWithCurrentPath(parts)) return false;
      return parts.length <= currentPath.value.length + 1;
    }),
  );

  const getDisplayName = (datasetName: string) => {
    const parts = getDatasetPathParts(datasetName);
    return parts[parts.length - 1] || datasetName;
  };

  const getFolderMeta = (folderName: string) =>
    folderMetaMap[folderName] || {
      title: folderName,
      description: '\u6309\u91c7\u96c6\u76ee\u5f55\u5f52\u6863\u7684\u6570\u636e\u96c6',
      badge: '\u76ee\u5f55',
      icon: 'ant-design:folder-open-outlined',
      theme: 'theme-gray',
    };

  const folders = computed(() => {
    const counts = new Map<string, number>();
    props.list.forEach((dataset) => {
      const parts = getDatasetPathParts(dataset.name);
      if (!startsWithCurrentPath(parts)) return;
      const next = parts[currentPath.value.length];
      if (next && parts.length > currentPath.value.length + 1) {
        counts.set(next, (counts.get(next) || 0) + 1);
      }
    });
    return Array.from(counts.entries())
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => a.name.localeCompare(b.name));
  });

  onMounted(() => {
    try {
      const stored = sessionStorage.getItem(storageKey);
      if (stored) {
        currentPath.value = JSON.parse(stored);
      }
    } catch (error) {
      currentPath.value = [];
    }
  });

  watch(
    currentPath,
    (value) => {
      sessionStorage.setItem(storageKey, JSON.stringify(value));
    },
    { deep: true },
  );

  const openFolder = (name: string) => {
    currentPath.value = [...currentPath.value, name];
  };

  const openStatistics = (name: string) => {
    go(`${RouteChildEnum.DATASETS_SOURCE_OVERVIEW}?source=${encodeURIComponent(name)}`);
  };

  const goUp = () => {
    currentPath.value = currentPath.value.slice(0, -1);
  };

  const goToLevel = (level: number) => {
    currentPath.value = currentPath.value.slice(0, level);
  };
</script>

<style lang="less" scoped>
  .dataset-browser {
    width: 100%;
    padding: 2px 8px 24px;
  }

  .browser-breadcrumb {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    min-height: 36px;
    margin: 2px 0 14px;
  }

  .crumb {
    border: 0;
    background: transparent;
    color: #4b5563;
    font-size: 14px;
    cursor: pointer;
    padding: 4px 2px;

    &.active {
      color: #111827;
      font-weight: 600;
      cursor: default;
    }
  }

  .separator {
    color: #9ca3af;
  }

  .back-row {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 30px;
    margin-bottom: 12px;
    color: #4f46e5;
    cursor: pointer;
  }

  .folder-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 12px;
    margin-bottom: 18px;

    &.source-grid {
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 16px;
      margin-top: 2px;
      margin-bottom: 24px;
    }
  }

  .folder-item {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 48px;
    padding: 0 14px;
    border: 1px solid #d9e2e7;
    border-radius: 6px;
    background: #fff;
    color: #111827;
    cursor: pointer;
    text-align: left;
    transition: all 0.2s ease;

    &:hover {
      border-color: #57ccef;
      background: #f7fdff;
    }

    &.source-item {
      position: relative;
      min-height: 132px;
      height: auto;
      gap: 14px;
      padding: 18px 18px 16px;
      border: 1px solid #d8e8ee;
      border-radius: 8px;
      background: linear-gradient(180deg, #ffffff 0%, #fbfeff 100%);
      box-shadow: 0 8px 20px rgba(18, 38, 63, 0.05);

      &:hover {
        border-color: #57ccef;
        box-shadow: 0 12px 28px rgba(18, 38, 63, 0.1);
        transform: translateY(-1px);

        .source-arrow {
          opacity: 1;
          transform: translateX(2px);
        }
      }
    }
  }

  .folder-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .folder-count {
    min-width: 22px;
    height: 18px;
    padding: 0 6px;
    border-radius: 9px;
    background: #eef2ff;
    color: #4f46e5;
    font-size: 12px;
    line-height: 18px;
    text-align: center;
  }

  .source-icon {
    width: 48px;
    height: 48px;
    border-radius: 8px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .source-main {
    min-width: 0;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .source-title-row,
  .source-footer {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    flex-wrap: wrap;
  }

  .source-title {
    color: #111827;
    font-size: 17px;
    font-weight: 700;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .source-badge {
    flex-shrink: 0;
    height: 22px;
    padding: 0 8px;
    border-radius: 11px;
    font-size: 12px;
    line-height: 22px;
    font-weight: 600;
  }

  .source-description {
    color: #52616d;
    font-size: 13px;
    line-height: 19px;
  }

  .source-path {
    max-width: 100%;
    padding: 3px 8px;
    border-radius: 6px;
    background: #f3f6f8;
    color: #6b7280;
    font-size: 12px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .source-action {
    height: 24px;
    padding: 0 9px;
    border-radius: 6px;
    background: #e8f8fb;
    color: #0e7490;
    font-size: 12px;
    line-height: 24px;
    font-weight: 600;
    cursor: pointer;

    &:hover {
      background: #d3f0f6;
    }
  }

  .source-count {
    width: 62px;
    height: 62px;
    border-radius: 8px;
    background: #f7fafc;
    border: 1px solid #edf2f5;
    display: inline-flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: #6b7280;
    flex-shrink: 0;

    strong {
      color: #111827;
      font-size: 20px;
      line-height: 22px;
    }

    span {
      margin-top: 3px;
      font-size: 12px;
    }
  }

  .source-arrow {
    color: #8aa0ad;
    opacity: 0;
    transition: all 0.2s ease;
    flex-shrink: 0;
  }

  .theme-cyan {
    &.source-icon {
      color: #0e7490;
      background: #e8f8fb;
    }

    &.source-badge {
      color: #0e7490;
      background: #e8f8fb;
    }
  }

  .theme-amber {
    &.source-icon {
      color: #a16207;
      background: #fff7df;
    }

    &.source-badge {
      color: #a16207;
      background: #fff7df;
    }
  }

  .theme-violet {
    &.source-icon {
      color: #6d28d9;
      background: #f1ecff;
    }

    &.source-badge {
      color: #6d28d9;
      background: #f1ecff;
    }
  }

  .theme-gray {
    &.source-icon {
      color: #4b5563;
      background: #f3f6f8;
    }

    &.source-badge {
      color: #4b5563;
      background: #f3f6f8;
    }
  }

  .dataset-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(292px, 292px));
    gap: 18px;
  }

  .listcard {
    height: 264px;
    padding: 0;
  }
</style>
