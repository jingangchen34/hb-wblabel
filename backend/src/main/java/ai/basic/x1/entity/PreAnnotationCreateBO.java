package ai.basic.x1.entity;

import ai.basic.x1.entity.enums.PreAnnotationSourceEnum;
import lombok.Data;

import java.util.List;

@Data
public class PreAnnotationCreateBO {
    private List<Long> datasetIds;
    private Long modelId;
    private String name;
    private PreAnnotationSourceEnum sourceMode;
    private String configPath;
    private String checkpointPath;
    private Integer sourcePointDim;
    private Integer modelInputDim;
    private Double iouThreshold;
    private Long createdBy;
}
