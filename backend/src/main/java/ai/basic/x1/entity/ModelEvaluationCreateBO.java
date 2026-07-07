package ai.basic.x1.entity;

import lombok.Data;

import java.util.List;

@Data
public class ModelEvaluationCreateBO {

    private Long datasetId;

    private Long modelId;

    private List<Long> dataIds;

    private String name;

    private String configPath;

    private String checkpointPath;

    private Long createdBy;

    private ModelRunFilterDataBO dataFilterParam;
}
