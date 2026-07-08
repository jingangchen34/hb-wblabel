package ai.basic.x1.usecase;

import ai.basic.x1.adapter.dto.ModelEvaluationCompareDTO;
import ai.basic.x1.adapter.port.dao.DataAnnotationObjectDAO;
import ai.basic.x1.adapter.port.dao.DataInfoDAO;
import ai.basic.x1.adapter.port.dao.ModelEvaluationRecordDAO;
import ai.basic.x1.adapter.port.dao.mybatis.model.DataAnnotationObject;
import ai.basic.x1.adapter.port.dao.mybatis.model.DataInfo;
import ai.basic.x1.adapter.port.dao.mybatis.model.ModelEvaluationRecord;
import ai.basic.x1.adapter.port.dao.mybatis.extension.ExtendLambdaQueryWrapper;
import ai.basic.x1.entity.ModelEvaluationCreateBO;
import ai.basic.x1.entity.ModelRunFilterDataBO;
import ai.basic.x1.entity.enums.DataAnnotationObjectSourceTypeEnum;
import ai.basic.x1.entity.enums.ItemTypeEnum;
import ai.basic.x1.entity.enums.RunStatusEnum;
import ai.basic.x1.usecase.exception.UsecaseCode;
import ai.basic.x1.usecase.exception.UsecaseException;
import ai.basic.x1.util.DefaultConverter;
import ai.basic.x1.util.Page;
import cn.hutool.core.collection.CollUtil;
import cn.hutool.core.date.DatePattern;
import cn.hutool.core.date.DateUtil;
import cn.hutool.core.thread.ThreadUtil;
import cn.hutool.core.util.ObjectUtil;
import cn.hutool.core.util.StrUtil;
import cn.hutool.http.ContentType;
import cn.hutool.http.HttpRequest;
import cn.hutool.http.HttpStatus;
import cn.hutool.json.JSONArray;
import cn.hutool.json.JSONObject;
import cn.hutool.json.JSONUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.stream.Collectors;

public class ModelEvaluationUseCase {

    @Autowired
    private ModelEvaluationRecordDAO modelEvaluationRecordDAO;

    @Autowired
    private DataInfoDAO dataInfoDAO;

    @Autowired
    private DataAnnotationObjectDAO dataAnnotationObjectDAO;

    @Autowired
    private DataInfoUseCase dataInfoUseCase;

    @Value("${fusiondet.evaluation.url:http://host.docker.internal:8510/evaluate}")
    private String evaluationUrl;

    @Value("${fusiondet.evaluation.config:configs/conch_and_xinchi_occ/sanet-point-pillar02-centerhead-conch-11cls-fp16_occ.py}")
    private String defaultConfigPath;

    @Value("${fusiondet.evaluation.checkpoint:work_dirs/occ/epoch_20_ema.pth}")
    private String defaultCheckpointPath;

    private static final ExecutorService EXECUTOR = ThreadUtil.newExecutor(2);

    public Long create(ModelEvaluationCreateBO createBO) {
        var datasetIds = resolveDatasetIds(createBO);
        if (CollUtil.isEmpty(datasetIds)) {
            throw new UsecaseException(UsecaseCode.PARAM_ERROR, "Please select dataset.");
        }
        var frameIds = resolveFrameIds(createBO, datasetIds);
        if (CollUtil.isEmpty(frameIds)) {
            throw new UsecaseException(UsecaseCode.PARAM_ERROR, "No single frame data selected.");
        }
        var configPath = StrUtil.blankToDefault(createBO.getConfigPath(), defaultConfigPath);
        var checkpointPath = StrUtil.blankToDefault(createBO.getCheckpointPath(), defaultCheckpointPath);
        var record = ModelEvaluationRecord.builder()
                .modelId(createBO.getModelId())
                .datasetId(datasetIds.get(0))
                .name(StrUtil.blankToDefault(createBO.getName(), buildEvaluationName(datasetIds)))
                .status(RunStatusEnum.STARTED)
                .dataCount((long) frameIds.size())
                .dataIds(JSONUtil.parseArray(frameIds))
                .configPath(configPath)
                .checkpointPath(checkpointPath)
                .createdBy(createBO.getCreatedBy())
                .build();
        modelEvaluationRecordDAO.save(record);
        EXECUTOR.execute(() -> runEvaluation(record.getId(), frameIds, resolveMetrics(createBO), createBO.getCreatedBy()));
        return record.getId();
    }

