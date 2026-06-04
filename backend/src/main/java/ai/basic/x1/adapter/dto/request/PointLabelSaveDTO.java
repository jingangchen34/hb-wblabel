package ai.basic.x1.adapter.dto.request;

import lombok.Data;

@Data
public class PointLabelSaveDTO {

    private Long dataId;

    private String frameId;

    private String labelsBase64;
}

