package ai.basic.x1.usecase;

import ai.basic.x1.adapter.dto.OccGridDTO;
import ai.basic.x1.adapter.dto.request.OccPatchDTO;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.stream.Collectors;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

public class OccAnnotationUseCase {

    @Value("${occ.annotation.path:./data/occ-annotations}")
    private String annotationPath;

    public OccGridDTO getFrame(Long dataId, ObjectMapper objectMapper) throws IOException {
        var path = gridPath(dataId);
        if (Files.exists(path)) {
            return objectMapper.readValue(path.toFile(), OccGridDTO.class);
        }

        var empty = new OccGridDTO();
        var meta = new OccGridDTO.OccMetaDTO();
        meta.setFrameId(String.valueOf(dataId));
        meta.setGridSize(new ArrayList<>());
        meta.setVoxelSize(new ArrayList<>());
        meta.setOrigin(new ArrayList<>());
        empty.setMeta(meta);
        empty.setVoxels(Collections.emptyList());
        empty.setColorMap(Collections.emptyMap());
        return empty;
    }

    public void savePatch(OccPatchDTO patch, ObjectMapper objectMapper) throws IOException {
        Files.createDirectories(root());
        objectMapper.writerWithDefaultPrettyPrinter().writeValue(patchPath(patch.getDataId()).toFile(), patch);
    }

    public Path exportClip(Long sceneId, ObjectMapper objectMapper) throws IOException {
        Files.createDirectories(root());
        var exportPath = root().resolve("scene-" + sceneId + "-occ-patches.zip");
        try (var output = new ZipOutputStream(Files.newOutputStream(exportPath))) {
            try (var stream = Files.list(root())) {
                var files = stream.filter(path -> path.getFileName().toString().endsWith(".patch.json")).collect(Collectors.toList());
                for (var path : files) {
                    output.putNextEntry(new ZipEntry(path.getFileName().toString()));
                    Files.copy(path, output);
                    output.closeEntry();
                }
            }
        }
        return exportPath;
    }

    private Path root() {
        return Path.of(annotationPath);
    }

    private Path gridPath(Long dataId) {
        return root().resolve(dataId + ".grid.json");
    }

    private Path patchPath(Long dataId) {
        return root().resolve(dataId + ".patch.json");
    }
}
