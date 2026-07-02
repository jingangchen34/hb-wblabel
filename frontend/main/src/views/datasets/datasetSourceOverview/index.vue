<template>
  <div class="source-overview" v-loading="loading">
    <div class="header-bar">
      <div>
        <div class="eyebrow">{{ sourceTitle }}</div>
        <div class="title">&#x7edf;&#x8ba1;&#x603b;&#x89c8;</div>
      </div>
      <Button @click="goBack">
        <template #icon><Icon icon="ant-design:arrow-left-outlined" /></template>
        &#x8fd4;&#x56de;&#x6570;&#x636e;&#x96c6;
      </Button>
    </div>

    <div class="summary-row">
      <div class="summary-item">
        <span>&#x6570;&#x636e;&#x96c6;</span>
        <strong>{{ formatNumber(statistics.datasetAmount) }}</strong>
      </div>
      <div class="summary-item">
        <span>Clip</span>
        <strong>{{ formatNumber(statistics.clipAmount) }}</strong>
      </div>
      <div class="summary-item">
        <span>&#x5df2;&#x6807;&#x6ce8;&#x5e27;</span>
        <strong>{{ formatNumber(statistics.annotatedDataAmount) }}</strong>
      </div>
      <div class="summary-item">
        <span>&#x7c7b;&#x522b;&#x5bf9;&#x8c61;</span>
        <strong>{{ formatNumber(totalObjects) }}</strong>
      </div>
    </div>

    <div class="content-grid">
      <div class="mine-list">
        <div class="section-title">&#x77ff;&#x533a;</div>
        <button
          class="mine-row"
          :class="{ active: selectedMineName === allMinesKey }"
          @click="selectedMineName = allMinesKey"
        >
          <span class="mine-name">{{ allMinesText }}</span>
          <span class="mine-count">{{ formatNumber(totalObjects) }}</span>
        </button>
        <button
          v-for="mine in statistics.mineUnits"
          :key="mine.mineName"
          class="mine-row"
          :class="{ active: mine.mineName === selectedMineName }"
          @click="selectedMineName = mine.mineName"
        >
          <span class="mine-name">{{ mine.mineName }}</span>
          <span class="mine-count">{{ formatNumber(getMineObjectCount(mine)) }}</span>
        </button>
      </div>

      <div class="detail-panel">
        <div class="panel-head">
          <div>
            <div class="section-title">{{ selectedTitle }}</div>
            <div class="subtle">
              {{ formatNumber(selectedDatasetAmount) }} &#x4e2a;&#x6570;&#x636e;&#x96c6; &middot;
              {{ formatNumber(selectedClipAmount) }} &#x4e2a; clip &middot;
              {{ formatNumber(selectedAnnotatedDataAmount) }} &#x5df2;&#x6807;&#x6ce8;&#x5e27;
            </div>
          </div>
        </div>

        <div class="stats-columns">
          <div class="stats-block">
            <div class="block-title">&#x7c7b;&#x522b;&#x6570;&#x91cf;</div>
            <ChartEmpty v-if="!selectedClassUnits.length" tip="No Classes" class="empty" />
            <div v-else class="bar-list">
              <div v-for="item in selectedClassUnits" :key="item.className" class="bar-row">
                <div class="bar-label">
                  <span class="dot" :style="{ backgroundColor: item.color || '#57ccef' }"></span>
                  <span>{{ item.className || 'No class' }}</span>
                </div>
                <div class="bar-track">
                  <span class="bar-fill" :style="{ width: getClassWidth(item.objectAmount) }"></span>
                </div>
                <strong>{{ formatNumber(item.objectAmount) }}</strong>
              </div>
            </div>
          </div>

          <div class="stats-block">
            <div class="block-title">Clip &#x5c5e;&#x6027;&#x6570;&#x91cf;</div>
            <ChartEmpty v-if="!selectedAttributeUnits.length" tip="No Attributes" class="empty" />
            <div v-else class="bar-list">
              <div
                v-for="item in selectedAttributeUnits"
                :key="`${item.category}-${item.subType}`"
                class="bar-row"
              >
                <div class="bar-label">
                  <span class="attribute-tag">{{ item.category }}</span>
                  <span>{{ item.subType }}</span>
                </div>
                <div class="bar-track attribute">
                  <span class="bar-fill" :style="{ width: getAttributeWidth(item.clipAmount) }"></span>
                </div>
                <strong>{{ formatNumber(item.clipAmount) }}</strong>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts" setup>
  import { computed, onMounted, reactive, ref } from 'vue';
  import { Button } from 'ant-design-vue';
  import { useRoute } from 'vue-router';
  import { useGo } from '/@/hooks/web/usePage';
  import { RouteEnum } from '/@/enums/routeEnum';
  import Icon from '/@/components/Icon';
  import ChartEmpty from '../datasetOverview/components/ChartEmpty.vue';
  import { getDatasetSourceStatisticsApi } from '/@/api/business/dataset';
  import type {
    DatasetSourceAttributeUnit,
    DatasetSourceMineUnit,
    DatasetSourceStatistics,
  } from '/@/api/business/dataset';

  const route = useRoute();
  const go = useGo();
  const loading = ref(false);
  const allMinesKey = '__all__';
  const selectedMineName = ref(allMinesKey);
  const allMinesText = '\u5168\u90e8\u77ff\u533a';
  const source = computed(() => String(route.query.source || 'fusiondet_data'));
  const sourceTitle = computed(() =>
    source.value === 'fusiondet_data' ? '\u6d77\u535a\u91c7\u96c6\u6570\u636e' : source.value,
  );

  const statistics = reactive<DatasetSourceStatistics>({
    sourceName: source.value,
    datasetAmount: 0,
    clipAmount: 0,
    annotatedDataAmount: 0,
    classTotals: [],
    mineUnits: [],
  });

  const totalObjects = computed(() =>
    statistics.classTotals.reduce((total, item) => total + (item.objectAmount || 0), 0),
  );

  const selectedMine = computed(() =>
    statistics.mineUnits.find((item) => item.mineName === selectedMineName.value),
  );
  const selectedTitle = computed(() => selectedMine.value?.mineName || allMinesText);
  const selectedDatasetAmount = computed(() => selectedMine.value?.datasetAmount ?? statistics.datasetAmount);
  const selectedClipAmount = computed(() => selectedMine.value?.clipAmount ?? statistics.clipAmount);
  const selectedAnnotatedDataAmount = computed(() =>
    selectedMine.value?.annotatedDataAmount ?? statistics.annotatedDataAmount,
  );
  const attributeTotals = computed(() => {
    const attributeMap = new Map<string, DatasetSourceAttributeUnit>();
    statistics.mineUnits.forEach((mine) => {
      mine.attributeUnits.forEach((item) => {
        const key = `${item.category}-${item.subType}`;
        const current = attributeMap.get(key);
        if (current) {
          current.clipAmount += item.clipAmount || 0;
          return;
        }
        attributeMap.set(key, { ...item, clipAmount: item.clipAmount || 0 });
      });
    });
    return Array.from(attributeMap.values()).sort((a, b) => b.clipAmount - a.clipAmount);
  });

  const selectedClassUnits = computed(() => selectedMine.value?.classUnits || statistics.classTotals);
  const selectedAttributeUnits = computed(() => selectedMine.value?.attributeUnits || attributeTotals.value);
  const maxClassAmount = computed(() =>
    Math.max(...selectedClassUnits.value.map((item) => item.objectAmount || 0), 1),
  );
  const maxAttributeAmount = computed(() =>
    Math.max(...selectedAttributeUnits.value.map((item) => item.clipAmount || 0), 1),
  );

  const fetchStatistics = async () => {
    loading.value = true;
    try {
      const res = await getDatasetSourceStatisticsApi({ source: source.value });
      Object.assign(statistics, res);
      selectedMineName.value = allMinesKey;
    } finally {
      loading.value = false;
    }
  };

  const getMineObjectCount = (mine: DatasetSourceMineUnit) =>
    mine.classUnits.reduce((total, item) => total + (item.objectAmount || 0), 0);

  const getClassWidth = (amount: number) => `${Math.max(4, (amount / maxClassAmount.value) * 100)}%`;
  const getAttributeWidth = (amount: number) => `${Math.max(4, (amount / maxAttributeAmount.value) * 100)}%`;
  const formatNumber = (value: number) => new Intl.NumberFormat('zh-CN').format(value || 0);
  const goBack = () => go(`${RouteEnum.DATASETS}/list`);

  onMounted(fetchStatistics);
