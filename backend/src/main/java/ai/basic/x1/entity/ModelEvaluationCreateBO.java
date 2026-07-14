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

    /** Raw point-cloud feature dimension used to parse each .bin file. */
    private Integer sourcePointDim;

    /** Number of features passed into the selected model. */
    private Integer modelInputDim;

    private Long createdBy;

    private ModelRunFilterDataBO dataFilterParam;
}
