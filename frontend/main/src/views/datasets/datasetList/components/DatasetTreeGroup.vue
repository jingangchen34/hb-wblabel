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

    <div v-if="folders.length" class="folder-grid">
      <button v-for="folder in folders" :key="folder.name" class="folder-item" @click="openFolder(folder.name)">
        <Icon icon="ant-design:folder-outlined" size="22" />
        <span class="folder-name">{{ folder.name }}</span>
        <span class="folder-count">{{ folder.count }}</span>
      </button>
    </div>

    <div v-if="datasets.length" class="dataset-grid">
      <ListCard
        v-for="item in datasets"
        :key="item.id"
        class="listcard"
        :data="item"
        @fetchList="$emit('fetchList')"
        @closeCreateModal="$emit('closeCreateModal')"
      />
    </div>
  </div>
</template>

<script lang="ts" setup>
  import { computed, ref } from 'vue';
  import Icon from '/@/components/Icon';
  import { DatasetListItem } from '/@/api/business/model/datasetModel';
  import ListCard from './DatasetListCard.vue';

  const props = defineProps<{
    list: DatasetListItem[];
  }>();

  defineEmits(['fetchList', 'closeCreateModal']);

  const currentPath = ref<string[]>([]);

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

  const openFolder = (name: string) => {
    currentPath.value = [...currentPath.value, name];
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
    padding: 2px 6px 20px;
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

    &:hover {
      border-color: #57ccef;
      background: #f7fdff;
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
