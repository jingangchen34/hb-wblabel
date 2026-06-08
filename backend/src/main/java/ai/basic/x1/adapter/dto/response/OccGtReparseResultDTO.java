package ai.basic.x1.adapter.dto.response;

import lombok.Builder;
import lombok.Data;

import java.util.List;

@Data
@Builder
public class OccGtReparseResultDTO {

    private Long sceneId;

    private Long datasetId;

    private String obstacleFile;

    private Boolean obstacleFileFound;

    private Integer frameCount;

    private Integer importedObjectCount;

    private Integer deletedImportedObjectCount;

    private List<String> createdClasses;
}
