package ai.basic.x1.entity;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class DataSceneAttributeBO {

    private Long datasetId;

    private Long dataId;

    private String category;

    private String subType;
}
