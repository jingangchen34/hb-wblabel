package ai.basic.x1.usecase;

import ai.basic.x1.adapter.dto.PreAnnotationFrameDTO;
import ai.basic.x1.adapter.port.dao.DataInfoDAO;
import ai.basic.x1.adapter.port.dao.ModelDAO;
import ai.basic.x1.adapter.port.dao.PreAnnotationRecordDAO;
import ai.basic.x1.adapter.port.dao.mybatis.extension.ExtendLambdaQueryWrapper;
import ai.basic.x1.adapter.port.dao.mybatis.model.DataInfo;
import ai.basic.x1.adapter.port.dao.mybatis.model.PreAnnotationRecord;
import ai.basic.x1.entity.PreAnnotationCreateBO;
import ai.basic.x1.entity.enums.ItemTypeEnum;
import ai.basic.x1.entity.enums.PreAnnotationSourceEnum;
import ai.basic.x1.entity.enums.PreAnnotationStatusEnum;
import ai.basic.x1.usecase.exception.UsecaseCode;
import ai.basic.x1.usecase.exception.UsecaseException;
import ai.basic.x1.util.DefaultConverter;
import ai.basic.x1.util.Page;
import cn.hutool.core.collection.CollUtil;
import cn.hutool.core.date.DatePattern;
import cn.hutool.core.date.DateUtil;
import cn.hutool.core.thread.ThreadUtil;
import cn.hutool.core.util.StrUtil;
import cn.hutool.http.ContentType;
import cn.hutool.http.HttpRequest;
import cn.hutool.http.HttpStatus;
import cn.hutool.json.JSONUtil;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import java.time.OffsetDateTime;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.stream.Collectors;

/** Independent pre-annotation workflow; deliberately not coupled to model evaluation. */
public class PreAnnotationUseCase {
    private static final ExecutorService EXECUTOR = ThreadUtil.newExecutor(1);
    @Autowired private PreAnnotationRecordDAO recordDAO;
    @Autowired private DataInfoDAO dataInfoDAO;
    @Autowired private ModelDAO modelDAO;
    @Autowired private PointLabelUseCase pointLabelUseCase;
    @Value("${preannotation.service.url:http://host.docker.internal:8520}") private String serviceUrl;

    public Long create(PreAnnotationCreateBO bo) {
        var datasetIds = bo.getDatasetIds() == null ? List.<Long>of() : bo.getDatasetIds().stream().distinct().collect(Collectors.toList());
        if (CollUtil.isEmpty(datasetIds)) throw new UsecaseException(UsecaseCode.PARAM_ERROR, "Please select dataset.");
        if (bo.getSourceMode() != PreAnnotationSourceEnum.V2V && bo.getModelId() == null)
            throw new UsecaseException(UsecaseCode.PARAM_ERROR, "AI and hybrid modes require a model.");
        var frames = dataInfoDAO.list(Wrappers.lambdaQuery(DataInfo.class)
                .in(DataInfo::getDatasetId, datasetIds).eq(DataInfo::getType, ItemTypeEnum.SINGLE_DATA)
                .eq(DataInfo::getIsDeleted, false).orderByAsc(DataInfo::getDatasetId)
                .orderByAsc(DataInfo::getParentId).orderByAsc(DataInfo::getOrderName).orderByAsc(DataInfo::getId));
        var dataIds = frames.stream().map(DataInfo::getId).collect(Collectors.toList());
        if (dataIds.isEmpty()) throw new UsecaseException(UsecaseCode.PARAM_ERROR, "No frames found in selected datasets.");
        var threshold = bo.getIouThreshold() == null ? 0.5D : bo.getIouThreshold();
        if (threshold < 0 || threshold > 1) throw new UsecaseException(UsecaseCode.PARAM_ERROR, "IoU threshold must be in [0, 1].");
        var record = PreAnnotationRecord.builder().modelId(bo.getModelId()).datasetId(datasetIds.get(0))
                .datasetIds(JSONUtil.parseArray(datasetIds))
                .name(StrUtil.blankToDefault(bo.getName(), "PreLabel-" + DateUtil.format(OffsetDateTime.now().toLocalDateTime(), DatePattern.PURE_DATETIME_PATTERN)))
                .sourceMode(bo.getSourceMode()).status(PreAnnotationStatusEnum.STARTED).dataCount((long)dataIds.size())
                .dataIds(JSONUtil.parseArray(dataIds)).configPath(bo.getConfigPath()).checkpointPath(bo.getCheckpointPath())
                .sourcePointDim(bo.getSourcePointDim()).modelInputDim(bo.getModelInputDim())
                .iouThreshold(threshold).createdBy(bo.getCreatedBy()).build();
        recordDAO.save(record);
        EXECUTOR.execute(() -> run(record.getId(), bo.getCreatedBy()));
        return record.getId();
    }

    public Page<PreAnnotationRecord> page(Integer pageNo, Integer pageSize) {
        var wrapper = new ExtendLambdaQueryWrapper<PreAnnotationRecord>();
        wrapper.eq(PreAnnotationRecord::getIsDeleted, false).orderByDesc(PreAnnotationRecord::getCreatedAt);
        var result = recordDAO.getBaseMapper().selectListWithDataset(
                new com.baomidou.mybatisplus.extension.plugins.pagination.Page<>(pageNo, pageSize), wrapper);
        return DefaultConverter.convert(result, PreAnnotationRecord.class);
    }