    public Page<ModelEvaluationRecord> findByPage(Long modelId, Integer pageNo, Integer pageSize) {
        var wrapper = new ExtendLambdaQueryWrapper<ModelEvaluationRecord>();
        wrapper.eq(ModelEvaluationRecord::getModelId, modelId);
        wrapper.orderByDesc(ModelEvaluationRecord::getCreatedAt);
        var page = modelEvaluationRecordDAO.getBaseMapper().selectListWithDatasetNotDeleted(
                new com.baomidou.mybatisplus.extension.plugins.pagination.Page<>(pageNo, pageSize), wrapper);
        return DefaultConverter.convert(page, ModelEvaluationRecord.class);
    }

    public void delete(Long id, Long userId) {
        var record = modelEvaluationRecordDAO.getById(id);
        if (record == null) {
            throw new UsecaseException(UsecaseCode.PARAM_ERROR, "Evaluation record does not exist.");
        }
        modelEvaluationRecordDAO.getBaseMapper().softDeleteById(id, userId);
    }

    public ModelEvaluationCompareDTO compare(Long evaluationId, Long dataId) {
        var record = modelEvaluationRecordDAO.getById(evaluationId);
        if (record == null) {
            throw new UsecaseException(UsecaseCode.PARAM_ERROR, "Evaluation record does not exist.");
        }
        var gtWrapper = Wrappers.lambdaQuery(DataAnnotationObject.class)
                .eq(DataAnnotationObject::getDataId, dataId)
                .eq(DataAnnotationObject::getSourceId, -1L)
                .eq(DataAnnotationObject::getSourceType, DataAnnotationObjectSourceTypeEnum.DATA_FLOW);
        var groundTruths = dataAnnotationObjectDAO.list(gtWrapper).stream()
                .map(DataAnnotationObject::getClassAttributes)
                .peek(obj -> {
                    obj.set("source", "GT");
                    obj.set("color", "#22c55e");
                })
                .collect(Collectors.toList());
        var predictions = new ArrayList<JSONObject>();
        var predictionMap = record.getPredictions();
        if (predictionMap != null) {
            var predArray = predictionMap.getJSONArray(String.valueOf(dataId));
            if (predArray != null) {
                predArray.forEach(item -> predictions.add(JSONUtil.parseObj(item)));
            }
        }
        return ModelEvaluationCompareDTO.builder()
                .evaluationId(evaluationId)
                .dataId(dataId)
                .groundTruths(groundTruths)
                .predictions(predictions)
                .build();
    }

    private List<Long> resolveDatasetIds(ModelEvaluationCreateBO createBO) {
        var datasetIds = new ArrayList<Long>();
        if (CollUtil.isNotEmpty(createBO.getDatasetIds())) {
            datasetIds.addAll(createBO.getDatasetIds());
        }
        if (createBO.getDatasetId() != null) {
            datasetIds.add(createBO.getDatasetId());
        }
        return datasetIds.stream().distinct().collect(Collectors.toList());
    }

    private List<String> resolveMetrics(ModelEvaluationCreateBO createBO) {
        var metrics = createBO.getMetrics();
        if (CollUtil.isEmpty(metrics)) {
            return List.of("mAP", "miou");
        }
        var resolved = metrics.stream()
                .filter(StrUtil::isNotBlank)
                .map(String::trim)
                .map(metric -> ObjectUtil.equals(metric, "map") ? "mAP" : metric)
                .filter(metric -> Arrays.asList("mAP", "miou").contains(metric))
                .distinct()
                .collect(Collectors.toList());
        return CollUtil.isEmpty(resolved) ? List.of("mAP", "miou") : resolved;
    }

    private String buildEvaluationName(List<Long> datasetIds) {
        var prefix = datasetIds.size() > 1 ? "Eval-" + datasetIds.size() + "sets-" : "Eval-";
        return prefix + DateUtil.format(OffsetDateTime.now().toLocalDateTime(), DatePattern.PURE_DATETIME_PATTERN);
    }

