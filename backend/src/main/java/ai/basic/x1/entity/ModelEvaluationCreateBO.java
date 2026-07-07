package ai.basic.x1.entity;

import lombok.Data;

import java.util.List;

@Data
public class ModelEvaluationCreateBO {

    private Long datasetId;

    private List<Long> datasetIds;

    private Long modelId;

    private List<Long> dataIds;

    private String name;

    private String configPath;

    private String checkpointPath;

    private List<String> metrics;

    private Long createdBy;

    private ModelRunFilterDataBO dataFilterParam;
}
