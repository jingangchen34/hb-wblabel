package ai.basic.x1.adapter.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import javax.validation.constraints.NotNull;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class DataSceneAttributeDTO {

    private Long datasetId;

    @NotNull(message = "dataId cannot be null")
    private Long dataId;

    private String category;

    private String subType;
}
