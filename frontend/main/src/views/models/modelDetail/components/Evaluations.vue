<template>
  <div class="evaluations">
    <div class="evaluations__toolbar">
      <Button type="primary" @click="openEvaluateModal">Evaluate Model</Button>
      <Button type="default" @click="loadList">Refresh</Button>
    </div>
    <Table
      :columns="columns"
      :data-source="records"
      :pagination="pagination"
      :loading="loading"
      row-key="id"
      @change="handleTableChange"
    />
    <Modal
      v-model:visible="evaluateVisible"
      title="Evaluate Model"
      :confirm-loading="creating"
      @ok="handleCreateEvaluation"
      @cancel="evaluateVisible = false"
    >
      <Form :model="evaluateForm" layout="vertical">
        <Form.Item label="Evaluation Source">
          <Radio.Group v-model:value="evaluateForm.sourceMode" button-style="solid" @change="refreshDataCount">
            <Radio.Button value="SPLIT">By Split</Radio.Button>
            <Radio.Button value="MANUAL">Manual Datasets</Radio.Button>
          </Radio.Group>
        </Form.Item>
        <Form.Item label="Datasets" required>
          <Select
            v-model:value="evaluateForm.datasetIds"
            mode="multiple"
            optionFilterProp="label"
            @change="refreshDataCount"
          >
            <Select.Option v-for="item in datasetOptions" :key="item.id" :value="item.id" :label="item.name">
              {{ item.name }}
            </Select.Option>
          </Select>
        </Form.Item>
        <Form.Item v-if="evaluateForm.sourceMode === 'SPLIT'" label="Split">
          <Radio.Group v-model:value="evaluateForm.splitType" button-style="solid" @change="refreshDataCount">
            <Radio.Button value="TRAINING">Training</Radio.Button>
            <Radio.Button value="VALIDATION">Validation</Radio.Button>
            <Radio.Button value="TEST">Test</Radio.Button>
            <Radio.Button value="NOT_SPLIT">Not Split</Radio.Button>
          </Radio.Group>
        </Form.Item>
        <Form.Item label="Eval Metrics" required>
          <Checkbox.Group v-model:value="evaluateForm.metrics">
            <Checkbox value="mAP">mAP</Checkbox>
            <Checkbox v-if="!isPointPillarsModel" value="miou">mIoU</Checkbox>
          </Checkbox.Group>
        </Form.Item>
        <Form.Item label="Source Point Dim" required>
          <InputNumber v-model:value="evaluateForm.sourcePointDim" :min="1" :max="16" :precision="0" />
        </Form.Item>
        <Form.Item v-if="isPointPillarsModel" label="Model Input Dim" required>
          <InputNumber v-model:value="evaluateForm.modelInputDim" :min="1" :max="16" :precision="0" />
        </Form.Item>
        <Form.Item v-if="isPointPillarsModel" label="PointPillars Config" required>
          <Input v-model:value="evaluateForm.configPath" placeholder="/home/user/.../xyres_0.16_raw.proto" />
        </Form.Item>
        <Form.Item v-if="isPointPillarsModel" label="PointPillars Weight Path" required>
          <Input v-model:value="evaluateForm.checkpointPath" placeholder="Directory: latest 15; .tckpt file: single weight" />
        </Form.Item>
        <div class="evaluations__count">Selected frames: {{ matchedCount }}</div>
      </Form>
    </Modal>
    <Modal v-model:visible="metricsVisible" title="Evaluation Metrics" width="1200px" :footer="null">
      <div class="metrics-detail">
        <div class="metrics-detail__summary">{{ metricsSummary }}</div>
        <pre v-if="selectedMetricsRecord?.metrics?.detectionText">{{ selectedMetricsRecord.metrics.detectionText }}</pre>
        <div v-if="safetyRows.length" class="safety-metrics">
          <h3>Per-class confidence recommendations</h3>
          <div class="safety-metrics__hint">False detection rate = FP / (TP + FP). Each threshold minimizes miss rate within its limit.</div>
          <table>
            <thead><tr><th>Class</th><th>FP limit</th><th>Confidence</th><th>TP / FP / FN</th><th>False detection</th><th>Miss</th><th>Frames</th></tr></thead>
            <tbody>
              <tr v-for="row in safetyRows" :key="`${row.className}-${row.falseDetectionRateLimit}`">
                <td>{{ row.className }}</td>
                <td>{{ formatRate(row.falseDetectionRateLimit) }}</td>
                <td>{{ Number(row.threshold).toFixed(4) }}</td>
                <td>{{ row.TP }} / {{ row.FP }} / {{ row.FN }}</td>
                <td>{{ formatRate(row.falseDetectionRate) }}</td>
                <td>{{ formatRate(row.missRate) }}</td>
                <td class="safety-metrics__actions">
                  <Button size="small" :disabled="!row.falsePositiveDataIds?.length" @click="openEvaluationFrames(row.falsePositiveDataIds)">FP {{ row.falsePositiveDataIds?.length || 0 }}</Button>
                  <Button size="small" :disabled="!row.missedDataIds?.length" @click="openEvaluationFrames(row.missedDataIds)">Miss {{ row.missedDataIds?.length || 0 }}</Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <pre v-if="selectedMetricsRecord?.metrics?.miouTable">{{ selectedMetricsRecord.metrics.miouTable }}</pre>
      </div>
    </Modal>
  </div>
