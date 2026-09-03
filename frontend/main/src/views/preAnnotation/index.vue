<template>
  <div class="preannotation-page">
    <div class="toolbar">
      <div><h2>预标注</h2><p>AI 推理与 V2V 融合生成草稿，人工校验后提交为源数据真值。</p></div>
      <div><Button @click="load">刷新</Button><Button type="primary" @click="visible = true">新建预标注</Button></div>
    </div>
    <Table :columns="columns" :data-source="records" row-key="id" :loading="loading" :pagination="pagination" :scroll="{ x: 1100 }" @change="onPage">
      <template #bodyCell="{ column, record }">
        <Space v-if="column.key === 'actions'">
          <Button size="small" type="primary" :disabled="record.status !== 'READY'" @click="open(record)">人工校验</Button>
          <Button size="small" danger @click="remove(record)">删除</Button>
        </Space>
      </template>
    </Table>
    <Modal v-model:visible="visible" title="新建预标注" :confirm-loading="creating" @ok="create">
      <Form layout="vertical" :model="form">
        <Form.Item label="任务名称"><Input v-model:value="form.name" placeholder="可选" /></Form.Item>
        <Form.Item label="数据集" required>
          <Select v-model:value="form.datasetIds" mode="multiple" option-filter-prop="label">
            <Select.Option v-for="item in datasets" :key="item.id" :value="Number(item.id)" :label="item.name">{{ item.name }}</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item label="预标注来源" required>
          <Radio.Group v-model:value="form.sourceMode" button-style="solid">
            <Radio.Button value="AI">AI 推理</Radio.Button><Radio.Button value="V2V">V2V 解析</Radio.Button><Radio.Button value="HYBRID">混合</Radio.Button>
          </Radio.Group>
        </Form.Item>
        <Form.Item v-if="form.sourceMode !== 'V2V'" label="推理模型" required>
          <Select v-model:value="form.modelId" option-filter-prop="label">
            <Select.Option v-for="item in models" :key="item.id" :value="Number(item.id)" :label="item.name">{{ item.name }}</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item v-if="form.sourceMode === 'HYBRID'" label="V2V 优先 IoU 阈值">
          <InputNumber v-model:value="form.iouThreshold" :min="0" :max="1" :step="0.05" />
          <span class="hint">匹配 IoU 大于此值时采用 V2V 框；未匹配框均保留。</span>
        </Form.Item>
      </Form>
    </Modal>
  </div>
</template>

<script lang="tsx" setup>
import { computed, h, onMounted, reactive, ref } from 'vue';
import { Button, Form, Input, InputNumber, Modal, Radio, Select, Space, Table, Tag } from 'ant-design-vue';
import { getAllDataset, getModelPageApi } from '/@/api/business/models';
import { createPreAnnotationApi, deletePreAnnotationApi, getPreAnnotationPageApi } from '/@/api/business/preAnnotation';
import { datasetTypeEnum } from '/@/api/business/model/datasetModel';
import { goToTool } from '/@/utils/business';
import { useMessage } from '/@/hooks/web/useMessage';

const { createMessage, createConfirm } = useMessage();
const records = ref<any[]>([]), datasets = ref<any[]>([]), models = ref<any[]>([]);
const loading = ref(false), creating = ref(false), visible = ref(false);
const pageNo = ref(1), pageSize = ref(10), total = ref(0);
const form = reactive({ name: '', datasetIds: [] as number[], sourceMode: 'AI', modelId: undefined as number|undefined, iouThreshold: .5 });
const colors:any = { STARTED:'blue', RUNNING:'cyan', READY:'green', FAILURE:'red', COMMITTED:'purple' };
const sourceText:any = { AI:'AI 推理', V2V:'V2V 解析', HYBRID:'AI + V2V' };
const open = (r:any) => goToTool({ datasetId:r.datasetId, dataId:r.dataIds?.[0], type:'readOnly', dataType:'frame', preAnnotationId:r.id, preAnnotation:'1' }, datasetTypeEnum.LIDAR_FUSION);
const remove = (r:any) => createConfirm({ iconType:'warning', title:'删除该预标注任务？', onOk: async()=>{ await deletePreAnnotationApi(r.id); await load(); } });
const columns:any[] = [
  { title:'任务', dataIndex:'name', width:180 }, { title:'数据集', dataIndex:'datasetName', width:220 },
  { title:'来源', dataIndex:'sourceMode', width:110, customRender:({text}:any)=>sourceText[text]||text },
  { title:'进度', width:110, customRender:({record}:any)=>`${record.committedDataIds?.length || 0}/${record.dataCount || 0}` },
  { title:'状态', dataIndex:'status', width:110, customRender:({text}:any)=>h(Tag,{color:colors[text]},()=>text) },
  { title:'失败原因', dataIndex:'errorReason', width:260, ellipsis:true },
  { title:'操作', key:'actions', width:190, fixed:'right' },
];
const pagination = computed(()=>({current:pageNo.value,pageSize:pageSize.value,total:total.value,showSizeChanger:true}));
async function load(){ loading.value=true; try { const r=await getPreAnnotationPageApi({pageNo:pageNo.value,pageSize:pageSize.value}); records.value=r?.list||[]; total.value=r?.total||0; } finally { loading.value=false; } }
function onPage(p:any){ pageNo.value=p.current; pageSize.value=p.pageSize; load(); }
async function loadOptions(){
  datasets.value = await getAllDataset({datasetTypes:[datasetTypeEnum.LIDAR_FUSION,datasetTypeEnum.LIDAR_BASIC].join(',')}) || [];
  const response:any = await getModelPageApi({pageNo:1,pageSize:100,datasetType:datasetTypeEnum.LIDAR_FUSION}); models.value=Array.isArray(response)?response:(response?.list||[]);
}
async function create(){
  if(!form.datasetIds.length){createMessage.warning('请选择数据集');return;} if(form.sourceMode!=='V2V'&&!form.modelId){createMessage.warning('请选择推理模型');return;}
  creating.value=true; try {
    await Promise.all(form.datasetIds.map((datasetId)=>createPreAnnotationApi({...form,datasetIds:[datasetId]})));
    visible.value=false; createMessage.success(`已创建 ${form.datasetIds.length} 个独立预标注任务`); await load();
  } finally { creating.value=false; }
}
onMounted(()=>{load();loadOptions();});
</script>

<style scoped lang="less">
.preannotation-page{padding:24px}.toolbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px}.toolbar h2{margin:0 0 4px;font-size:22px}.toolbar p{margin:0;color:#7b8494}.toolbar button{margin-left:8px}.hint{margin-left:10px;color:#8c8c8c}
</style>
