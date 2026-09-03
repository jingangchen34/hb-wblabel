package ai.basic.x1.adapter.port.dao.mybatis.model;

import ai.basic.x1.entity.enums.PreAnnotationSourceEnum;
import ai.basic.x1.entity.enums.PreAnnotationStatusEnum;
import cn.hutool.json.JSONArray;
import cn.hutool.json.JSONObject;
import com.baomidou.mybatisplus.annotation.*;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.*;
import java.time.OffsetDateTime;

@Data @Builder @NoArgsConstructor @AllArgsConstructor
@TableName(autoResultMap = true)
public class PreAnnotationRecord {
    @TableId(type = IdType.AUTO) private Long id;
    private Long modelId;
    private Long datasetId;
    @TableField(typeHandler = JacksonTypeHandler.class) private JSONArray datasetIds;
    private String name;
    private PreAnnotationSourceEnum sourceMode;
    private PreAnnotationStatusEnum status;
    private Long dataCount;
    @TableField(typeHandler = JacksonTypeHandler.class) private JSONArray dataIds;
    @TableField(typeHandler = JacksonTypeHandler.class) private JSONArray committedDataIds;
    private String configPath;
    private String checkpointPath;
    private Integer sourcePointDim;
    private Integer modelInputDim;
    private Double iouThreshold;
    @TableField(typeHandler = JacksonTypeHandler.class) private JSONObject predictions;
    @TableField(typeHandler = JacksonTypeHandler.class) private JSONObject occArtifacts;
    private String outputPath;
    private String logPath;
    private String errorReason;
    @TableField(typeHandler = JacksonTypeHandler.class) private JSONObject commitSummary;
    private Boolean isDeleted;
    @TableField(fill = FieldFill.INSERT) private OffsetDateTime createdAt;
    @TableField(fill = FieldFill.INSERT) private Long createdBy;
    @TableField(fill = FieldFill.UPDATE) private OffsetDateTime updatedAt;
    @TableField(fill = FieldFill.UPDATE) private Long updatedBy;
    @TableField(exist = false) private String datasetName;
}
