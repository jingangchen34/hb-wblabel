package ai.basic.x1.adapter.dto;

import ai.basic.x1.entity.enums.RunStatusEnum;
import cn.hutool.json.JSONArray;
import cn.hutool.json.JSONObject;
import lombok.Data;

import java.time.OffsetDateTime;

@Data
public class ModelEvaluationRecordDTO {

    private Long id;

    private Long modelId;

    private Long datasetId;

    private String datasetName;

    private String name;

    private RunStatusEnum status;

    private Long dataCount;

    private Long miouDataCount;

    private String configPath;

    private String checkpointPath;

    private Integer sourcePointDim;

    private Integer modelInputDim;

    private JSONObject metrics;

    private JSONArray dataIds;

    private String outputPath;

    private String logPath;

    private String errorReason;

    private OffsetDateTime createdAt;
}