</template>
<script lang="tsx" setup>
  import { computed, onMounted, reactive, ref, watch } from 'vue';
  import { Checkbox, Form, Input, InputNumber, Modal, Radio, Select, Table, Tag } from 'ant-design-vue';
  import { Button } from '/@@/Button';
  import { getDateTime } from '/@/utils/business/timeFormater';
  import {
    createModelEvaluationApi,
    deleteModelEvaluationApi,
    getAllDataset,
    getModelDataCountApi,
    getModelEvaluationPageApi,
  } from '/@/api/business/models';
  import { RouteChildEnum } from '/@/enums/routeEnum';
  import { useGo } from '/@/hooks/web/usePage';
  import { useMessage } from '/@/hooks/web/useMessage';
  import { datasetTypeEnum } from '/@/api/business/model/datasetModel';

  const props = defineProps<{ modelId: string | number; datasetType: datasetTypeEnum; overviewData?: any }>();
  const go = useGo();
  const { createMessage } = useMessage();
  const records = ref<any[]>([]);
  const loading = ref(false);
  const creating = ref(false);
  const evaluateVisible = ref(false);
  const metricsVisible = ref(false);
  const selectedMetricsRecord = ref<any>(null);
  const pageNo = ref(1);
  const pageSize = ref(10);
  const total = ref(0);
  const datasetOptions = ref<any[]>([]);
  const matchedCount = ref(0);
  const evaluateForm = reactive({
    sourceMode: 'SPLIT',
    datasetIds: [] as number[],
    splitType: 'TEST',
    metrics: ['mAP', 'miou'] as string[],
    sourcePointDim: 6 as number | undefined,
    modelInputDim: 4 as number | undefined,
    configPath: '',
    checkpointPath: '',
  });

  const isPointPillarsModel = computed(() => {
    const overview = props.overviewData || {};
    const text = [overview.name, overview.url, overview.description, overview.scenario].join(' ').toLowerCase();
    return text.includes('pointpillar') || text.includes('point_pillar') || text.includes('pp_data');
  });

  const statusColor = {
    STARTED: 'blue',
    RUNNING: 'cyan',
    SUCCESS: 'green',
    SUCCESS_WITH_ERROR: 'orange',
    FAILURE: 'red',
  };

  const metricValue = (record: any, key: string) => {
    const value = record?.metrics?.[key];
    if (value === undefined || value === null || value === '') return '-';
    return typeof value === 'number' ? value.toFixed(4) : value;
  };

  const metricsSummary = computed(() => {
    const record = selectedMetricsRecord.value;
    if (!record) return '';
    return `Id ${record.id} / ${record.name || ''}`;
  });

  const safetyRows = computed(() => {
    const groups = selectedMetricsRecord.value?.metrics?.safetyThresholds || [];
    return groups.flatMap((group: any) =>
      (group.recommendations || []).map((item: any) => ({ className: group.className, ...item })),
    );
  });

  const formatRate = (value: number) => `${(Number(value || 0) * 100).toFixed(2)}%`;

  const openEvaluationFrames = (dataIds: Array<number | string>) => {
    const record = selectedMetricsRecord.value;
    if (!record || !dataIds?.length) return;
    go({
      path: RouteChildEnum.DATASETS_DATA as any,
      query: {
        id: record.datasetId,
        evaluationId: record.id,
        showEvaluation: 1,
        evaluationDataIds: dataIds.join(','),
      },
    });
  };

  const datasetTypes = computed(() => {
    if (props.datasetType === datasetTypeEnum.IMAGE) return datasetTypeEnum.IMAGE;
    return `${datasetTypeEnum.LIDAR_BASIC},${datasetTypeEnum.LIDAR_FUSION}`;
  });

  const openMetrics = (record: any) => {
    selectedMetricsRecord.value = record;
    metricsVisible.value = true;
  };

  const deleteEvaluation = (record: any) => {
    Modal.confirm({
      title: 'Delete evaluation?',
      content: record.name,
      onOk: async () => {
        await deleteModelEvaluationApi({ id: record.id });
        createMessage.success('Evaluation deleted.');
        await loadList();
      },
    });
  };

  const openDataset = (record: any) => {
    go({
      path: RouteChildEnum.DATASETS_DATA as any,
      query: {
        id: record.datasetId,
        evaluationId: record.id,
        showEvaluation: 1,
      },
    });
  };

  const columns = [
    { title: 'Id', dataIndex: 'id', width: 80 },
    { title: 'Name', dataIndex: 'name' },
    { title: 'Dataset', dataIndex: 'datasetName' },
    { title: 'Frames', dataIndex: 'dataCount', width: 90 },
    {
      title: 'mIoU Frames',
      width: 120,
      customRender: ({ record }) => `${record.miouDataCount ?? 0}/${record.dataCount ?? 0}`,
    },
    {
      title: 'mAP',
      width: 100,
      customRender: ({ record }) => metricValue(record, 'mAP'),
    },
    {
      title: 'meanIoU',
      width: 110,
      customRender: ({ record }) => metricValue(record, 'meanIoU'),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      width: 120,
      customRender: ({ record }) => <Tag color={statusColor[record.status] || 'default'}>{record.status}</Tag>,
    },
    {
      title: 'Created At',
      dataIndex: 'createdAt',
      width: 170,
      customRender: ({ record }) => getDateTime(record.createdAt),
    },
    {
      title: 'Actions',
      width: 240,
      customRender: ({ record }) => (
        <div class="action-cell">
          <Button type="link" onClick={() => openDataset(record)}>Open Dataset</Button>
          <Button type="link" onClick={() => openMetrics(record)}>Metrics</Button>
          <Button type="link" danger onClick={() => deleteEvaluation(record)}>Delete</Button>
        </div>
      ),
    },
    {
      title: 'Artifacts',
      width: 260,
      customRender: ({ record }) => (
        <div class="artifact-cell">
          <div title={record.outputPath}>{record.outputPath || '-'}</div>
          <div title={record.logPath}>{record.logPath || ''}</div>
          {record.errorReason ? <div class="error" title={record.errorReason}>{record.errorReason}</div> : null}
        </div>
      ),
    },
  ];

  const pagination = computed(() => ({
    current: pageNo.value,
    pageSize: pageSize.value,
    total: total.value,
    showSizeChanger: true,
  }));

  const loadList = async () => {
    loading.value = true;
    try {
      const res = await getModelEvaluationPageApi({
        modelId: Number(props.modelId),
        pageNo: pageNo.value,
        pageSize: pageSize.value,
      });
      records.value = res?.list || [];
      total.value = res?.total || 0;
    } finally {
      loading.value = false;
    }
  };

  const loadDatasetOptions = async () => {
    const res = await getAllDataset({ datasetTypes: datasetTypes.value });
    datasetOptions.value = res || [];
    if (!evaluateForm.datasetIds.length && datasetOptions.value?.[0]?.id) {
      evaluateForm.datasetIds = [datasetOptions.value[0].id];
    }
    await refreshDataCount();
  };

  const refreshDataCount = async () => {
    if (!evaluateForm.datasetIds.length) {
      matchedCount.value = 0;
      return;
    }
    const counts = await Promise.all(
      evaluateForm.datasetIds.map((datasetId) =>
        getModelDataCountApi({
          datasetId,
          modelId: Number(props.modelId),
          dataCountRatio: 100,
          isExcludeModelData: false,
          splitType: evaluateForm.sourceMode === 'SPLIT' ? evaluateForm.splitType : undefined,
        }),
      ),
    );
    matchedCount.value = counts.reduce((sum, count) => sum + Number(count || 0), 0);
  };

  const openEvaluateModal = async () => {
    if (isPointPillarsModel.value) {
      evaluateForm.metrics = ['mAP'];
    } else if (!evaluateForm.metrics.includes('miou')) {
      evaluateForm.metrics = ['mAP', 'miou'];
    }
    evaluateVisible.value = true;
    await loadDatasetOptions();
  };

  const handleCreateEvaluation = async () => {
    if (!evaluateForm.datasetIds.length) {
      createMessage.warning('Please select dataset.');
      return;
    }
    if (!evaluateForm.metrics.length) {
      createMessage.warning('Please select eval metrics.');
      return;
    }
    if (isPointPillarsModel.value && (!evaluateForm.configPath.trim() || !evaluateForm.checkpointPath.trim())) {
      createMessage.warning('Please provide the PointPillars config and weight path.');
      return;
    }
    if (!evaluateForm.sourcePointDim || (isPointPillarsModel.value && (!evaluateForm.modelInputDim || evaluateForm.modelInputDim > evaluateForm.sourcePointDim))) {
      createMessage.warning('Model input dimension must not exceed source point dimension.');
      return;
    }
    if (!matchedCount.value) {
      createMessage.warning('No matched frames for evaluation.');
      return;
    }
    creating.value = true;
    try {
      await createModelEvaluationApi({
        datasetId: evaluateForm.datasetIds[0],
        datasetIds: evaluateForm.datasetIds,
        modelId: Number(props.modelId),
        metrics: evaluateForm.metrics,
        sourcePointDim: evaluateForm.sourcePointDim,
        modelInputDim: isPointPillarsModel.value ? evaluateForm.modelInputDim : undefined,
        configPath: evaluateForm.configPath,
        checkpointPath: evaluateForm.checkpointPath,
        dataFilterParam: {
          dataCountRatio: 100,
          isExcludeModelData: false,
          splitType: evaluateForm.sourceMode === 'SPLIT' ? evaluateForm.splitType : undefined,
        },
      });
      createMessage.success('Evaluation task created.');
      evaluateVisible.value = false;
      await loadList();
    } finally {
      creating.value = false;
    }
  };

  const handleTableChange = (page) => {
    pageNo.value = page.current;
    pageSize.value = page.pageSize;
    loadList();
  };

  watch(() => props.datasetType, loadDatasetOptions);
  onMounted(loadList);
</script>
<style lang="less" scoped>
  .evaluations {
    margin: 20px;
    padding: 20px;
    background: #fff;
    border-radius: 8px;

    &__toolbar {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-bottom: 12px;
    }

    &__count {
      font-size: 13px;
      color: #666;
    }
  }

  .action-cell {
    display: flex;
    align-items: center;
    gap: 4px;
    white-space: nowrap;
  }

  .metrics-detail {
    max-height: 650px;
    overflow: auto;

    &__summary {
      margin-bottom: 8px;
      font-weight: 600;
    }

    pre {
      padding: 12px;
      background: #f7f8fa;
      border-radius: 4px;
      white-space: pre-wrap;
    }
  }

  .safety-metrics {
    margin: 16px 0;

    &__hint {
      margin-bottom: 8px;
      color: #666;
    }

    &__actions {
      display: flex;
      gap: 4px;
      white-space: nowrap;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }

    th,
    td {
      padding: 7px 8px;
      border: 1px solid #e5e7eb;
      text-align: left;
    }

    th {
      background: #f7f8fa;
    }
  }

  .artifact-cell {
    max-width: 250px;
    font-size: 12px;
    line-height: 18px;

    div {
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }

    .error {
      color: #f5222d;
    }
  }
</style>