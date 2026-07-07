package ai.basic.x1.adapter.dto;

import ai.basic.x1.adapter.dto.request.ModelRunFilterDataDTO;
import lombok.Data;

import javax.validation.Valid;
import javax.validation.constraints.NotNull;
import java.util.List;

@Data
public class ModelEvaluationCreateDTO {

    @NotNull
    private Long datasetId;

    @NotNull
    private Long modelId;
    private List<Long> dataIds;

    private String name;

    private String configPath;

    private String checkpointPath;

    @Valid
    private ModelRunFilterDataDTO dataFilterParam;
}
