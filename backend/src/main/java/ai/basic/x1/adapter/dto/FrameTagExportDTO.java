package ai.basic.x1.adapter.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import javax.validation.constraints.NotEmpty;
import javax.validation.constraints.NotNull;
import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class FrameTagExportDTO {

    @NotNull(message = "datasetId cannot be null")
    private Long datasetId;

    /** Optional. When set, only tagged frames in this clip are exported. */
    private Long sceneId;

    @NotEmpty(message = "tags cannot be empty")
    private List<String> tags;
}
