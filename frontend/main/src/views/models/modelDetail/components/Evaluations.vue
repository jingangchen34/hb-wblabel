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
        <Form.Item label="Dataset" required>
          <Select v-model:value="evaluateForm.datasetId" optionFilterProp="label" @change="refreshDataCount">
            <Select.Option v-for="item in datasetOptions" :key="item.id" :value="item.id" :label="item.name">
              {{ item.name }}
            </Select.Option>
          </Select>
        </Form.Item>
        <Form.Item label="Split">
          <Radio.Group v-model:value="evaluateForm.splitType" button-style="solid" @change="refreshDataCount">
            <Radio.Button value="">All</Radio.Button>
            <Radio.Button value="TRAINING">Training</Radio.Button>
            <Radio.Button value="VALIDATION">Validation</Radio.Button>
            <Radio.Button value="TEST">Test</Radio.Button>
            <Radio.Button value="NOT_SPLIT">Not Splited</Radio.Button>
          </Radio.Group>
        </Form.Item>
        <Form.Item label="Annotation Status">
          <Radio.Group v-model:value="evaluateForm.annotationStatus" button-style="solid" @change="refreshDataCount">
            <Radio.Button value="">All</Radio.Button>
            <Radio.Button value="ANNOTATED">Annotated</Radio.Button>
            <Radio.Button value="NOT_ANNOTATED">Not Annotated</Radio.Button>
            <Radio.Button value="INVALID">Invalid</Radio.Button>
          </Radio.Group>
        </Form.Item>
        <div class="evaluations__count">Matched frames: {{ matchedCount }}</div>
      </Form>
    </Modal>
  </div>
</template>
<script lang="tsx" setup>
  import { computed, onMounted, reactive, ref, watch } from 'vue';
  import { Form, Modal, Radio, Select, Table, Tag } from 'ant-design-vue';
  import { Button } from '/@@/Button';
  import { getDateTime } from '/@/utils/business/timeFormater';
  import {
    createModelEvaluationApi,
    getAllDataset,
    getModelDataCountApi,
    getModelEvaluationPageApi,
  } from '/@/api/business/models';
  import { RouteChildEnum } from '/@/enums/routeEnum';
  import { useGo } from '/@/hooks/web/usePage';
  import { useMessage } from '/@/hooks/web/useMessage';
  import { datasetTypeEnum } from '/@/api/business/model/datasetModel';

  const props = defineProps<{ modelId: string | number; datasetType: datasetTypeEnum }>();
  const go = useGo();
  const { createMessage } = useMessage();
  const records = ref<any[]>([]);
  const loading = ref(false);
  const creating = ref(false);
  const evaluateVisible = ref(false);
  const pageNo = ref(1);
  const pageSize = ref(10);
  const total = ref(0);
  const datasetOptions = ref<any[]>([]);
  const matchedCount = ref(0);
  const evaluateForm = reactive({
    datasetId: undefined as number | undefined,
    splitType: '',
    annotationStatus: 'ANNOTATED',
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

  const datasetTypes = computed(() => {
    if (props.datasetType === datasetTypeEnum.IMAGE) return datasetTypeEnum.IMAGE;
    return `${datasetTypeEnum.LIDAR_BASIC},${datasetTypeEnum.LIDAR_FUSION}`;
  });

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
      width: 130,
      customRender: ({ record }) => (
        <Button type="link" onClick={() => openDataset(record)}>Open Dataset</Button>
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
    if (!evaluateForm.datasetId) {
      evaluateForm.datasetId = datasetOptions.value?.[0]?.id;
    }
    await refreshDataCount();
  };

  const refreshDataCount = async () => {
    if (!evaluateForm.datasetId) {
      matchedCount.value = 0;
      return;
    }
    const res = await getModelDataCountApi({
      datasetId: evaluateForm.datasetId,
      modelId: Number(props.modelId),
      dataCountRatio: 100,
      isExcludeModelData: false,
      splitType: evaluateForm.splitType || undefined,
      annotationStatus: evaluateForm.annotationStatus || undefined,
    });
    matchedCount.value = Number(res || 0);
  };

  const openEvaluateModal = async () => {
    evaluateVisible.value = true;
    await loadDatasetOptions();
  };

  const handleCreateEvaluation = async () => {
    if (!evaluateForm.datasetId) {
      createMessage.warning('Please select dataset.');
      return;
    }
    if (!matchedCount.value) {
      createMessage.warning('No matched frames for evaluation.');
      return;
    }
    creating.value = true;
    try {
      await createModelEvaluationApi({
        datasetId: evaluateForm.datasetId,
        modelId: Number(props.modelId),
        dataFilterParam: {
          dataCountRatio: 100,
          isExcludeModelData: false,
          splitType: evaluateForm.splitType || undefined,
          annotationStatus: evaluateForm.annotationStatus || undefined,
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