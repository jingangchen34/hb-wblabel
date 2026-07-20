package ai.basic.x1.adapter.port.dao.mybatis.model;

import ai.basic.x1.entity.enums.RunStatusEnum;
import cn.hutool.json.JSONArray;
import cn.hutool.json.JSONObject;
import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(autoResultMap = true)
public class ModelEvaluationRecord {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long modelId;

    private Long datasetId;

    private String name;

    private RunStatusEnum status;

    private Long dataCount;

    private Long miouDataCount;

    private String configPath;

    private String checkpointPath;

    @TableField(value = "checkpoint_selection_classes", typeHandler = JacksonTypeHandler.class)
    private JSONArray checkpointSelectionClasses;

    private Integer sourcePointDim;

    private Integer modelInputDim;

    @TableField(value = "metrics", typeHandler = JacksonTypeHandler.class)
    private JSONObject metrics;

    @TableField(value = "data_ids", typeHandler = JacksonTypeHandler.class)
    private JSONArray dataIds;

    @TableField(value = "predictions", typeHandler = JacksonTypeHandler.class)
    private JSONObject predictions;

    private String outputPath;

    private String logPath;

    private String errorReason;

    private Boolean isDeleted;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT)
    private Long createdBy;

    @TableField(fill = FieldFill.UPDATE)
    private OffsetDateTime updatedAt;

    @TableField(fill = FieldFill.UPDATE)
    private Long updatedBy;

    @TableField(exist = false)
    private String datasetName;
}
