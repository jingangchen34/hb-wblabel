package ai.basic.x1.entity;

import lombok.Builder;
import lombok.Data;

import java.util.List;

@Data
@Builder
public class OccGtReparseResultBO {

    private Long sceneId;

    private Long datasetId;

    private String obstacleFile;

    private Boolean obstacleFileFound;

    private Integer frameCount;

    private Integer importedObjectCount;

    private Integer deletedImportedObjectCount;

    private List<String> createdClasses;
}
