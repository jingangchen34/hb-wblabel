<template>
  <div class="preannotation-page">
    <div class="toolbar">
      <div><h2>预标注</h2><p>AI 推理与 V2V 融合生成草稿，人工校验后提交为源数据真值。</p></div>
      <div><Button @click="load">刷新</Button><Button type="primary" @click="visible = true">新建预标注</Button></div>
    </div>
    <Table :columns="columns" :data-source="records" row-key="id" :loading="loading" :pagination="pagination" :scroll="{ x: 1100 }" @change="onPage">
      <template #actions="{ record }">
        <Space>
          <Button size="small" type="primary" :disabled="!['READY','COMMITTED'].includes(record.status)" @click="selectClip(record)">选择 Clip</Button>
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
        <template v-if="form.sourceMode !== 'V2V' && isFusionDetModel">
          <Form.Item label="FusionDet Config" required>
            <AutoComplete v-model:value="form.configPath" :options="configOptions" placeholder="选择或输入服务器上的 config 绝对路径" />
          </Form.Item>
          <Form.Item label="FusionDet 权重" required>
            <AutoComplete v-model:value="form.checkpointPath" :options="checkpointOptions" placeholder="选择或输入服务器上的 checkpoint 绝对路径" />
          </Form.Item>
          <Form.Item label="点云维度">
            <InputNumber v-model:value="form.sourcePointDim" :min="3" :max="16" />
            <span class="hint">源文件维度（all_test 原始 bin 为 6）</span>
            <InputNumber v-model:value="form.modelInputDim" :min="3" :max="16" style="margin-left:16px" />
            <span class="hint">模型使用维度（当前模型为 4）</span>
          </Form.Item>
          <div v-if="form.configPath.includes('occ-only')" class="config-warning">当前 config 是 OCC-only：会生成 OCC 标签，但不一定生成 3D 检测框。OD+OCC 请改选多任务 config。</div>
        </template>
        <Form.Item v-if="form.sourceMode === 'HYBRID'" label="V2V 优先 IoU 阈值">
          <InputNumber v-model:value="form.iouThreshold" :min="0" :max="1" :step="0.05" />
          <span class="hint">匹配 IoU 大于此值时采用 V2V 框；未匹配框均保留。</span>
        </Form.Item>
      </Form>
    </Modal>
    <Modal v-model:visible="clipVisible" :title="`${activeRecord?.name || ''} - 选择人工校验 Clip`" :footer="null" width="900px">
      <Table :columns="clipColumns" :data-source="clips" row-key="sceneId" :loading="clipLoading" :pagination="{ pageSize: 10 }">
        <template #clipActions="{ record }">
          <Button size="small" :type="record.completed ? 'default' : 'primary'" @click="openClip(record)">
            {{ record.completed ? '重新校验' : '开始校验' }}
          </Button>
        </template>
      </Table>
    </Modal>
  </div>
</template>

