package ai.basic.x1.adapter.dto;

import ai.basic.x1.adapter.dto.request.ModelRunFilterDataDTO;
import lombok.Data;

import javax.validation.Valid;
import javax.validation.constraints.NotNull;
import java.util.List;

@Data
public class ModelEvaluationCreateDTO {

    private Long datasetId;

    private List<Long> datasetIds;

    @NotNull
    private Long modelId;
    private List<Long> dataIds;

    private String name;

    private String configPath;

    private String checkpointPath;

    /** Classes whose mean AP is used to select the best checkpoint. Empty means overall mAP. */
    private List<String> checkpointSelectionClasses;

    private List<String> metrics;

    /** Raw point-cloud feature dimension used to parse each .bin file. */
    private Integer sourcePointDim;

    /** Number of features passed into the selected model. */
    private Integer modelInputDim;

    @Valid
    private ModelRunFilterDataDTO dataFilterParam;
}
