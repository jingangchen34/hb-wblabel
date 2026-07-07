package ai.basic.x1.adapter.dto;

import cn.hutool.json.JSONObject;
import lombok.Builder;
import lombok.Data;

import java.util.List;

@Data
@Builder
public class ModelEvaluationCompareDTO {

    private Long evaluationId;

    private Long dataId;

    private List<JSONObject> groundTruths;

    private List<JSONObject> predictions;
}