<script lang="tsx" setup>
import { computed, h, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { AutoComplete, Button, Form, Input, InputNumber, Modal, Radio, Select, Space, Table, Tag } from 'ant-design-vue';
import { getAllDataset, getModelPageApi } from '/@/api/business/models';
import { createPreAnnotationApi, deletePreAnnotationApi, getPreAnnotationClipsApi, getPreAnnotationPageApi } from '/@/api/business/preAnnotation';
import { datasetTypeEnum } from '/@/api/business/model/datasetModel';
import { goToTool } from '/@/utils/business';
import { useMessage } from '/@/hooks/web/useMessage';

const { createMessage, createConfirm } = useMessage();
const records = ref<any[]>([]), datasets = ref<any[]>([]), models = ref<any[]>([]);
const loading = ref(false), creating = ref(false), visible = ref(false);
const clipVisible = ref(false), clipLoading = ref(false), clips = ref<any[]>([]), activeRecord = ref<any>();
const pageNo = ref(1), pageSize = ref(10), total = ref(0);
const defaultConfig = '/home/user/cjg/code/fusiondet/configs/conch_and_xinchi_occ/sanet-point-pillar02-centerhead-dataset-all-occ-only.py';
const defaultCheckpoint = '/home/user/cjg/code/fusiondet/work_dirs/dataset_all_occ/epoch_20_ema.pth';
const configOptions = [{ value: defaultConfig }];
const checkpointOptions = [{ value: defaultCheckpoint }];
const form = reactive({ name: '', datasetIds: [] as number[], sourceMode: 'AI', modelId: undefined as number|undefined, iouThreshold: .5,
  configPath: defaultConfig, checkpointPath: defaultCheckpoint, sourcePointDim: 6, modelInputDim: 4 });
const selectedModel = computed(()=>models.value.find((item:any)=>Number(item.id)===Number(form.modelId)));
const isFusionDetModel = computed(()=>/fusiondet|sanet/i.test(`${selectedModel.value?.name || ''} ${selectedModel.value?.version || ''}`));
const colors:any = { STARTED:'blue', RUNNING:'cyan', READY:'green', FAILURE:'red', COMMITTED:'purple' };
const sourceText:any = { AI:'AI 推理', V2V:'V2V 解析', HYBRID:'AI + V2V' };
async function selectClip(record:any){
  activeRecord.value=record; clipVisible.value=true; clipLoading.value=true;
  try { clips.value=await getPreAnnotationClipsApi(record.id) || []; }
  finally { clipLoading.value=false; }
}
const openClip = (clip:any) => goToTool({ datasetId:activeRecord.value.datasetId, dataId:clip.firstDataId, type:'readOnly', dataType:'frame', preAnnotationId:activeRecord.value.id, preAnnotation:'1' }, datasetTypeEnum.LIDAR_FUSION);
const remove = (r:any) => createConfirm({ iconType:'warning', title:'删除该预标注任务？', onOk: async()=>{ await deletePreAnnotationApi(r.id); await load(); } });
const columns:any[] = [
  { title:'任务', dataIndex:'name', width:180 }, { title:'数据集', dataIndex:'datasetName', width:220 },
  { title:'来源', dataIndex:'sourceMode', width:110, customRender:({text}:any)=>sourceText[text]||text },
  { title:'进度', width:110, customRender:({record}:any)=>`${record.committedDataIds?.length || 0}/${record.dataCount || 0}` },
  { title:'状态', dataIndex:'status', width:220, customRender:({text,record}:any)=>h(Space,{},()=>[
      h(Tag,{color:colors[text]},()=>text),
      text==='FAILURE' ? h(Button,{size:'small',danger:true,onClick:remove.bind(null,record)},()=> '删除失败任务') : null,
    ]) },
  { title:'失败原因', dataIndex:'errorReason', width:260, ellipsis:true },
  { title:'操作', key:'actions', width:190, fixed:'right', slots:{ customRender:'actions' } },
];
const clipColumns:any[] = [
  { title:'Clip', dataIndex:'sceneName', ellipsis:true },
  { title:'校验进度', width:130, customRender:({record}:any)=>`${record.committedCount || 0}/${record.dataCount || 0}` },
  { title:'状态', width:110, customRender:({record}:any)=>h(Tag,{color:record.completed?'green':'orange'},()=>record.completed?'已完成':'待校验') },
  { title:'操作', key:'clipActions', width:120, slots:{ customRender:'clipActions' } },
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
  if(isFusionDetModel.value && (!form.configPath || !form.checkpointPath)){createMessage.warning('请选择 FusionDet config 和权重');return;}
  creating.value=true; try {
    const inference = isFusionDetModel.value ? {} : {configPath:undefined,checkpointPath:undefined,sourcePointDim:undefined,modelInputDim:undefined};
    await Promise.all(form.datasetIds.map((datasetId)=>createPreAnnotationApi({...form,...inference,datasetIds:[datasetId]})));
    visible.value=false; createMessage.success(`已创建 ${form.datasetIds.length} 个独立预标注任务`); await load();
  } finally { creating.value=false; }
}
async function refreshOnFocus(){ await load(); if(clipVisible.value && activeRecord.value) await selectClip(activeRecord.value); }
onMounted(()=>{load();loadOptions();window.addEventListener('focus',refreshOnFocus);});
onBeforeUnmount(()=>window.removeEventListener('focus',refreshOnFocus));
</script>

<style scoped lang="less">
.preannotation-page{padding:24px}.toolbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px}.toolbar h2{margin:0 0 4px;font-size:22px}.toolbar p{margin:0;color:#7b8494}.toolbar button{margin-left:8px}.hint{margin-left:10px;color:#8c8c8c}.config-warning{margin:-10px 0 18px;color:#d48806}
</style>
