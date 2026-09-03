package ai.basic.x1.adapter.dto;

import cn.hutool.json.JSONObject;
import lombok.Builder;
import lombok.Data;

import java.util.List;

@Data
@Builder
public class PreAnnotationFrameDTO {
    private Long preAnnotationId;
    private Long dataId;
    private List<JSONObject> predictions;
    private JSONObject occArtifact;
}