    public PreAnnotationFrameDTO frame(Long id, Long dataId) {
        var record = requireRecord(id);
        var predictions = new ArrayList<cn.hutool.json.JSONObject>();
        if (record.getPredictions() != null && record.getPredictions().getJSONArray(String.valueOf(dataId)) != null)
            record.getPredictions().getJSONArray(String.valueOf(dataId)).forEach(v -> predictions.add(JSONUtil.parseObj(v)));
        var occ = record.getOccArtifacts() == null ? null : record.getOccArtifacts().getJSONObject(String.valueOf(dataId));
        return PreAnnotationFrameDTO.builder().preAnnotationId(id).dataId(dataId).predictions(predictions).occArtifact(occ).build();
    }

    public List<PreAnnotationFrameDTO> frames(Long id, List<Long> dataIds) {
        requireRecord(id);
        if (CollUtil.isEmpty(dataIds)) return List.of();
        return dataIds.stream().distinct().map(dataId -> frame(id, dataId)).collect(Collectors.toList());
    }

    public PreAnnotationRecord commit(Long id, List<Long> requestedDataIds, Long userId) {
        var record = requireRecord(id);
        if (record.getStatus() != PreAnnotationStatusEnum.READY)
            throw new UsecaseException(UsecaseCode.PARAM_ERROR, "Only a READY pre-annotation job can be committed.");
        var allowed = record.getDataIds().stream().map(v -> Long.valueOf(String.valueOf(v))).collect(Collectors.toSet());
        var commitIds = requestedDataIds.stream().filter(allowed::contains).distinct().collect(Collectors.toList());
        if (commitIds.isEmpty()) throw new UsecaseException(UsecaseCode.PARAM_ERROR, "No frame in this clip belongs to the job.");
        var labels = new cn.hutool.json.JSONObject();
        for (var dataId : commitIds) {
            try {
                var bytes = pointLabelUseCase.getLabels(dataId);
                if (bytes.length > 0) labels.set(String.valueOf(dataId), Base64.getEncoder().encodeToString(bytes));
            } catch (Exception ignored) { }
        }
        var payload = new cn.hutool.json.JSONObject().set("preAnnotationId", id)
                .set("dataIds", commitIds).set("occLabels", labels);
        var data = post("/commit", payload, 60 * 60 * 1000);
        var committed = new LinkedHashSet<Long>();
        if (record.getCommittedDataIds() != null) record.getCommittedDataIds().forEach(v -> committed.add(Long.valueOf(String.valueOf(v))));
        committed.addAll(commitIds);
        data.set("committedDataIds", committed);
        var status = committed.containsAll(allowed) ? PreAnnotationStatusEnum.COMMITTED : PreAnnotationStatusEnum.READY;
        recordDAO.updateById(PreAnnotationRecord.builder().id(id).status(status)
                .committedDataIds(JSONUtil.parseArray(committed)).commitSummary(data).updatedBy(userId).build());
        return recordDAO.getById(id);
    }

    public void delete(Long id, Long userId) { requireRecord(id); recordDAO.getBaseMapper().softDeleteById(id, userId); }

    private void run(Long id, Long userId) {
        recordDAO.updateById(PreAnnotationRecord.builder().id(id).status(PreAnnotationStatusEnum.RUNNING).updatedBy(userId).build());
        var r = recordDAO.getById(id);
        var payload = new cn.hutool.json.JSONObject().set("preAnnotationId", id).set("dataIds", r.getDataIds())
                .set("sourceMode", r.getSourceMode()).set("modelId", r.getModelId()).set("iouThreshold", r.getIouThreshold())
                .set("configPath", r.getConfigPath()).set("checkpointPath", r.getCheckpointPath())
                .set("sourcePointDim", r.getSourcePointDim()).set("modelInputDim", r.getModelInputDim());
        if (r.getModelId() != null) {
            var model = modelDAO.getById(r.getModelId());
            if (model != null) payload.set("modelName", model.getName()).set("modelUrl", model.getUrl());
        }
        try {
            var data = post("/preannotate", payload, 6 * 60 * 60 * 1000);
            recordDAO.updateById(PreAnnotationRecord.builder().id(id).status(PreAnnotationStatusEnum.READY)
                    .predictions(data.getJSONObject("predictions")).occArtifacts(data.getJSONObject("occArtifacts"))
                    .outputPath(data.getStr("outputPath")).logPath(data.getStr("logPath")).updatedBy(userId).build());
        } catch (Exception e) {
            recordDAO.updateById(PreAnnotationRecord.builder().id(id).status(PreAnnotationStatusEnum.FAILURE)
                    .errorReason(StrUtil.maxLength(e.getMessage(), 1000)).updatedBy(userId).build());
        }
    }

    private cn.hutool.json.JSONObject post(String path, cn.hutool.json.JSONObject payload, int timeout) {
        var response = HttpRequest.post(StrUtil.removeSuffix(serviceUrl, "/") + path)
                .body(payload.toString(), ContentType.JSON.getValue()).timeout(timeout).execute();
        if (response.getStatus() != HttpStatus.HTTP_OK) throw new UsecaseException("Pre-annotation service error: " + response.body());
        var body = JSONUtil.parseObj(response.body());
        if (!"OK".equalsIgnoreCase(body.getStr("code"))) throw new UsecaseException(body.getStr("message", "Pre-annotation failed."));
        return body.getJSONObject("data");
    }

    private PreAnnotationRecord requireRecord(Long id) {
        var r = recordDAO.getById(id);
        if (r == null || Boolean.TRUE.equals(r.getIsDeleted())) throw new UsecaseException(UsecaseCode.PARAM_ERROR, "Pre-annotation job does not exist.");
        return r;
    }
}
