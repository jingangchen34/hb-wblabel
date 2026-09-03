package ai.basic.x1.adapter.dto;

import lombok.Data;
import javax.validation.constraints.NotEmpty;
import java.util.List;

@Data
public class PreAnnotationCommitDTO {
    @NotEmpty
    private List<Long> dataIds;
}