</script>

<style lang="less" scoped>
  .source-overview {
    height: 100%;
    padding: 18px 22px 24px;
    overflow: auto;
    background: #eefbfc;
  }

  .header-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
  }

  .eyebrow {
    color: #52616d;
    font-size: 13px;
    line-height: 18px;
  }

  .title {
    color: #111827;
    font-size: 24px;
    font-weight: 700;
    line-height: 32px;
  }

  .summary-row {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
    margin-bottom: 16px;
  }

  .summary-item {
    min-height: 82px;
    padding: 16px 18px;
    background: #fff;
    border: 1px solid #d8e8ee;
    border-radius: 8px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 8px;

    span {
      color: #6b7280;
      font-size: 13px;
    }

    strong {
      color: #111827;
      font-size: 24px;
      line-height: 28px;
    }
  }

  .content-grid {
    display: grid;
    grid-template-columns: 260px minmax(0, 1fr);
    gap: 16px;
  }

  .mine-list,
  .detail-panel {
    background: #fff;
    border: 1px solid #d8e8ee;
    border-radius: 8px;
  }

  .mine-list {
    padding: 14px;
  }

  .section-title {
    color: #111827;
    font-size: 16px;
    font-weight: 700;
    line-height: 22px;
  }

  .mine-row {
    width: 100%;
    height: 40px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 8px;
    padding: 0 10px;
    cursor: pointer;
    color: #374151;

    &.active,
    &:hover {
      background: #e8f8fb;
      color: #0e7490;
    }
  }

  .mine-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .mine-count {
    flex-shrink: 0;
    color: #6b7280;
    font-size: 12px;
  }

  .detail-panel {
    padding: 18px;
  }

  .panel-head {
    display: flex;
    justify-content: space-between;
    margin-bottom: 18px;
  }

  .subtle {
    margin-top: 4px;
    color: #6b7280;
    font-size: 13px;
  }

  .stats-columns {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 18px;
  }

  .stats-block {
    min-width: 0;
  }

  .block-title {
    margin-bottom: 12px;
    color: #374151;
    font-weight: 600;
  }

  .bar-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .bar-row {
    display: grid;
    grid-template-columns: minmax(120px, 180px) minmax(120px, 1fr) 72px;
    align-items: center;
    gap: 10px;
    min-height: 30px;
  }

  .bar-label {
    display: flex;
    align-items: center;
    gap: 7px;
    min-width: 0;
    color: #374151;
    font-size: 13px;

    span:last-child {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .attribute-tag {
    flex-shrink: 0;
    padding: 2px 6px;
    border-radius: 6px;
    background: #fff7df;
    color: #a16207;
    font-size: 12px;
  }

  .bar-track {
    height: 8px;
    border-radius: 4px;
    background: #edf2f5;
    overflow: hidden;

    &.attribute .bar-fill {
      background: #f59e0b;
    }
  }

  .bar-fill {
    display: block;
    height: 100%;
    border-radius: 4px;
    background: #57ccef;
  }

  .bar-row strong {
    text-align: right;
    color: #111827;
  }

  .empty {
    padding: 64px 0;
  }

  @media (max-width: 1100px) {
    .summary-row,
    .stats-columns,
    .content-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
