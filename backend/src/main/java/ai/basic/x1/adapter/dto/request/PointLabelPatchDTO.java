package ai.basic.x1.adapter.dto.request;

import lombok.Data;

import java.util.List;

@Data
public class PointLabelPatchDTO {

    private Long dataId;

    private Integer pointCount;

    private List<Integer> indices;

    private String labelsBase64;
}
