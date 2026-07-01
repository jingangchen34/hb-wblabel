<template>
  <div class="dataset-tree">
    <div v-for="node in nodes" :key="node.path" class="tree-node">
      <div v-if="node.children.length || node.datasets.length" class="tree-title" :style="indentStyle(level)">
        <Icon icon="ant-design:folder-open-outlined" size="16" />
        <span>{{ node.name }}</span>
        <span class="tree-count">{{ countDatasets(node) }}</span>
      </div>
      <DatasetTreeGroup
        v-if="node.children.length"
        :nodes="node.children"
        :level="level + 1"
        @fetchList="$emit('fetchList')"
        @closeCreateModal="$emit('closeCreateModal')"
      />
      <div v-if="node.datasets.length" class="tree-cards" :style="indentStyle(level + 1)">
        <ListCard
          v-for="item in node.datasets"
          :key="item.id"
          class="listcard"
          :data="item"
          @fetchList="$emit('fetchList')"
          @closeCreateModal="$emit('closeCreateModal')"
        />
      </div>
    </div>
  </div>
</template>

<script lang="ts" setup>
  import Icon from '/@/components/Icon';
  import { DatasetListItem } from '/@/api/business/model/datasetModel';
  import ListCard from './DatasetListCard.vue';

  type DatasetTreeNode = {
    name: string;
    path: string;
    children: DatasetTreeNode[];
    datasets: DatasetListItem[];
  };

  withDefaults(
    defineProps<{
      nodes: DatasetTreeNode[];
      level?: number;
    }>(),
    { level: 0 },
  );

  defineEmits(['fetchList', 'closeCreateModal']);

  const indentStyle = (level = 0) => ({ paddingLeft: `${level * 18}px` });

  const countDatasets = (node: DatasetTreeNode): number =>
    node.datasets.length + node.children.reduce((total, child) => total + countDatasets(child), 0);
</script>

<style lang="less" scoped>
  .dataset-tree {
    width: 100%;
  }

  .tree-node {
    width: 100%;
  }

  .tree-title {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 32px;
    margin: 8px 0 6px;
    color: #1f2937;
    font-size: 14px;
    font-weight: 600;
  }

  .tree-count {
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

  .tree-cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 16px;
    margin-bottom: 12px;
  }

  .listcard {
    min-height: 260px;
  }
</style>
