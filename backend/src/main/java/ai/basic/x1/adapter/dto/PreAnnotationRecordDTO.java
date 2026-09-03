package ai.basic.x1.adapter.dto;

import ai.basic.x1.entity.enums.PreAnnotationSourceEnum;
import ai.basic.x1.entity.enums.PreAnnotationStatusEnum;
import cn.hutool.json.JSONArray;
import cn.hutool.json.JSONObject;
import lombok.Data;

import java.time.OffsetDateTime;

@Data
public class PreAnnotationRecordDTO {
    private Long id;
    private Long modelId;
    private Long datasetId;
    private String datasetName;
    private JSONArray datasetIds;
    private String name;
    private PreAnnotationSourceEnum sourceMode;
    private PreAnnotationStatusEnum status;
    private Long dataCount;
    private JSONArray dataIds;
    private JSONArray committedDataIds;
    private Double iouThreshold;
    private JSONObject occArtifacts;
    private String outputPath;
    private String logPath;
    private String errorReason;
    private JSONObject commitSummary;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;
}
