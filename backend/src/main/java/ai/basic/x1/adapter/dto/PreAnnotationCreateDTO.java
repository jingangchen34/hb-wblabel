package ai.basic.x1.adapter.dto;

import ai.basic.x1.entity.enums.PreAnnotationSourceEnum;
import lombok.Data;

import javax.validation.constraints.NotEmpty;
import javax.validation.constraints.NotNull;
import java.util.List;

@Data
public class PreAnnotationCreateDTO {
    @NotEmpty
    private List<Long> datasetIds;
    private Long modelId;
    private String name;
    @NotNull
    private PreAnnotationSourceEnum sourceMode;
    private String configPath;
    private String checkpointPath;
    private Integer sourcePointDim;
    private Integer modelInputDim;
    private Double iouThreshold;
}
