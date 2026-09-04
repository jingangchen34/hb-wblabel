package ai.basic.x1.adapter.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class PreAnnotationClipDTO {
    private Long sceneId;
    private String sceneName;
    private Long firstDataId;
    private Long dataCount;
    private Long committedCount;
    private Boolean completed;
}