    private List<Long> resolveFrameIds(ModelEvaluationCreateBO createBO, List<Long> datasetIds) {
        if (CollUtil.isNotEmpty(createBO.getDataIds())) {
            return expandFrameIds(datasetIds.get(0), createBO.getDataIds());
        }
        var filter = createBO.getDataFilterParam();
        if (filter == null) {
            filter = ModelRunFilterDataBO.builder()
                    .dataCountRatio(100)
                    .isExcludeModelData(false)
                    .build();
        }
        if (filter.getDataCountRatio() == null) {
            filter.setDataCountRatio(100);
        }
        if (filter.getIsExcludeModelData() == null) {
            filter.setIsExcludeModelData(false);
        }
        var frameIds = new ArrayList<Long>();
        for (var datasetId : datasetIds) {
            var totalDataNum = dataInfoUseCase.findModelRunDataCount(filter, datasetId, createBO.getModelId());
            totalDataNum = (long) Math.ceil(totalDataNum * filter.getDataCountRatio() / 100.0D);
            if (!ObjectUtil.equals(totalDataNum, 0L)) {
                frameIds.addAll(dataInfoUseCase.findModelRunDataIds(filter, datasetId, createBO.getModelId(), totalDataNum));
            }
        }
        return frameIds.stream().distinct().collect(Collectors.toList());
    }

    private List<Long> expandFrameIds(Long datasetId, List<Long> selectedIds) {
        var selected = dataInfoDAO.listByIds(selectedIds);
        var frameIds = selected.stream()
                .filter(data -> data.getType() == ItemTypeEnum.SINGLE_DATA)
                .map(DataInfo::getId)
                .collect(Collectors.toCollection(ArrayList::new));
        var sceneIds = selected.stream()
                .filter(data -> data.getType() == ItemTypeEnum.SCENE)
                .map(DataInfo::getId)
                .collect(Collectors.toList());
        if (CollUtil.isNotEmpty(sceneIds)) {
            var children = dataInfoDAO.list(Wrappers.lambdaQuery(DataInfo.class)
                    .eq(DataInfo::getDatasetId, datasetId)
                    .eq(DataInfo::getType, ItemTypeEnum.SINGLE_DATA)
                    .in(DataInfo::getParentId, sceneIds)
                    .orderByAsc(DataInfo::getName)
                    .orderByAsc(DataInfo::getId));
            frameIds.addAll(children.stream().map(DataInfo::getId).collect(Collectors.toList()));
        }
        return frameIds.stream().distinct().collect(Collectors.toList());
    }

    private void runEvaluation(Long evaluationId, List<Long> frameIds, List<String> metrics, Long userId) {
        updateStatus(evaluationId, RunStatusEnum.RUNNING, null, userId);
        var record = modelEvaluationRecordDAO.getById(evaluationId);
        var request = new JSONObject();
        request.set("evaluationId", evaluationId);
        request.set("datasetId", record.getDatasetId());
        request.set("modelId", record.getModelId());
        request.set("dataIds", frameIds);
        request.set("configPath", record.getConfigPath());
        request.set("checkpointPath", record.getCheckpointPath());
        request.set("metrics", metrics);
        try {
            var response = HttpRequest.post(evaluationUrl)
                    .body(JSONUtil.toJsonStr(request), ContentType.JSON.getValue())
                    .timeout(6 * 60 * 60 * 1000)
                    .execute();
            if (response.getStatus() != HttpStatus.HTTP_OK) {
                throw new UsecaseException("Evaluation service error: " + response.body());
            }
            var body = JSONUtil.parseObj(response.body());
            var data = body.containsKey("data") ? body.getJSONObject("data") : body;
            if (!"OK".equalsIgnoreCase(body.getStr("code", "OK"))) {
                throw new UsecaseException(body.getStr("message", "Evaluation failed."));
            }
            modelEvaluationRecordDAO.updateById(ModelEvaluationRecord.builder()
                    .id(evaluationId)
                    .status(RunStatusEnum.SUCCESS)
                    .metrics(data.getJSONObject("metrics"))
                    .miouDataCount(data.getLong("miouDataCount"))
                    .predictions(data.getJSONObject("predictions"))
                    .outputPath(data.getStr("outputPath"))
                    .logPath(data.getStr("logPath"))
                    .updatedBy(userId)
                    .build());
        } catch (Exception e) {
            updateStatus(evaluationId, RunStatusEnum.FAILURE, e.getMessage(), userId);
        }
    }

    private void updateStatus(Long id, RunStatusEnum status, String errorReason, Long userId) {
        modelEvaluationRecordDAO.updateById(ModelEvaluationRecord.builder()
                .id(id)
                .status(status)
                .errorReason(StrUtil.maxLength(errorReason, 1024))
                .updatedBy(userId)
                .build());
    }
}
